"""向量化服务：MiniMax embo-01（并兼容 OpenAI 风格接口）

为什么要单独写一层适配，而不是复用 ai.py 的 chat_real：
  1. MiniMax 的 embedding 接口**不是** OpenAI 格式 ——
     请求用 `texts` 而非 `input`，多一个 `type` 参数（query / db），
     返回是 `{"vectors": [[...]]}` 而非 `data[].embedding`。
     直接套 chat_real 那套 payload 必然 400。
  2. 接口地址也不同：chat 走 /v1/chat/completions，embedding 走
     /v1/embeddings。这里从用户已配置的 chat 地址自动推导，避免
     再让人手填一遍。

维度不写死：emo-01 在各处资料里有 1024 / 1536 两种说法，所以首次调用
成功后按实际返回长度确定维度，交给 docindex 建表。
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from ..config import settings
from . import ai_config as cfg_svc

log = logging.getLogger("kb.embed")

# 熔断：embedding 失败后短期内不再重试
#
# 为什么需要：额度不足 / 网络不通时，每次检索都会先等一次 HTTP 超时
# 才降级到关键词检索，用户会感觉「搜索很卡」。
# 记下失败时间，冷却期内直接返回 None（调用方立即降级），
# 冷却结束再试一次 —— 用户充值后无需重启即可自动恢复。
_FAIL_COOLDOWN = 90.0
_last_failure = 0.0
_last_error = ""


def _cooling_down() -> bool:
    return (time.time() - _last_failure) < _FAIL_COOLDOWN


def _mark_failure(reason: str) -> None:
    global _last_failure, _last_error
    _last_failure = time.time()
    _last_error = reason


def _mark_success() -> None:
    global _last_failure, _last_error
    _last_failure = 0.0
    _last_error = ""


def breaker_state() -> dict:
    return {
        "cooling_down": _cooling_down(),
        "last_error": _last_error,
        "retry_in": max(0, round(_FAIL_COOLDOWN - (time.time() - _last_failure), 1))
        if _last_failure else 0,
    }


STATUS_HINT = {
    400: "请求格式错误（可能是模型名不支持或该模型未开通 embedding 权限）",
    401: "API Key 无效",
    402: "账户额度不足",
    403: "无该模型访问权限",
    404: "接口地址不存在",
    429: "请求过于频繁",
}


def derive_embed_url(cfg: dict) -> str:
    """推导 embedding 接口地址

    优先用用户显式配置的 embed_base_url；否则从 chat 地址改写：
      https://api.minimax.cn/v1/chat/completions  →  .../v1/embeddings
      https://api.openai.com/v1/chat/completions  →  .../v1/embeddings
    """
    explicit = (cfg.get("embed_base_url") or "").strip()
    if explicit:
        return explicit

    chat = (cfg.get("base_url") or "").strip()
    if not chat:
        return ""

    base = chat.rstrip("/")
    # 去掉已知的 chat 路径后缀
    base = re.sub(
        r"/(chat/completions|text/chatcompletion_v2|text/chatcompletion|"
        r"chatcompletion_v2|chatcompletion|completions|chat)$",
        "", base,
    )
    if base.endswith("/v1") or base.endswith("/v2"):
        return base + "/embeddings"
    return base + "/embeddings"


def _is_minimax(cfg: dict, url: str) -> bool:
    style = (cfg.get("embed_style") or "auto").lower()
    if style in ("minimax", "openai"):
        return style == "minimax"
    provider = (cfg.get("provider") or "").lower()
    return "minimax" in provider or "minimax" in url.lower()


def get_embed_config() -> dict[str, Any]:
    """汇总 embedding 所需配置（Key 缺省时回落到 chat 的 Key）"""
    cfg = cfg_svc.get_full_config()
    url = derive_embed_url(cfg)
    api_key = (cfg.get("embed_api_key") or "").strip() or (cfg.get("api_key") or "").strip()
    return {
        "enabled": bool(cfg.get("enabled")) and bool(url) and bool(api_key),
        "url": url,
        "api_key": api_key,
        "model": (cfg.get("embed_model") or "").strip() or "embo-01",
        "style": "minimax" if _is_minimax(cfg, url) else "openai",
        "group_id": (cfg.get("embed_group_id") or "").strip(),
        "timeout": float(cfg.get("embed_timeout") or 30),
    }


def config_summary() -> dict:
    """给设置页看的脱敏状态"""
    c = get_embed_config()
    cfg = cfg_svc.load_config()
    return {
        "enabled": c["enabled"],
        "url": c["url"],
        "model": c["model"],
        "style": c["style"],
        "has_key": bool(c["api_key"]),
        "key_from_chat": not bool((cfg.get("embed_api_key") or "").strip()),
        "dim": int(cfg.get("embed_dim") or 0),
        **breaker_state(),
    }


async def embed_texts(texts: list[str], *, kind: str = "db") -> list[list[float]] | None:
    """批量向量化。kind: db（入库正文） / query（检索词）

    失败返回 None —— 调用方据此降级到纯关键词检索，业务不中断。
    """
    texts = [t for t in texts if (t or "").strip()]
    if not texts:
        return []

    c = get_embed_config()
    if not c["enabled"]:
        return None

    if _cooling_down():
        return None

    out: list[list[float]] = []
    batch = max(1, settings.embed_batch_size)
    for i in range(0, len(texts), batch):
        part = texts[i:i + batch]
        vecs = await _call(part, c, kind)
        if vecs is None:
            return None
        out.extend(vecs)
    return out



async def embed_query(text: str) -> list[float] | None:
    vecs = await embed_texts([text], kind="query")
    if not vecs:
        return None
    return vecs[0]


async def _call(batch: list[str], c: dict, kind: str) -> list[list[float]] | None:
    url = c["url"]
    headers = {
        "Authorization": f"Bearer {c['api_key']}",
        "Content-Type": "application/json",
    }
    params = {}
    if c.get("group_id"):
        params["GroupId"] = c["group_id"]

    trimmed = [(t or "")[: settings.embed_max_chars] for t in batch]

    if c["style"] == "minimax":
        payload = {"model": c["model"], "texts": trimmed, "type": kind}
    else:
        payload = {"model": c["model"], "input": trimmed}

    try:
        async with httpx.AsyncClient(timeout=c["timeout"], follow_redirects=True) as client:
            r = await client.post(url, json=payload, headers=headers, params=params or None)
            if r.status_code != 200:
                reason = f"{r.status_code} {STATUS_HINT.get(r.status_code, r.text[:120])}"
                log.warning("embedding 接口 %s", reason)
                _mark_failure(reason)
                return None
            body = r.json()
    except Exception as e:
        _mark_failure(f"{type(e).__name__}: {e}")
        log.warning("embedding 调用异常：%s: %s", type(e).__name__, e)
        return None

    # MiniMax 风格的业务错误码
    base_resp = body.get("base_resp") if isinstance(body, dict) else None
    if isinstance(base_resp, dict) and base_resp.get("status_code", 0) != 0:
        code = base_resp.get("status_code")
        msg = base_resp.get("status_msg") or ""
        log.warning("embedding 业务错误：%s", base_resp)
        _mark_failure(f"[{code}] {msg}")
        return None


    vecs = _parse_vectors(body)
    if vecs is None:
        # 风格判断错了就换另一种再试一次
        alt = "openai" if c["style"] == "minimax" else "minimax"
        if alt == "minimax":
            payload = {"model": c["model"], "texts": trimmed, "type": kind}
        else:
            payload = {"model": c["model"], "input": trimmed}
        try:
            async with httpx.AsyncClient(timeout=c["timeout"], follow_redirects=True) as client:
                r = await client.post(url, json=payload, headers=headers, params=params or None)
                if r.status_code == 200:
                    vecs = _parse_vectors(r.json())
        except Exception:
            pass

    if vecs is None:
        log.warning("embedding 响应无法解析：%s", str(body)[:300])
        _mark_failure("响应无法解析")
        return None
    _mark_success()
    return vecs


def _parse_vectors(body: Any) -> list[list[float]] | None:
    """兼容两种返回结构"""
    if not isinstance(body, dict):
        return None
    # MiniMax: {"vectors": [[...], ...]}
    v = body.get("vectors")
    if isinstance(v, list) and v and isinstance(v[0], list):
        return [[float(x) for x in row] for row in v]
    # OpenAI: {"data": [{"embedding": [...]}]}
    d = body.get("data")
    if isinstance(d, list) and d:
        try:
            rows = [item["embedding"] for item in d]
            if rows and isinstance(rows[0], list):
                return [[float(x) for x in row] for row in rows]
        except Exception:
            return None
    return None


async def test_embedding() -> dict:
    """测试向量化连通性，并报告实际维度"""
    c = get_embed_config()
    if not (c["url"] and c["api_key"]):
        return {"ok": False, "error": "未配置 embedding 地址或 API Key"}
    if not c["enabled"]:
        return {"ok": False, "error": "AI 未启用（请先在设置中启用并保存）"}

    vecs = await embed_texts(["连通性测试"], kind="db")
    if not vecs or not vecs[0]:
        return {"ok": False, "url": c["url"], "model": c["model"],
                "error": "调用失败，请检查模型名 / 额度 / 该模型是否支持 embedding"}
    return {
        "ok": True,
        "url": c["url"],
        "model": c["model"],
        "style": c["style"],
        "dim": len(vecs[0]),
        "response": f"成功，维度 {len(vecs[0])}",
    }
