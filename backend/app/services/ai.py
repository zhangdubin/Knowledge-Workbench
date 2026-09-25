"""AI 服务：OpenAI 兼容调用 + Mock 规则引擎

未配置真实 API 时使用本地规则（关键词提取、模板摘要等），
保证系统无 LLM 时也能用基础 AI 能力。
"""
import re
import json
import logging
import httpx
from typing import AsyncIterator

from . import ai_config as cfg_svc

logger = logging.getLogger("kb.ai")

# HTTP 状态码 → 人话（中文）
STATUS_HINT = {
    400: "请求格式错误（可能是模型名不支持或参数非法）",
    401: "API Key 无效或未携带",
    402: "账户额度不足 / 已达用量上限",
    403: "权限不足（Key 无该模型访问权限）",
    404: "接口地址不存在（endpoint 路径不对）",
    429: "请求过于频繁（触发限流）",
    500: "服务端内部错误",
    502: "网关错误",
    503: "服务暂时不可用",
}


# 推理模型（DeepSeek-R1 / 带思考链的模型）会把思考过程混在 content 里，
# 例如「<think>…</think>正文」。这些内容不该进入摘要、标题等面向用户的字段。
_THINK_CLOSED_RE = re.compile(
    r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE
)
_THINK_OPEN_RE = re.compile(
    r"<(think|thinking|reasoning)>.*$", re.DOTALL | re.IGNORECASE
)
# 流式解析用：只判断「本段是否含开/闭标签」，不贪婪吞到结尾
_THINK_OPEN_RE_STRICT = re.compile(r"<(think|thinking|reasoning)>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</(think|thinking|reasoning)>", re.IGNORECASE)


def scrub_reasoning(text: str) -> str:
    """剥离模型泄漏的思考块，保留真正的回答"""
    if not text:
        return text
    out = _THINK_CLOSED_RE.sub("", text)
    # 未闭合（被 max_tokens 截断）的情况：从起始标签起全部丢弃
    out = _THINK_OPEN_RE.sub("", out)
    return out.strip()


def _extract_error(r: "httpx.Response") -> str:
    """从响应中提取可读的错误信息"""
    try:
        body = r.json()
    except Exception:
        return (r.text or "").strip()[:300] or "（无响应内容）"
    err = body.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("type") or json.dumps(err, ensure_ascii=False)
    elif isinstance(err, str):
        msg = err
    else:
        msg = body.get("message") or body.get("msg")
    # MiniMax 风格：{"base_resp": {"status_code": 2067, "status_msg": "..."}}
    base = body.get("base_resp") or {}
    if not msg and base:
        msg = f"[{base.get('status_code', '')}] {base.get('status_msg', '')}"
    if not msg:
        msg = json.dumps(body, ensure_ascii=False)[:300]
    return str(msg)[:300]


# ============ 真实 API 调用（OpenAI 兼容）============

async def chat_real(
    messages: list[dict],
    *,
    stream: bool = False,
) -> str | AsyncIterator[str]:
    cfg = cfg_svc.get_full_config()
    if not cfg.get("enabled") or not cfg.get("api_key") or not cfg.get("base_url"):
        # 降级到 mock
        return await chat_mock(messages)

    # 清理 api_key：去除首尾空白、换行
    api_key = (cfg.get("api_key") or "").strip()

    payload = {
        "model": cfg.get("model") or "gpt-3.5-turbo",
        "messages": messages,
        "temperature": cfg.get("temperature", 0.7),
        "max_tokens": cfg.get("max_tokens", 1024),
        "stream": stream,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 直接使用用户配置的完整 endpoint，不追加任何路径
    url = cfg["base_url"]

    if stream:
        async def gen():
            in_think = False
            buf = ""
            try:
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    async with client.stream(
                        "POST", url,
                        json=payload, headers=headers,
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line or line.startswith(":"):
                                continue
                            if line.startswith("data: "):
                                chunk = line[6:]
                                if chunk.strip() == "[DONE]":
                                    break
                                try:
                                    data = json.loads(chunk)
                                    delta = data.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if not content:
                                        continue
                                    # 跨 chunk 的 <think>…</think> 需要状态机处理，
                                    # 否则思考链会一段段漏到前端
                                    if in_think:
                                        buf += content
                                        if _THINK_CLOSE_RE.search(buf):
                                            rest = _THINK_CLOSE_RE.split(buf, 1)[-1]
                                            in_think, buf = False, ""
                                            if rest:
                                                yield rest
                                    elif _THINK_OPEN_RE_STRICT.search(content):
                                        if _THINK_CLOSE_RE.search(content):
                                            yield scrub_reasoning(content)
                                        else:
                                            in_think, buf = True, content
                                    else:
                                        yield content
                                except Exception:
                                    pass
            except Exception as e:
                logger.warning("AI 流式接口失败，降级到本地规则：%s", e)
                yield await chat_mock(messages)
        return gen()
    else:
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                return scrub_reasoning(data["choices"][0]["message"]["content"])
        except Exception as e:
            # 优雅降级：真实 API 失败（额度用尽 / 网络异常 / Key 失效）时
            # 回退到本地规则引擎，保证业务功能不中断
            detail = ""
            if isinstance(e, httpx.HTTPStatusError):
                detail = f"{e.response.status_code} {STATUS_HINT.get(e.response.status_code, '')}"
            logger.warning("AI 真实接口调用失败，降级到本地规则：%s %s", detail or type(e).__name__, e)
            return await chat_mock(messages)


# ============ Mock 规则引擎 ============

def _extract_keywords(text: str, top: int = 8) -> list[str]:
    """简单关键词提取：去停用词、取最长 2-gram"""
    # 中文 + 英文混合
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    words = [w for w in text.split() if len(w) >= 2]
    # 统计频次
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq, key=lambda x: (-freq[x], -len(x)))[:top]


def _summary_mock(text: str, max_chars: int = 200) -> str:
    sentences = re.split(r"[。！？\n]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) >= 8]
    if not sentences:
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    summary = sentences[0]
    for s in sentences[1:]:
        if len(summary) + len(s) + 1 > max_chars:
            break
        summary += "。" + s
    return summary + "。" if not summary.endswith("。") else summary


def _tags_mock(text: str) -> list[str]:
    return _extract_keywords(text, 5)


async def chat_mock(messages: list[dict]) -> str:
    """基于规则的 mock 回复"""
    last = messages[-1]["content"] if messages else ""
    sys = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""

    # 根据系统提示判断任务类型
    if "摘要" in sys or "summarize" in sys.lower():
        return _summary_mock(last)
    if "标签" in sys or "tag" in sys.lower():
        return json.dumps(_tags_mock(last), ensure_ascii=False)
    if "改写" in sys or "rewrite" in sys.lower():
        return last + "\n\n（已润色）"
    if "扩写" in sys or "expand" in sys.lower():
        return last + "\n\n进一步说明：此内容涉及关键业务逻辑，建议关注相关上下游关联。"
    if "问答" in sys or "qa" in sys.lower():
        return "这是一个本地 mock 回复，未配置 LLM API。要获得智能问答，请在 AI 设置页配置 API Key。"

    return f"（Mock）收到你的内容：「{last[:50]}...」"


# ============ 业务功能封装 ============

async def summarize(text: str) -> str:
    """摘要笔记"""
    return await chat_real([
        {"role": "system", "content": "你是摘要助手。请把下面的笔记内容用 1-2 句话总结要点，保持简洁准确。"},
        {"role": "user", "content": text},
    ])


async def extract_tags(text: str, max_tags: int = 5) -> list[str]:
    """提取标签"""
    resp = await chat_real([
        {"role": "system", "content": f"你是标签提取助手。请从下面内容中提取 {max_tags} 个关键标签（JSON 数组）。只返回 JSON，不要其他文字。"},
        {"role": "user", "content": text},
    ])
    try:
        # 尝试提取 JSON
        m = re.search(r"\[.*?\]", resp, re.DOTALL)
        if m:
            tags = json.loads(m.group(0))
            return [str(t) for t in tags][:max_tags]
    except Exception:
        pass
    # fallback：逗号分隔
    return [t.strip() for t in resp.split(",") if t.strip()][:max_tags]


async def rewrite(text: str, style: str = "polish") -> str:
    """改写/润色"""
    style_map = {
        "polish": "你是文字润色助手。保持原意，让表达更清晰流畅。",
        "formal": "你是文本风格化助手。把内容改写得更正式专业。",
        "casual": "你是文本风格化助手。把内容改写得更轻松口语化。",
        "expand": "你是内容扩写助手。在保持原意基础上补充细节和例子。",
        "shorten": "你是文本精简助手。删除冗余字。",
    }
    sys_prompt = style_map.get(style, style_map["polish"])
    return await chat_real([
        {"role": "system", "content": sys_prompt + " 直接返回改写后的内容。"},
        {"role": "user", "content": text},
    ])


async def suggest_title(content: str) -> str:
    """基于内容生成标题"""
    return await chat_real([
        {"role": "system", "content": "你是标题助手。基于内容生成一个简洁的标题（10 字以内）。直接返回标题，不要其他文字。"},
        {"role": "user", "content": content},
    ])


async def ask(question: str, context: list[str] | None = None) -> str:
    """AI 问答（带上下文）"""
    sys_msg = "你是知识工作台 AI 助手。基于上下文回答用户问题，简洁准确。"
    if context:
        sys_msg += "\n\n参考上下文：\n" + "\n---\n".join(context[:5])

    return await chat_real([
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": question},
    ])


async def test_connection() -> dict:
    """测试 AI 连接"""
    cfg = cfg_svc.get_full_config()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return {"ok": False, "error": "AI 未启用或未配置 API Key"}

    if not cfg.get("base_url"):
        return {"ok": False, "error": "未配置 API Base URL"}

    # 清理 api_key：去除首尾空白、换行
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        return {"ok": False, "error": "API Key 为空"}

    # 直接使用用户配置的完整 endpoint URL
    url = cfg["base_url"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg.get("model") or "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 8,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                body = {}
                try:
                    body = r.json()
                except Exception:
                    pass
                model_echo = (body.get("model") if isinstance(body, dict) else None) or payload["model"]
                return {
                    "ok": True,
                    "status": 200,
                    "url": url,
                    "model": model_echo,
                    "response": f"HTTP 200 OK · 模型 {model_echo} 响应正常",
                }
            # 非 200：返回完整诊断
            msg = _extract_error(r)
            return {
                "ok": False,
                "status": r.status_code,
                "url": url,
                "model": payload["model"],
                "error": msg,
                "hint": STATUS_HINT.get(r.status_code, ""),
            }
    except Exception as e:
        return {
            "ok": False,
            "url": url,
            "model": payload["model"],
            "error": f"{type(e).__name__}: {e}",
            "hint": "网络异常，请检查 endpoint 可达性 / 代理设置",
        }