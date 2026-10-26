"""升级更新：检查 GitHub Releases 上有没有新版本

链路：设置页「系统更新」卡片 → GET /api/system/update/check →
GitHub API /repos/{repo}/releases/latest → 与 settings.app_version 做
语义化版本对比 → 返回是否有更新 + Release Notes。

设计要点：

1. **只检查、不代执行**。升级动作（git fetch → checkout tag → 重建镜像）
   只能发生在宿主机上（容器里没有 docker），由 scripts/upgrade.sh 执行；
   接口负责「告诉你有没有新版、改了什么、怎么升」。
2. **结果缓存 10 分钟**（update_cache_seconds）。GitHub 未认证限额
   60 次/小时/IP，多开几个浏览器页签反复点也不该把限额烧光。
   ?refresh=1 可强制跳过缓存（手动点「重新检查」时用）。
   缓存的 key 里**必须带上仓库**：换了仓库还命中旧仓库的缓存，
   界面会显示「你配的仓库没有新版本」而实际查的是上一个仓库 ——
   这种假阴性看着一切正常，最坑人。
3. **失败要说人话**。直连不通、代理连不上、仓库不存在、仓库没发过
   Release，分别给出可操作的提示，而不是甩一个 httpx 堆栈。
4. **配置读的是「生效值」**，不是环境变量：设置页里改完立即生效、
   不用重启容器；而以前用 .env 配过的用户依然有效（见 settings_store）。
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import settings
from . import settings_store as ss

# 结果缓存：key = "仓库|代理" → {"result": {...}, "ts": monotonic 秒}
# 用字典而不是单条记录，是为了同时缓存「仓库 A」「仓库 B」两份结果：
# 用户来回切换仓库时不必每次都重新请求 GitHub（限额 60 次/小时/IP）。
_cache: dict[str, dict[str, Any]] = {}

# 状态码（前端按 status 区分渲染，不要去猜 error 文案）
ST_NOT_CONFIGURED = "not_configured"      # 没配仓库
ST_INVALID_CONFIG = "invalid_config"      # 配了，但格式不合法
ST_UP_TO_DATE = "up_to_date"              # 已是最新
ST_UPDATE_AVAILABLE = "update_available"  # 有新版本
ST_REPO_NOT_FOUND = "repo_not_found"      # 仓库不存在 / 是私有的
ST_NO_RELEASE = "no_release"              # 仓库在，但没发布过 Release
ST_ACCESS_DENIED = "access_denied"        # GitHub 拒绝（限额或权限）
ST_TIMEOUT = "timeout"                    # 连接超时
ST_NETWORK = "network_error"              # 连不上 GitHub
ST_PROXY = "proxy_error"                  # 连不上代理


def parse_version(v: str) -> tuple[int, int, int] | None:
    """'v0.3.4' / '0.3.4' → (0, 3, 4)。不合法返回 None（不抛异常：
    GitHub 上的 tag 名是别人手填的，脏数据只能降级而不是炸接口）。"""
    s = (v or "").strip().lstrip("vV")
    parts = s.split(".")
    if len(parts) < 3:
        return None
    # 每段只取前导数字（'0-rc1' → 0，'4beta' → 4），
    # 拼接全部数字会把 '0-rc1' 解析成 01，坑过一版。
    import re
    nums = []
    for p in parts[:3]:
        m = re.match(r"\d+", p.strip())
        if not m:
            return None
        nums.append(int(m.group()))
    return tuple(nums)


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False          # 解析不了就当没有更新，宁可不提醒也不误报
    return a > b


def effective_config() -> dict[str, str]:
    """取「升级仓库」「出站代理」的生效值与来源

    走 settings_store 的 effective()：**文件（界面上改的）> 环境变量 >
    代码默认值**。这样设置页保存完立即生效、不用重启容器，
    而以前在 .env / compose 里配过的用户不受影响（环境变量仍然是兜底来源）。

    注意这里刻意不用 get_value()：它把空串当成「未设置」，
    而「用户在界面上明确把仓库清空」必须能盖过环境变量里的旧值，
    否则会出现「界面上明明清空了，检查更新时用的还是 .env 里那个」。
    """
    out: dict[str, str] = {}
    for key in ("update_repo", "update_proxy"):
        value, source = ss.effective(key)
        out[key] = str(value or "").strip()
        out[f"{key}_source"] = source
    return out


def _client_kwargs(proxy: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "timeout": settings.update_timeout,
        "headers": {"Accept": "application/vnd.github+json",
                    "User-Agent": "kb-workbench-updater"},
    }
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


async def _repo_state(repo: str, kwargs: dict[str, Any]) -> str:
    """仓库本身能不能查到。用来区分「仓库不存在」和「仓库没发过 Release」

    GitHub 对这两种情况一律返回 404，光看状态码分不出来 ——
    而这两种情况的处理完全不同（一个是名字写错了，一个是还没发版）。
    返回 "exists" / "missing" / "unknown"。
    """
    try:
        async with httpx.AsyncClient(**kwargs) as cli:
            r = await cli.get(f"https://api.github.com/repos/{repo}")
        if r.status_code == 200:
            return "exists"
        if r.status_code == 404:
            return "missing"
        return "unknown"
    except Exception:
        return "unknown"


async def check_update(refresh: bool = False) -> dict[str, Any]:
    """检查 GitHub 最新 Release。返回给前端的结构固定，错误也装在
    ok/error 字段里（HTTP 层面永远 200，前端按 ok 分支渲染）。"""
    current = settings.app_version
    cfg = effective_config()
    repo_raw = cfg["update_repo"]
    proxy_raw = cfg["update_proxy"]

    out: dict[str, Any] = {
        "current": current,
        "latest": "",
        "has_update": False,
        "name": "",
        "notes": "",
        "html_url": "",
        "published_at": "",
        "repo": "",
        "repo_source": cfg["update_repo_source"],
        # 只回「有没有配代理」，不回代理地址本身：代理 URL 里可能带着
        # 用户名口令，没必要在另一个接口里再抄一份出去。
        "proxy_configured": bool(proxy_raw),
        "proxy_source": cfg["update_proxy_source"],
        "configured": False,
        "status": ST_NOT_CONFIGURED,
        "error": "",
        "checked_at": "",
        "ok": False,
    }

    # ---- 未配置：说清楚去哪配，而不是让人去翻 .env ----
    if not repo_raw:
        out["status"] = ST_NOT_CONFIGURED
        out["error"] = (
            "未配置升级仓库：请到「系统设置 → 升级与更新」里填入仓库标识"
            "（owner/name，例如 your-org/kb-workbench），保存后立即生效；"
            "也可以在 .env 里设 KB_UPDATE_REPO 后重启容器。"
        )
        return out

    # ---- 配了但格式不合法（多半来自 .env，绕过了界面校验）----
    repo, err = ss.normalize_repo(repo_raw)
    if err:
        out["repo"] = repo_raw
        out["status"] = ST_INVALID_CONFIG
        out["error"] = (f"升级仓库配置不合法：{err} —— "
                        "请到「系统设置 → 升级与更新」改正后重新保存。")
        return out
    out["repo"] = repo

    proxy, proxy_err = ss.normalize_proxy(proxy_raw)
    if proxy_err:
        out["status"] = ST_INVALID_CONFIG
        out["error"] = (f"出站代理配置不合法：{proxy_err} —— "
                        "请到「系统设置 → 升级与更新」改正后重新保存。")
        return out
    out["configured"] = True

    # ---- 缓存：key 里带仓库与代理，换了配置不会拿到旧结果 ----
    cache_key = f"{repo}|{proxy}"
    now = time.monotonic()
    hit = _cache.get(cache_key)
    if (not refresh and hit
            and now - hit["ts"] < settings.update_cache_seconds):
        return dict(hit["result"])

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    kwargs = _client_kwargs(proxy)
    try:
        async with httpx.AsyncClient(**kwargs) as cli:
            r = await cli.get(url)
    except httpx.ProxyError:
        out["status"] = ST_PROXY
        out["error"] = (
            f"连不上配置的代理 {proxy} —— 请核对「系统设置 → 升级与更新」里的"
            "代理地址与端口，或把它清空改成直连。"
        )
        return out
    except httpx.ConnectError:
        out["status"] = ST_NETWORK
        out["error"] = (
            "连不上 api.github.com：容器没有出网（DNS 或防火墙拦截）。"
            "请在「系统设置 → 升级与更新」里配置出站代理，"
            "或让运维放开到 GitHub 的出站访问。"
        )
        return out
    except httpx.TimeoutException:
        out["status"] = ST_TIMEOUT
        out["error"] = (
            f"访问 GitHub 超时（{int(settings.update_timeout)} 秒）："
            "容器到 api.github.com 的链路不通。"
            "请在「系统设置 → 升级与更新」里配置出站代理，或稍后再试。"
        )
        return out
    except httpx.HTTPError:
        # 网络类错误统一收口：原始异常对用户没有意义，也不该暴露内部细节
        out["status"] = ST_NETWORK
        out["error"] = ("访问 GitHub 失败：网络请求没成功。"
                        "请检查容器出网情况，或在「系统设置 → 升级与更新」里配置代理。")
        return out
    except Exception:
        out["status"] = ST_NETWORK
        out["error"] = ("访问 GitHub 失败：请求过程中出现意外错误。"
                        "请稍后重试，或在「系统设置 → 升级与更新」里改用代理。")
        return out

    if r.status_code == 404:
        # 404 有两种可能，处置方式完全不同，分开说
        state = await _repo_state(repo, kwargs)
        if state == "exists":
            out["status"] = ST_NO_RELEASE
            out["error"] = (f"仓库 {repo} 里还没有发布任何 Release —— "
                            "在线升级依赖 GitHub Release，请先在该仓库发一个版本。")
        elif state == "missing":
            out["status"] = ST_REPO_NOT_FOUND
            out["error"] = (f"仓库 {repo} 不存在（或它是私有仓库，"
                            "而这里没有配置 GitHub Token）—— "
                            "请核对「系统设置 → 升级与更新」里的 owner/name 是否写对。")
        else:
            out["status"] = ST_REPO_NOT_FOUND
            out["error"] = (f"GitHub 返回 404：仓库 {repo} 可能不存在、是私有仓库，"
                            "或者还没有发布任何 Release。"
                            "请核对仓库名，或在仓库上发布一个 Release。")
        return out
    if r.status_code in (401, 403):
        out["status"] = ST_ACCESS_DENIED
        out["error"] = ("GitHub 拒绝了这次访问（401/403）："
                        "可能是未认证限额（60 次/小时/IP）用完了，"
                        "也可能是仓库是私有的。等一会儿再试，或换一个公开仓库。")
        return out
    if r.status_code == 429:
        out["status"] = ST_ACCESS_DENIED
        out["error"] = ("GitHub 限流了（429）：未认证限额 60 次/小时/IP 已用完，"
                        "请稍后再试。")
        return out
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        out["status"] = ST_NETWORK
        out["error"] = (f"GitHub 返回了 {r.status_code}："
                        "稍后重试；若一直失败，多半是仓库名写错或仓库不可访问。")
        return out
    try:
        data = r.json()
    except Exception:
        out["status"] = ST_NETWORK
        out["error"] = "GitHub 返回的内容不是预期的 JSON，请稍后重试。"
        return out

    tag = str(data.get("tag_name") or "")
    out.update({
        "ok": True,
        "latest": tag,
        "name": str(data.get("name") or ""),
        "notes": str(data.get("body") or ""),
        "html_url": str(data.get("html_url") or ""),
        "published_at": str(data.get("published_at") or ""),
        "has_update": is_newer(tag, current),
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "error": "",
    })
    out["status"] = ST_UPDATE_AVAILABLE if out["has_update"] else ST_UP_TO_DATE
    # 只缓存成功结果：一次网络抖动不该被缓存住 10 分钟
    _cache[cache_key] = {"result": dict(out), "ts": now}
    return out
