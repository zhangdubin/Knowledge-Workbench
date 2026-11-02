"""AI 配置管理

用户可在系统设置页配置 LLM API key、base_url、模型名等。
支持 OpenAI 兼容协议（OpenAI / DeepSeek / OpenRouter / 通义千问 / Ollama 等）。
"""
import json
import os
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ai_config.json"
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "mock",         # mock / openai / openrouter / custom
    "base_url": "",             # 自定义 endpoint（OpenAI 兼容）
    "api_key": "",
    "model": "",                # 默认模型
    "temperature": 0.7,
    # 回答长度上限（单位：token）。
    # 为什么从 1024 提到 4096：1024 token 大约只有 700~800 个汉字，
    # 写两句就到底了 —— 模型还没把话说完就被切断，
    # 用户看到的就是「回复到一半没了」。4096 大约能写 3000 字，
    # 足够覆盖一次正常的表格化回答。
    "max_tokens": 4096,
    # 被截断时是否自动加大长度重试（通用机制，不只是「空回答」才重试）。
    # 关掉的话回答会被原样截断，用户只能自己改设置再问一遍。
    "auto_retry_on_truncation": True,
    # 自动重试时 max_tokens 能涨到的天花板，防止无限加大把费用打爆。
    "max_tokens_ceiling": 32768,
    "enabled": False,           # 是否启用真实 API（False 时用 mock 规则引擎）
    "system_prompt": "你是一个知识工作台 AI 助手，简洁准确。",
    # 允许 AI 助理执行写操作（新建/修改/删除记录）。
    # 开启后每一次写操作仍会在对话里列明字段、由用户点确认才落库。
    "agent_write": True,

    # ---- 向量化（embedding）配置 ----
    # 留空时自动从 base_url 推导为 .../v1/embeddings
    "embed_base_url": "",
    # 留空时复用上面的 api_key
    "embed_api_key": "",
    "embed_model": "embo-01",
    # auto / minimax / openai —— 决定请求体用 texts+type 还是 input
    "embed_style": "auto",
    "embed_group_id": "",
    "embed_timeout": 30,
    # 首次向量化成功后写入的实际维度
    "embed_dim": 0,
}


# 老版本的默认 max_tokens。1024 太小 —— 约 700 个汉字，
# 模型写两句就到底了，「回复到一半没了」的根因就是它。
LEGACY_MAX_TOKENS = 1024


def effective_max_tokens(raw: dict) -> int | None:
    """磁盘配置里的 max_tokens 该怎么解释

    为什么要做这次迁移：
    只改默认值对老用户是没用的 —— 他们的配置文件里还躺着 1024
    （大多数人根本没碰过这个设置）。所以把「没标记过的 1024」
    当成老默认值，抬到新的 4096；抬过一次之后打上标记，
    之后用户再显式设回 1024 就不再动它。
    """
    raw = raw or {}
    v = raw.get("max_tokens")
    if v == LEGACY_MAX_TOKENS and not raw.get("max_tokens_migrated"):
        return DEFAULT_CONFIG["max_tokens"]
    return v


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            # 合并默认值（防止字段缺失）
            merged = {**DEFAULT_CONFIG, **cfg}
            # 老配置里留着 1024 的，抬到新默认（见 effective_max_tokens 的说明）
            eff = effective_max_tokens(cfg)
            if eff is not None and eff != cfg.get("max_tokens"):
                merged["max_tokens"] = eff
                merged["max_tokens_migrated"] = True
            return merged
        except Exception:
            pass
    return {**DEFAULT_CONFIG}


SECRET_FIELDS = ("api_key", "embed_api_key")


def _looks_masked(value: str) -> bool:
    v = (value or "").strip()
    return (not v) or v.startswith("***") or "•" in v


def save_config(cfg: dict) -> dict:
    """保存配置。

    关键保护：前端拿到的 api_key / embed_api_key 是掩码（***abcd）。
    如果表单未修改就回传掩码、或回传空串，都视为「不修改」，
    保留磁盘上原有的真实 Key，避免把掩码写成真 Key。
    两个 Key 各自独立判断 —— 只改 embedding 的 Key 不应影响 chat 的 Key。
    """
    current = load_config()

    payload = {k: v for k, v in cfg.items() if k != "clear_api_key"}
    merged = {**DEFAULT_CONFIG, **payload}
    # 保留迁移标记：用户显式把上限设回 1024 时，别又被自动抬上去
    if "max_tokens_migrated" not in payload:
        merged["max_tokens_migrated"] = bool(current.get("max_tokens_migrated", False))

    for field in SECRET_FIELDS:
        incoming = (merged.get(field) or "").strip()
        # 单独清空某个 Key：clear_api_key 支持字符串字段名或 True（清 api_key）
        clear = cfg.get("clear_api_key")
        if clear is True and field == "api_key":
            merged[field] = ""
        elif clear == field:
            merged[field] = ""
        elif _looks_masked(incoming):
            merged[field] = current.get(field, "")
        else:
            merged[field] = incoming

    CONFIG_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged


def _mask(value: str) -> str:
    if not value:
        return ""
    return "***" + value[-4:] if len(value) > 4 else "***"


def get_public_config() -> dict:
    """返回配置（隐藏所有 Key）"""
    cfg = load_config()
    for field in SECRET_FIELDS:
        if cfg.get(field):
            cfg[field] = _mask(cfg[field])
    return cfg



def get_full_config() -> dict:
    """返回完整配置（用于调用）"""
    return load_config()


# ============ 回答长度上限相关 ============

# 下限：太小的上限没有任何意义，模型连一句话都写不完
MIN_MAX_TOKENS = 256
# 上限（配置里可调的天花板本身也有上限，防止有人填 10^9）
HARD_MAX_TOKENS = 131072


def get_max_tokens(cfg: dict | None = None) -> int:
    """本次回答的长度上限（token）

    为什么要有这层归一化：
    配置是用户手填的，可能填 0、负数、超大值。直接发给模型会 400，
    或者一次请求烧掉不必要的 token。这里把越界值夹回合法区间。
    """
    cfg = cfg if cfg is not None else get_full_config()
    raw = cfg.get("max_tokens")
    if raw is None or raw == "":
        v = DEFAULT_CONFIG["max_tokens"]
    else:
        try:
            v = int(raw)
        except (TypeError, ValueError):
            v = DEFAULT_CONFIG["max_tokens"]
    return max(MIN_MAX_TOKENS, min(v, HARD_MAX_TOKENS))


def get_max_tokens_ceiling(cfg: dict | None = None) -> int:
    """自动重试时长度上限能涨到哪

    天花板只比当前上限大 —— 用户把上限调小了，就是不想让回答太长，
    这时不该偷偷涨上去。
    """
    cfg = cfg if cfg is not None else get_full_config()
    cur = get_max_tokens(cfg)
    try:
        c = int(cfg.get("max_tokens_ceiling") or DEFAULT_CONFIG["max_tokens_ceiling"])
    except (TypeError, ValueError):
        c = DEFAULT_CONFIG["max_tokens_ceiling"]
    c = max(MIN_MAX_TOKENS, min(c, HARD_MAX_TOKENS))
    return max(cur, c)


def auto_retry_enabled(cfg: dict | None = None) -> bool:
    """回答被截断时要不要自动加大长度重试"""
    cfg = cfg if cfg is not None else get_full_config()
    return bool(cfg.get("auto_retry_on_truncation", True))