"""出网路径：代理能用就用代理，代理坏了自动改走直连

为什么需要这个模块：
    实测踩到过一种很难查的代理故障 ——
    代理地址配着、端口开着、TCP 也连得上，
    但代理往上游取东西时**一直挂着不返回**：
        容器 → 代理   TCP OK，0.00s
        代理 → GitHub  一直等，15s 超时
    而**直连是通的**（0.7s 就拿到）。

    这时候应用如果死抱代理不放，用户看到的就是一句
    「访问 GitHub 超时（8 秒）：容器到 api.github.com 的链路不通」——
    把矛头指向了容器出网，可容器出网好着呢。
    用户只能自己一个个猜：是不是 DNS？是不是防火墙？是不是仓库写错了？

    所以这里把「走哪条路」变成自动的事：
      - 配了代理：代理与直连**同时**发起，谁先成功用谁；
        代理输了就自动改走直连，并明确记下「这次绕过了代理」。
      - 没配代理：只走直连。
    绕过了要**明说**（route.bypassed），不能装作一切正常。

为什么用「同时发起」而不是「先代理、失败再直连」：
    先代理再回退，坏代理每次都要先赔上一个超时（8 秒）才轮到直连；
    同时发起，总耗时取两者里慢的那个，而不是相加。
    顺带还白得一份诊断：两条路各自通不通，一目了然。

为什么下载大文件也走这里：
    一键升级要下 100MB+ 的镜像包，不能靠试错重来 ——
    所以升级那条路先用 resolve_route() 探出该走哪条，再下。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# 代理「自己不行」的错误：连不上代理、代理握手失败、代理那侧超时。
# 这些都说明「这条路断了」，换条路可能就通了。
#
# 注意不含 HTTPStatusError：404/403 是**有意义的回答**（仓库不存在、被拒绝），
# 换条路重试也不会变好，反而把真实原因糊掉。
ROUTE_BROKEN = (httpx.ProxyError, httpx.ConnectError, httpx.TimeoutException)

# 探测结果的缓存时长。
#
# 为什么短（120 秒）：代理故障经常是「进程还活着但已经不干活了」，
# 修好代理之后不该再等十几分钟才生效 ——
# 两分钟足够让「刚修好代理」的人立刻看到变化，又不至于每次点检查都重新探。
PROBE_TTL = 120.0


class RouteError(httpx.HTTPError):
    """两条出网路径都不通时抛出。

    继承 httpx.HTTPError 是为了不破坏调用方已有的 except 链 ——
    上层本来就把 httpx 的各种错误统一收口成一句人话，
    这里不该让它们漏网。

    带一个 .route，调用方据此判断「是代理的问题还是网络的问题」。
    """

    def __init__(self, route: "Route", cause: BaseException | None = None):
        super().__init__(str(cause) if cause else route.note)
        self.route = route
        self.cause = cause


@dataclass
class Route:
    """一次请求实际走了哪条路，以及两条路各自通不通"""
    proxy: str = ""
    use_proxy: bool = False        # 这次该走代理吗
    proxy_ok: bool = False         # 代理这条路通不通
    direct_ok: bool = False        # 直连这条路通不通
    bypassed: bool = False         # 配了代理但最后走的是直连
    note: str = ""                 # 给人看的说明
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.proxy_ok or self.direct_ok

    def describe(self) -> str:
        """一句话说清「这次是怎么通的」"""
        if not self.proxy:
            return "直连"
        if self.bypassed:
            return "配置的代理不通，已自动改用直连"
        if self.proxy_ok:
            return "经由代理"
        return "代理与直连都不通"


_probe_cache: dict[str, tuple[float, Route]] = {}


def _cache_key(proxy: str, url: str) -> str:
    return f"{proxy}|{url}"


async def _one_shot(url: str, *, proxy: str, timeout: float,
                    headers: dict[str, str] | None, **kw: Any) -> httpx.Response:
    """按指定路径发一次请求。失败就抛，由调用方决定换不换路"""
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "headers": headers or {},
    }
    if proxy:
        kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**kwargs) as cli:
        return await cli.get(url, **kw)


async def resolve_route(proxy: str, *, timeout: float, probe_url: str,
                        headers: dict[str, str] | None = None,
                        use_cache: bool = True) -> Route:
    """探出该走哪条路：代理优先，代理不行就直连

    用于**大文件下载**这种「试错代价高」的场景：
    先花一次小请求探路，探到了再下大文件。

    参数 probe_url 一般填一个轻量的探测地址（如 https://api.github.com/）。
    """
    key = _cache_key(proxy, probe_url)
    if use_cache:
        hit = _probe_cache.get(key)
        if hit and (time.monotonic() - hit[0]) < PROBE_TTL:
            return hit[1]

    route = await _race(proxy, timeout=timeout, probe_url=probe_url,
                        headers=headers)
    _probe_cache[key] = (time.monotonic(), route)
    return route


async def fetch(url: str, *, proxy: str, timeout: float,
                headers: dict[str, str] | None = None,
                **kw: Any) -> tuple[httpx.Response, Route]:
    """发一次请求，自动在代理与直连之间挑一条能通的路

    返回 (响应, 实际走的路)。两条路都不通时抛最后一个异常。
    """
    route, resp = await _race_request(url, proxy=proxy, timeout=timeout,
                                       headers=headers, **kw)
    if resp is None:
        # _race_request 已经把最后一个异常留在 route.extra 里了
        cause = route.extra.get("error")
        raise RouteError(route, cause) from cause
    return resp, route


async def _race(proxy: str, *, timeout: float, probe_url: str,
                headers: dict[str, str] | None) -> Route:
    """同时试代理与直连，看哪条通"""
    if not proxy:
        try:
            await _one_shot(probe_url, proxy="", timeout=timeout,
                            headers=headers)
            return Route(proxy="", use_proxy=False, direct_ok=True,
                         note="直连")
        except Exception as e:  # noqa: BLE001 - 探测只关心通不通
            return Route(proxy="", use_proxy=False, direct_ok=False,
                         note="直连不通", extra={"error": e})

    results = await asyncio.gather(
        _one_shot(probe_url, proxy=proxy, timeout=timeout, headers=headers),
        _one_shot(probe_url, proxy="", timeout=timeout, headers=headers),
        return_exceptions=True,
    )
    proxy_ok = not isinstance(results[0], BaseException)
    direct_ok = not isinstance(results[1], BaseException)
    if proxy_ok:
        return Route(proxy=proxy, use_proxy=True, proxy_ok=True,
                     direct_ok=direct_ok, note="经由代理")
    if direct_ok:
        return Route(proxy=proxy, use_proxy=False, proxy_ok=False,
                     direct_ok=True, bypassed=True,
                     note="配置的代理不通，已自动改用直连",
                     extra={"proxy_error": results[0]})
    return Route(proxy=proxy, use_proxy=False, proxy_ok=False, direct_ok=False,
                 note="代理与直连都不通",
                 extra={"error": results[0], "direct_error": results[1]})


async def _race_request(url: str, *, proxy: str, timeout: float,
                         headers: dict[str, str] | None,
                         **kw: Any) -> tuple[Route, httpx.Response | None]:
    """同时发起真实请求，谁先成功用谁"""
    if not proxy:
        try:
            resp = await _one_shot(url, proxy="", timeout=timeout,
                                    headers=headers, **kw)
            return Route(proxy="", use_proxy=False, direct_ok=True), resp
        except Exception as e:  # noqa: BLE001
            return Route(proxy="", direct_ok=False, note="直连不通",
                         extra={"error": e}), None

    tasks = [
        asyncio.create_task(_one_shot(url, proxy=proxy, timeout=timeout,
                                      headers=headers, **kw)),
        asyncio.create_task(_one_shot(url, proxy="", timeout=timeout,
                                      headers=headers, **kw)),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    # 先把「谁成功了」记下来；没成功的那条可能是异常，也可能还在跑。
    winner: httpx.Response | None = None
    proxy_ok = False
    direct_ok = False
    errors: list[BaseException] = []
    for task in tasks:
        if task in done and not task.cancelled():
            exc = task.exception()
            if exc is None:
                winner = task.result()
                if task is tasks[0]:
                    proxy_ok = True
                else:
                    direct_ok = True
                # 两条路都成功时，代理优先 ——
                # 用户既然配了代理，就该用代理。
                # （不 break 的话下面那个成功的会把 winner 覆盖掉，
                #   报告出来的路线就与实际用的那条对不上了。）
                break
            else:
                errors.append(exc)

    # 输的那条：已经失败的就算了，还在跑的取消掉（省下带宽）。
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    if winner is None:
        # 两条都失败：再看一下还没结束的那条的结果。
        err = errors[0] if errors else RuntimeError("两条出网路径都不通")
        return Route(proxy=proxy, proxy_ok=proxy_ok, direct_ok=direct_ok,
                     note="代理与直连都不通", extra={"error": err}), None

    if proxy_ok:
        return Route(proxy=proxy, use_proxy=True, proxy_ok=True,
                     direct_ok=direct_ok, note="经由代理"), winner
    return Route(proxy=proxy, use_proxy=False, proxy_ok=False, direct_ok=True,
                 bypassed=True, note="配置的代理不通，已自动改用直连",
                 extra={"proxy_error": (errors[0] if errors else None)}), winner

async def probe_paths(proxy: str, *, timeout: float,
                      probe_url: str = "https://api.github.com/",
                      headers: dict[str, str] | None = None) -> dict[str, Any]:
    """分别测代理与直连，给出各自的耗时与结论

    与 resolve_route 的区别：
      - resolve_route：只为了「选一条路」，结果是给程序用的；
      - probe_paths：只为了「告诉人哪条路坏了」，结果是给人看的。

    为什么要单独提供：
        「检查更新」是顺带测的 —— 它测的是「能不能连到 GitHub」，
        顺带才暴露代理坏没坏。用户想知道的往往是反过来：
        「我配的代理到底能不能用？」

        实测踩到过一种很难查的代理故障：
        端口开着、TCP 连得上，但代理往上游取东西时一直挂着不返回。
        从外面看「代理配了、也连上了」，一切像好的，
        只有真正发一次请求才知道它不干活。

        所以这里把两条路分别测一遍，各自给出耗时与结论。
    """
    import time as _t

    async def _timed(use_proxy: bool) -> tuple[bool, int, str]:
        t0 = _t.monotonic()
        try:
            await _one_shot(probe_url, proxy=(proxy if use_proxy else ""),
                            timeout=timeout, headers=headers)
            return True, int((_t.monotonic() - t0) * 1000), ""
        except Exception as e:  # noqa: BLE001 - 探测只关心通不通
            return False, int((_t.monotonic() - t0) * 1000), type(e).__name__

    if proxy:
        # 两条路同时测：用户等的是「两条路里慢的那条」，
        # 不是它们加起来 —— 坏代理不该让探测多花一倍时间。
        results = await asyncio.gather(
            _timed(True), _timed(False), return_exceptions=False)
        p_ok, p_ms, p_err = results[0]
        d_ok, d_ms, d_err = results[1]
    else:
        p_ok, p_ms, p_err = False, 0, "未配置代理"
        d_ok, d_ms, d_err = await _timed(False)

    bypassed = bool(proxy) and (not p_ok) and d_ok
    if not proxy:
        note = "未配置出站代理，走直连"
    elif bypassed:
        note = "代理不通、直连通 —— 已自动改用直连"
    elif p_ok:
        note = "代理可用"
    elif d_ok:
        note = "代理不通、直连通"
    else:
        note = "代理与直连都不通"

    return {
        "proxy_configured": bool(proxy),
        "proxy_ok": p_ok,
        "proxy_ms": p_ms,
        "proxy_error": p_err,
        "direct_ok": d_ok,
        "direct_ms": d_ms,
        "direct_error": d_err,
        "bypassed": bypassed,
        "note": note,
    }

