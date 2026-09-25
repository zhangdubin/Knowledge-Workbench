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
3. **失败要说人话**。直连不通、代理没配、仓库 404，分别给出可操作的
   提示，而不是甩一个 httpx 堆栈。
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import settings

# 简单的内存缓存：{ "result": {...}, "ts": monotonic 秒 }
_cache: dict[str, Any] = {"result": None, "ts": 0.0}


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


async def check_update(refresh: bool = False) -> dict[str, Any]:
    """检查 GitHub 最新 Release。返回给前端的结构固定，错误也装在
    ok/error 字段里（HTTP 层面永远 200，前端按 ok 分支渲染）。"""
    current = settings.app_version
    repo = (settings.update_repo or "").strip().rstrip("/")

    out: dict[str, Any] = {
        "current": current,
        "latest": "",
        "has_update": False,
        "name": "",
        "notes": "",
        "html_url": "",
        "published_at": "",
        "repo": repo,
        "configured": bool(repo),
        "checked_at": "",
    }
    if not repo:
        out["ok"] = False
        out["error"] = "未配置升级仓库：在 .env 里设置 KB_UPDATE_REPO=owner/name 后重启容器"
        return out

    # 缓存命中（且未强制刷新）
    now = time.monotonic()
    if (not refresh and _cache["result"]
            and now - _cache["ts"] < settings.update_cache_seconds
            and _cache["result"].get("repo") == repo):
        return _cache["result"]

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    kwargs: dict[str, Any] = {"timeout": settings.update_timeout,
                              "headers": {"Accept": "application/vnd.github+json",
                                          "User-Agent": "kb-workbench-updater"}}
    if settings.update_proxy:
        kwargs["proxy"] = settings.update_proxy
    try:
        async with httpx.AsyncClient(**kwargs) as cli:
            r = await cli.get(url)
        if r.status_code == 404:
            out["ok"] = False
            out["error"] = f"仓库 {repo} 还没有任何 Release（404）：先在 GitHub 上发布一个版本"
            return out
        if r.status_code == 401 or r.status_code == 403:
            out["ok"] = False
            out["error"] = "GitHub API 拒绝访问（401/403）：未认证限额 60 次/小时/IP，稍后再试或配置 Token"
            return out
        r.raise_for_status()
        data = r.json()
    except httpx.TimeoutException:
        out["ok"] = False
        out["error"] = "访问 GitHub 超时：容器需要能直连 GitHub，或在 .env 配 KB_UPDATE_PROXY=http://<代理地址>"
        return out
    except Exception as e:                     # 网络类错误统一收口
        out["ok"] = False
        out["error"] = f"访问 GitHub 失败：{type(e).__name__}: {str(e)[:120]}"
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
    })
    _cache.update({"result": out, "ts": now})
    return out
