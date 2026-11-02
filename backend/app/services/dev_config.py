"""软件开发模块的运行期配置：GitHub 令牌、本地模型端点、出网总开关

为什么单独一个文件，不并进 ai_config：
    这两类配置管的不是一件事。
    ai_config 管「聊天/助理用哪个大模型」，是全站 AI 能力的入口；
    这里管的是「开发流程用哪些外部依赖」——
    GitHub 仓库与令牌、离线模式的本地模型端点、以及出网总闸门。
    混在一起的后果是两头不讨好：
    为了配一个 GitHub 令牌要去改 AI 设置页；
    或者把开发模块的出网开关跟问答的模型配置绑在一起，
    关掉开发的外网顺手把问答也关了。

密钥口径与 ai_config 一致：磁盘上是明文（文件权限交给部署方保证），
对外一律掩码返回，日志里一次都不出现。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("kb.dev.config")

def config_path() -> Path:
    """配置文件所在路径。

    优先跟系统设置走（容器里是 /app/data，与 ai_config.json 同一个目录）；
    允许用 KB_DEV_CONFIG 环境变量覆盖 —— 测试与多实例部署时用得上。
    """
    override = os.environ.get("KB_DEV_CONFIG")
    if override:
        p = Path(override)
    else:
        try:
            from ..config import settings
            d = (settings.data_dir or "").strip()
            p = Path(d) / "dev_config.json" if d else (
                Path(__file__).resolve().parent.parent.parent / "data" / "dev_config.json")
        except Exception:
            p = Path(__file__).resolve().parent.parent.parent / "data" / "dev_config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ============ 模式常量 ============

MODE_OFFLINE = "offline"   # 离线闭环：只用本机知识 + 本地模型
MODE_ONLINE = "online"     # 在线协同：AI + GitHub + 网络知识 + 喂养源码
MODES = (MODE_OFFLINE, MODE_ONLINE)

MODE_LABEL = {MODE_OFFLINE: "离线闭环", MODE_ONLINE: "在线协同"}


class OutboundBlocked(RuntimeError):
    """出网被闸门拦下。

    单独一个异常类型，是为了让上层能把它和「网络故障」区分开：
    网络故障要提示重试，出网被拦要提示「你处在离线模式」或者
    「全局出网开关关着」—— 两者的处置方式完全不同。
    """


DEFAULT_CONFIG: dict[str, Any] = {
    # 默认离线：软件开发默认不应该往外发东西，要联网得显式打开
    "mode": MODE_OFFLINE,
    # 出网总闸门。关掉之后，GitHub 与网络搜索一律不发请求（连探测都不发）
    "outbound_enabled": True,
    "github": {
        "token": "",
        "repos": [],       # [{"owner": "", "repo": "", "branch": "", "note": ""}]
    },
    "local_model": {
        # OpenAI 兼容的本地端点，如 http://127.0.0.1:11434/v1/chat/completions
        "base_url": "",
        "model": "",
        "api_key": "",     # 本地端点一般留空；填了也只发给本地地址
        "temperature": 0.3,
        "max_tokens": 2048,
    },
    "web_search": {
        # 自建搜索服务的地址（SearxNG 之类）：/search?format=json&q=...
        # 没配就明确降级，绝不假装搜过
        "endpoint": "",
        "enabled": False,
    },
}

SECRET_FIELDS = ("github.token", "local_model.api_key")


def _deep_merge(base: dict, patch: dict) -> dict:
    """逐层合并，避免旧配置文件缺字段导致 KeyError"""
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    """读配置（缺字段用默认值补齐）"""
    cfg: dict = {}
    path = config_path()
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("开发模块配置读取失败，改用默认配置：%s", type(e).__name__)
            cfg = {}
    merged = _deep_merge(DEFAULT_CONFIG, cfg if isinstance(cfg, dict) else {})
    # mode 只认两个值：脏数据不能让系统落进「不存在的模式」里
    if merged.get("mode") not in MODES:
        merged["mode"] = DEFAULT_CONFIG["mode"]
    return merged


def _looks_masked(value: str) -> bool:
    v = (value or "").strip()
    return (not v) or v.startswith("***") or "\u2022" in v or "\u25cf" in v


def save_config(cfg: dict) -> dict:
    """保存配置。

    掩码保护与 ai_config 同一套口径：
    前端拿到的密钥是掩码（***abcd），原样回传时视为「不修改」，
    保留磁盘上的真值 —— 否则前端只改了个仓库地址，就把令牌抹没了。
    """
    current = load_config()
    payload = {k: v for k, v in (cfg or {}).items() if k != "clear_secrets"}
    merged = _deep_merge(current, payload)

    # clear_secrets 支持三种写法：True（全清）、字段名（清一个）、字段名列表（清多个）
    clear = (cfg or {}).get("clear_secrets")
    if clear is True:
        cleared = set(SECRET_FIELDS)
    elif isinstance(clear, str):
        cleared = {clear}
    elif isinstance(clear, (list, tuple, set)):
        cleared = {str(x) for x in clear}
    else:
        cleared = set()

    for field in SECRET_FIELDS:
        head, _, tail = field.partition(".")
        incoming = str((merged.get(head) or {}).get(tail) or "")
        if field in cleared:
            merged.setdefault(head, {})[tail] = ""
        elif _looks_masked(incoming):
            merged.setdefault(head, {})[tail] = current.get(head, {}).get(tail, "")
    merged["mode"] = merged.get("mode") if merged.get("mode") in MODES else DEFAULT_CONFIG["mode"]
    merged.setdefault("github", {})["repos"] = [
        normalize_repo(r) for r in (merged.get("github", {}).get("repos") or [])]

    try:
        config_path().write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception as e:
        log.warning("开发模块配置写入失败：%s", type(e).__name__)
    return merged


def mask(value: str) -> str:
    """密钥掩码：只留后四位"""
    v = (value or "").strip()
    if not v:
        return ""
    return "***" + v[-4:] if len(v) > 4 else "***"


def public_config() -> dict:
    """对外的配置（密钥掩码）"""
    cfg = load_config()
    out = json.loads(json.dumps(cfg))
    out["github"]["token"] = mask(cfg.get("github", {}).get("token", ""))
    out["github"]["token_set"] = bool((cfg.get("github", {}).get("token") or "").strip())
    out["local_model"]["api_key"] = mask(cfg.get("local_model", {}).get("api_key", ""))
    out["local_model"]["api_key_set"] = bool((cfg.get("local_model", {}).get("api_key") or "").strip())
    return out


def get_secret(path: str) -> str:
    """取密钥明文（只在本进程内调用，绝不进日志）"""
    cfg = load_config()
    head, _, tail = path.partition(".")
    return str((cfg.get(head) or {}).get(tail) or "")


# ============ GitHub 仓库解析 ============

_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def normalize_repo(raw: Any) -> dict:
    """把各种写法归一成 {"owner","repo","branch","note"}

    接受：owner/repo、https://github.com/owner/repo、github.com/owner/repo、
    git@github.com:owner/repo.git —— 用户多半是从浏览器地址栏直接粘过来的。
    """
    text = str(raw or "").strip()
    if not text and not isinstance(raw, dict):
        return {"owner": "", "repo": "", "branch": "", "note": ""}
    if isinstance(raw, dict):
        owner = str(raw.get("owner") or "").strip()
        repo = str(raw.get("repo") or "").strip()
        branch = str(raw.get("branch") or "").strip()
        note = str(raw.get("note") or "").strip()
        if owner and repo:
            return {"owner": owner, "repo": repo, "branch": branch, "note": note}
        text = ("%s/%s" % (owner, repo)).strip("/")
    text = text.rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    text = re.sub(r"^(git@|https?://)", "", text)
    text = re.sub(r"^github\.com[:/]", "", text)
    parts = [p for p in text.split("/") if p]
    owner = parts[0] if len(parts) >= 2 else ""
    repo = parts[1] if len(parts) >= 2 else ""
    branch = ""
    if len(parts) >= 4 and parts[2] in ("tree", "blob"):
        branch = parts[3]
    return {"owner": owner, "repo": repo, "branch": branch, "note": ""}


def repo_label(spec: dict) -> str:
    owner = (spec or {}).get("owner") or ""
    repo = (spec or {}).get("repo") or ""
    if not owner or not repo:
        return ""
    return "%s/%s" % (owner, repo)


def is_repo_spec_ok(spec: dict) -> bool:
    """仓库标识是否完整（owner/repo 都要有）"""
    owner = (spec or {}).get("owner") or ""
    repo = (spec or {}).get("repo") or ""
    if not owner or not repo:
        return False
    return bool(_REPO_RE.match("%s/%s" % (owner, repo)))


# ============ 出网闸门（整个模块唯一的出网入口） ============

def outbound_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    return bool(cfg.get("outbound_enabled", True))


def assert_outbound(mode: str, what: str = "外部请求", cfg: dict | None = None) -> None:
    """出网闸门：离线模式（或总开关关闭）时，任何外网请求都不许发。

    为什么要有这一道：
        「离线闭环」这个承诺，靠的是「所有出网调用都从这一个口子过」，
    而不是靠每个调用点自觉检查 —— 自觉检查一定会漏一个。
    漏掉的那一个就会变成：用户说「我这是离线环境」，
    系统背着他把代码发到了云端大模型。

    离线模式额外要求调用方自己保证端点是本机地址（见 dev.call_model）：
    有人把云端地址填进「本地模型端点」字段，名字叫本地，其实还是出网。
    """
    cfg = cfg or load_config()
    if not outbound_enabled(cfg):
        raise OutboundBlocked(
            "%s 已被全局出网开关拦下（开发设置 → 出网总开关处于关闭状态）" % what)
    if mode != MODE_ONLINE:
        raise OutboundBlocked(
            "%s 在离线模式下被禁止：离线闭环只用本机知识与本地模型，" % what +
            "请切到「在线协同」模式或打开出网开关")
