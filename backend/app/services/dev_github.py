"""在线协同模式的外网取材：GitHub 开源项目 + 网络搜索

这一层只做「只读取材」：仓库信息、README、源码片段、issue、代码检索。
不克隆、不写回、不执行仓库里的任何东西 —— 把外部代码拉进本机执行
是另一件事（要沙箱、要签名），不该由一个知识工作台顺手做掉。

出网纪律（这一层是模块里唯一会发外网请求的地方，所以规矩写在这里）：
  1. 每次请求前先过 dev_config.assert_outbound —— 离线模式下一律不发；
  2. 令牌只出现在请求头里，不进日志、不进异常消息、不进返回值；
  3. 令牌没配也能用（GitHub 匿名限额 60 次/小时），只是检索能力受限，
     这件事要如实告诉调用方，不能假装「搜过了」。
"""
from __future__ import annotations

import base64
import logging
from urllib.parse import quote, urlencode

import httpx

from . import dev_config

log = logging.getLogger("kb.dev.github")

API_BASE = "https://api.github.com"
UA = "kb-workbench-dev/1.0"

# 一次取材最多读多少字节：README 与源码片段都可能是几十 MB 的文件
MAX_SNIPPET_BYTES = 120 * 1024
MAX_LIST = 50


class GitHubError(RuntimeError):
    """GitHub 调用失败（网络故障、鉴权失败、限流、仓库不存在）"""


class SearchUnavailable(RuntimeError):
    """网络搜索没配或不可用 —— 调用方要如实降级，不能假装搜过"""


def _headers(token: str) -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = "Bearer %s" % token.strip()
    return h


async def _get_json(client: httpx.AsyncClient, url: str, token: str,
                    params: dict | None = None) -> dict:
    """一次 GitHub JSON 请求；失败时抛 GitHubError（消息里绝不含令牌）"""
    try:
        r = await client.get(url, headers=_headers(token), params=params)
    except Exception as e:
        raise GitHubError("GitHub 请求失败：%s" % type(e).__name__) from e
    if r.status_code == 404:
        raise GitHubError("GitHub 上找不到这个资源（404）")
    if r.status_code == 401:
        raise GitHubError("GitHub 令牌无效或已过期（401）")
    if r.status_code == 403:
        # 403 既可能是令牌权限不足，也可能是匿名限额用完
        remain = r.headers.get("x-ratelimit-remaining")
        extra = "（匿名额度已用完，配置令牌可提高限额）" if remain == "0" else ""
        raise GitHubError("GitHub 拒绝访问（403）%s" % extra)
    if r.status_code >= 400:
        raise GitHubError("GitHub 返回 %s" % r.status_code)
    try:
        return r.json()
    except Exception as e:
        raise GitHubError("GitHub 返回的不是合法 JSON") from e


def _guard(cfg: dict, mode: str, what: str) -> None:
    """出网闸门：离线模式直接拦下，绝不发请求"""
    dev_config.assert_outbound(mode, what, cfg=cfg)


def _clip(text: str, limit: int = MAX_SNIPPET_BYTES) -> str:
    t = text or ""
    if len(t.encode("utf-8", "replace")) <= limit:
        return t
    return t.encode("utf-8", "replace")[:limit].decode("utf-8", "ignore") + "\n…（已截断）"


async def repo_overview(cfg: dict, mode: str, spec: dict) -> dict:
    """仓库名片：名称、描述、星标、默认分支、许可证、主题"""
    _guard(cfg, mode, "GitHub 仓库检索")
    if not dev_config.is_repo_spec_ok(spec):
        raise GitHubError("仓库标识不完整，需要 owner/repo")
    url = "%s/repos/%s/%s" % (API_BASE, quote(spec["owner"]), quote(spec["repo"]))
    token = (cfg.get("github") or {}).get("token") or ""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        data = await _get_json(client, url, token)
    return {
        "full_name": data.get("full_name") or "",
        "description": data.get("description") or "",
        "stars": data.get("stargazers_count") or 0,
        "forks": data.get("forks_count") or 0,
        "default_branch": data.get("default_branch") or "",
        "license": ((data.get("license") or {}) or {}).get("spdx_id") or "",
        "topics": (data.get("topics") or [])[:12],
        "language": data.get("language") or "",
        "url": data.get("html_url") or "",
        "updated_at": data.get("pushed_at") or "",
    }


async def readme(cfg: dict, mode: str, spec: dict) -> str:
    """读 README 正文（GitHub 返回的是 base64）"""
    _guard(cfg, mode, "GitHub README 读取")
    if not dev_config.is_repo_spec_ok(spec):
        raise GitHubError("仓库标识不完整，需要 owner/repo")
    url = "%s/repos/%s/%s/readme" % (API_BASE, quote(spec["owner"]), quote(spec["repo"]))
    token = (cfg.get("github") or {}).get("token") or ""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        data = await _get_json(client, url, token)
    raw = data.get("content") or ""
    try:
        text = base64.b64decode(raw).decode("utf-8", "replace")
    except Exception:
        text = raw
    return _clip(text)


async def file_content(cfg: dict, mode: str, spec: dict, path: str) -> str:
    """读仓库里某个文件的原文"""
    _guard(cfg, mode, "GitHub 文件读取")
    if not dev_config.is_repo_spec_ok(spec):
        raise GitHubError("仓库标识不完整，需要 owner/repo")
    branch = spec.get("branch") or "HEAD"
    url = "%s/repos/%s/%s/contents/%s?ref=%s" % (
        API_BASE, quote(spec["owner"]), quote(spec["repo"]), quote(path), quote(branch))
    token = (cfg.get("github") or {}).get("token") or ""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        data = await _get_json(client, url, token)
    if isinstance(data, list):
        raise GitHubError("这是一个目录，不是文件：%s" % path)
    raw = data.get("content") or ""
    try:
        text = base64.b64decode(raw).decode("utf-8", "replace")
    except Exception:
        text = raw
    return _clip(text)


async def list_files(cfg: dict, mode: str, spec: dict, path: str = "") -> list[dict]:
    """列目录（只列一层，不递归 —— 递归会把整个仓库拖下来）"""
    _guard(cfg, mode, "GitHub 目录列举")
    if not dev_config.is_repo_spec_ok(spec):
        raise GitHubError("仓库标识不完整，需要 owner/repo")
    branch = spec.get("branch") or ""
    url = "%s/repos/%s/%s/contents/%s" % (
        API_BASE, quote(spec["owner"]), quote(spec["repo"]), quote(path))
    params = {"ref": branch} if branch else None
    token = (cfg.get("github") or {}).get("token") or ""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        data = await _get_json(client, url, token, params=params)
    if not isinstance(data, list):
        return []
    out = []
    for item in data[:MAX_LIST]:
        out.append({
            "name": item.get("name") or "",
            "path": item.get("path") or "",
            "type": item.get("type") or "",
            "size": item.get("size") or 0,
        })
    return out


async def issues(cfg: dict, mode: str, spec: dict, limit: int = 20) -> list[dict]:
    """读 issue（开源项目里很多坑都写在 issue 里）"""
    _guard(cfg, mode, "GitHub issue 读取")
    if not dev_config.is_repo_spec_ok(spec):
        raise GitHubError("仓库标识不完整，需要 owner/repo")
    url = "%s/repos/%s/%s/issues" % (API_BASE, quote(spec["owner"]), quote(spec["repo"]))
    token = (cfg.get("github") or {}).get("token") or ""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        data = await _get_json(client, url, token,
                               params={"state": "all", "per_page": min(limit, MAX_LIST)})
    if not isinstance(data, list):
        return []
    out = []
    for it in data[:limit]:
        # GitHub 把 PR 也放在 issues 接口里，这里标出来免得混淆
        out.append({
            "number": it.get("number"),
            "title": it.get("title") or "",
            "state": it.get("state") or "",
            "is_pr": bool(it.get("pull_request")),
            "body": _clip(it.get("body") or "", 800),
            "url": it.get("html_url") or "",
        })
    return out


async def code_search(cfg: dict, mode: str, spec: dict, query: str) -> list[dict]:
    """在仓库里搜代码（需要令牌：GitHub 的代码检索不认匿名请求）"""
    _guard(cfg, mode, "GitHub 代码检索")
    if not dev_config.is_repo_spec_ok(spec):
        raise GitHubError("仓库标识不完整，需要 owner/repo")
    token = (cfg.get("github") or {}).get("token") or ""
    if not token:
        raise GitHubError("GitHub 代码检索需要令牌，请先在开发设置里配置")
    q = "%s repo:%s/%s" % (query, spec["owner"], spec["repo"])
    url = "%s/search/code" % API_BASE
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        data = await _get_json(client, url, token, params={"q": q, "per_page": 10})
    items = (data or {}).get("items") or []
    out = []
    for it in items[:10]:
        fragment = ""
        tm = it.get("text_matches") or []
        if tm:
            fragment = tm[0].get("fragment") or ""
        out.append({
            "path": it.get("path") or "",
            "repo": "%s/%s" % (spec["owner"], spec["repo"]),
            "url": it.get("html_url") or "",
            "snippet": _clip(fragment, 600),
        })
    return out


async def web_search(cfg: dict, mode: str, query: str, limit: int = 5) -> list[dict]:
    """网络知识检索（自建搜索服务；没配就明确不可用）

    为什么不做「默认接一个公共搜索引擎」：
        公共搜索接口要么要密钥、要么条款上不允许拿来做程序化检索。
    与其埋一个随时会失效、还会悄悄把查询发出去的默认值，
    不如把「没配就说没配」写清楚 —— 这正是需求里「不要假装」那一条。
    """
    _guard(cfg, mode, "网络知识检索")
    ws = cfg.get("web_search") or {}
    if not ws.get("enabled") or not (ws.get("endpoint") or "").strip():
        raise SearchUnavailable("未配置网络搜索服务：网络知识检索不可用")
    endpoint = ws["endpoint"].strip()
    sep = "&" if "?" in endpoint else "?"
    url = "%s%s%s" % (endpoint, sep, urlencode({"q": query, "format": "json"}))
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise SearchUnavailable("网络搜索服务不可达：%s" % type(e).__name__) from e
    items = data.get("results") if isinstance(data, dict) else data
    out = []
    for it in (items or [])[:limit]:
        if not isinstance(it, dict):
            continue
        out.append({
            "title": it.get("title") or it.get("name") or "",
            "url": it.get("url") or it.get("link") or "",
            "snippet": _clip(it.get("content") or it.get("snippet") or "", 600),
            "engine": it.get("engine") or "",
        })
    return out


async def collect_repo_context(cfg: dict, mode: str, spec: dict,
                               query: str = "") -> dict:
    """一次性把一个仓库的可用材料收齐（名片 + README + 目录 + issue）

    任何一项失败都不影响其它项 —— 取材是「锦上添花」，
    失败了要如实告诉用户哪一项没取到，而不是整个请求报错。
    """
    out = {"label": dev_config.repo_label(spec), "ok": [], "failed": [], "data": {}}
    if not dev_config.is_repo_spec_ok(spec):
        out["failed"].append({"what": "仓库标识", "reason": "需要 owner/repo"})
        return out
    try:
        out["data"]["overview"] = await repo_overview(cfg, mode, spec)
        out["ok"].append("仓库名片")
    except GitHubError as e:
        out["failed"].append({"what": "仓库名片", "reason": str(e)})
    try:
        out["data"]["readme"] = await readme(cfg, mode, spec)
        out["ok"].append("README")
    except GitHubError as e:
        out["failed"].append({"what": "README", "reason": str(e)})
    try:
        out["data"]["files"] = await list_files(cfg, mode, spec, "")
        out["ok"].append("目录结构")
    except GitHubError as e:
        out["failed"].append({"what": "目录结构", "reason": str(e)})
    try:
        out["data"]["issues"] = await issues(cfg, mode, spec, 10)
        out["ok"].append("issue")
    except GitHubError as e:
        out["failed"].append({"what": "issue", "reason": str(e)})
    if query:
        try:
            out["data"]["code"] = await code_search(cfg, mode, spec, query)
            out["ok"].append("代码检索")
        except GitHubError as e:
            out["failed"].append({"what": "代码检索", "reason": str(e)})
    return out
