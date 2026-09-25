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
    "max_tokens": 1024,
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


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            # 合并默认值（防止字段缺失）
            merged = {**DEFAULT_CONFIG, **cfg}
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