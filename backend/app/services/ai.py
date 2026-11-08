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


def scrub_reasoning_ex(text: str) -> tuple[str, dict]:
    """剥离模型泄漏的思考块，同时报告「正文是不是被思考块吃掉了」

    返回 (clean_text, info)：
    - dropped：确实剥掉了思考块；
    - unclosed：思考块没有闭合。
      这几乎总是因为 max_tokens 在思考写到一半时把输出砍断了，
      此时正文往往整段丢失 —— 调用方必须知道这件事，
      才有办法「加大 max_tokens 重试」，而不是把一个空答案返回给用户。
    """
    if not text:
        return text, {"dropped": False, "unclosed": False}
    out = _THINK_CLOSED_RE.sub("", text)
    closed_removed = out != text
    out = _THINK_OPEN_RE.sub("", out)
    unclosed = out != _THINK_CLOSED_RE.sub("", text)
    return out.strip(), {"dropped": closed_removed or unclosed, "unclosed": unclosed}


def scrub_reasoning(text: str) -> str:
    """剥离模型泄漏的思考块，保留真正的回答"""
    return scrub_reasoning_ex(text)[0]


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

# 各家厂商表示「输出被长度上限切断」的 finish_reason 写法不完全一样：
# OpenAI 用 length，MiniMax / 通义也是 length，个别推理模型用 max_output_tokens。
# 不认全的话，被截断的答案会被当成完整答案原样返回给用户 ——
# 这正是「回复到一半没了、界面还不提示」的根因。
LENGTH_FINISH_REASONS = {"length", "max_tokens", "max_output_tokens", "truncated"}

# 自动加长重试最多几次（每次把 max_tokens 翻倍）
MAX_LENGTH_RETRIES = 2


def is_length_finish(finish_reason: str | None) -> bool:
    """finish_reason 是否表示「因为长度上限被切断」"""
    if not finish_reason:
        return False
    return str(finish_reason).strip().lower() in LENGTH_FINISH_REASONS


async def chat_real_meta(
    messages: list[dict],
    *,
    stream: bool = False,
    max_tokens: int | None = None,
) -> dict:
    """调用真实 API，并返回「正文 + 结构化截断信息」

    返回 {content, finish_reason, truncated, max_tokens, retried, usage, model}
    - truncated=True：这段回答被长度上限切掉了，不是完整答案；
    - retried=True：后端已经自动加大长度重试过。

    为什么要有这一层：以前这里只回一段字符串，上游根本分不清
    「模型写完了」和「模型被拦腰砍断」，用户只能看到半截回答，
    而且没有任何提示 —— 只能自己猜是不是系统坏了。
    """
    cfg = cfg_svc.get_full_config()
    meta: dict = {
        "content": "",
        "finish_reason": None,
        "truncated": False,
        "max_tokens": 0,
        "retried": False,
        "usage": None,
        "model": cfg.get("model") or "gpt-3.5-turbo",
        "mock": False,
    }
    if not cfg.get("enabled") or not cfg.get("api_key") or not cfg.get("base_url"):
        meta["content"] = await chat_mock(messages)
        meta["finish_reason"] = "mock"
        meta["mock"] = True
        return meta

    # 清理 api_key：去除首尾空白、换行
    api_key = (cfg.get("api_key") or "").strip()

    base_tokens = int(max_tokens or cfg_svc.get_max_tokens(cfg))
    ceiling = cfg_svc.get_max_tokens_ceiling(cfg)
    retry_on = cfg_svc.auto_retry_enabled(cfg)

    payload = {
        "model": cfg.get("model") or "gpt-3.5-turbo",
        "messages": messages,
        "temperature": cfg.get("temperature", 0.7),
        "max_tokens": base_tokens,
        "stream": stream,
    }
    meta["max_tokens"] = base_tokens
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 直接使用用户配置的完整 endpoint，不追加任何路径
    url = cfg["base_url"]

    if stream:
        meta["stream"] = _stream_chat(url, payload, headers, messages, meta)
        return meta

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            attempt = 0
            while True:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                finish_reason = choice.get("finish_reason")
                raw = msg.get("content") or ""
                content, info = scrub_reasoning_ex(raw)

                meta["finish_reason"] = finish_reason
                meta["usage"] = data.get("usage")
                meta["model"] = data.get("model") or payload["model"]

                truncated = is_length_finish(finish_reason)
                empty = not content.strip()

                # 「没写完」有两种来路，都要靠加大 max_tokens 解决：
                #   1) finish_reason=length —— 正文写到一半被上限砍断；
                #   2) 正文为空 —— 模型把 max_tokens 全花在思考块上，
                #      剥掉思考块之后什么都不剩（实测问「中标供应商」时命中过）。
                # 之前只处理了第 2 种，第 1 种（更常见）被当成完整答案直接返回了。
                need_more = (truncated or empty) and retry_on
                if (need_more and attempt < MAX_LENGTH_RETRIES
                        and payload["max_tokens"] < ceiling):
                    payload["max_tokens"] = min(payload["max_tokens"] * 2, ceiling)
                    attempt += 1
                    meta["retried"] = True
                    meta["max_tokens"] = payload["max_tokens"]
                    logger.warning(
                        "AI 回答未完成（finish_reason=%s，空内容=%s），加大 max_tokens 到 %s 重试",
                        finish_reason, empty, payload["max_tokens"])
                    continue

                if empty:
                    # 加到天花板还是空 → 退回本地规则引擎，别把空答案扔给用户
                    meta["content"] = await chat_mock(messages)
                    meta["finish_reason"] = "mock_fallback"
                    meta["truncated"] = False
                    break

                meta["content"] = content
                meta["truncated"] = truncated
                break
        return meta
    except Exception as e:
        # 优雅降级：真实 API 失败（额度用尽 / 网络异常 / Key 失效）时
        # 回退到本地规则引擎，保证业务功能不中断
        detail = ""
        if isinstance(e, httpx.HTTPStatusError):
            detail = f"{e.response.status_code} {STATUS_HINT.get(e.response.status_code, '')}"
        logger.warning("AI 真实接口调用失败，降级到本地规则：%s %s", detail or type(e).__name__, e)
        meta["content"] = await chat_mock(messages)
        meta["finish_reason"] = "mock_fallback"
        meta["truncated"] = False
        return meta


async def _stream_chat(url, payload, headers, messages, meta) -> AsyncIterator[str]:
    """流式调用：边收边吐，并把 finish_reason 记进 meta

    流式正文光看长度是看不出被截断的，只能靠最后一个 chunk 的
    finish_reason 判断 —— 所以这里必须把它单独存下来。
    """
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
                            choice = (data.get("choices") or [{}])[0]
                            delta = choice.get("delta") or {}
                            # 结束原因单独记：这是「有没有被截断」的唯一依据
                            fr = choice.get("finish_reason")
                            if fr:
                                meta["finish_reason"] = fr
                                meta["truncated"] = is_length_finish(fr)
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


async def chat_real(
    messages: list[dict],
    *,
    stream: bool = False,
) -> str | AsyncIterator[str]:
    """兼容旧调用：只取正文

    需要知道「有没有被截断」的调用方请改用 chat_real_meta()。
    """
    meta = await chat_real_meta(messages, stream=stream)
    if stream:
        st = meta.get("stream")
        if st is not None:
            return st

        async def _fallback():
            yield await chat_mock(messages)
        return _fallback()
    return meta["content"]


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
    if "会议纪要" in sys or "meeting" in sys.lower():
        return _meeting_mock(last)
    if "排版" in sys or "layout" in sys.lower():
        return _layout_mock(last)
    if "问答" in sys or "qa" in sys.lower():
        return "这是一个本地 mock 回复，未配置 LLM API。要获得智能问答，请在 AI 设置页配置 API Key。"

    return f"（Mock）收到你的内容：「{last[:50]}...」"


def _meeting_mock(text: str) -> str:
    """会议纪要 mock：按行提取要点，凑出一个像样的纪要骨架"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    head = lines[:1]
    points = [l for l in lines[1:] if len(l) > 3][:8]
    out = ["## 会议纪要", ""]
    if head:
        out += [f"**议题**：{head[0]}", ""]
    out += ["### 讨论要点", ""]
    out += [f"- {p}" for p in points] if points else ["- （未识别到要点，请配置 AI 后重新生成）"]
    out += ["", "### 待办事项", "", "- （待补充）"]
    return "\n".join(out)


def _layout_mock(text: str) -> str:
    """排版建议 mock：给出几条通用建议"""
    return "\n".join([
        "## 排版建议",
        "",
        "1. **标题层级**：每节用 `##`，子条目用 `-`，别混用数字编号和符号列表",
        "2. **段落长度**：超过 4 行就拆段，重点句单独成段",
        "3. **表格**：字段多于 4 个就改用表格，两列以下就用列表",
        "4. **强调**：关键结论用 `**粗体**`，只强调一次，别整段加粗",
        "5. **代码与命令**：用代码块包起来，并标明语言",
        "",
        "> 配置 AI 后可获得针对具体内容的逐段排版建议。",
    ])


# ============ 业务功能封装 ============

async def summarize(text: str) -> str:
    """摘要笔记"""
    return await chat_real([
        {"role": "system", "content": "你是摘要助手。请把下面的笔记内容用 1-2 句话总结要点，保持简洁准确。"},
        {"role": "user", "content": text},
    ])


_STRUCT_SYSTEM = """你是笔记结构化提取器。给你一段散乱的记录（可能是终端输出、复制粘贴的碎片、没有小标题的段落），
你要提取出**结构化事实**，供排版器渲染成规范笔记。只输出 JSON，不要解释、不要 markdown 代码围栏。

输出 schema：
{
  "tldr": ["一两句结论", "关键影响", "可选第三行"],   // 2-3 条，每条 ≤ 60 字；只能说原文有的事实，不许编
  "sensitivity": "secret | confidential | public",
  "tags": ["英文域标签", "最多 6 个"],
  "risks": [                                        // 原文里明确写出的问题/发现；没有就给空数组
    {"id": "C2", "severity": "严重|高|中|低", "title": "一句话问题", "evidence": "证据/位置（≤80 字）"}
  ],
  "targets": [                                      // 原文里出现的资产
    {"name": "域名或IP", "port": "端口", "stack": "系统/框架（不知道就空串）", "result": "结果（≤30 字）"}
  ],
  "timeline": [                                     // 原文里带时间的事件；没有就给空数组
    {"time": "2026-11-08 17:17", "event": "发生了什么（≤50 字）"}
  ],
  "sections": ["原文实际包含的主题（3-8 个，每个 ≤ 12 字）"]
}

硬规则：
- 只提取原文出现过的事实；不确定的字段留空，绝不编造 IP、时间、口令、结论。
- 口令/密钥/token 这类值不要写进 JSON（排版器会自己遮盖）。
- 没有把握的数组就给 []，宁缺毋滥。
- 每字段都要短：tldr ≤ 60 字/条，risks ≤ 8 条，targets ≤ 6 条，timeline ≤ 8 条。
"""


# 结构化结果缓存：同一个内容只花一次模型调用（弹窗切开关、重复预览都不重复烧 token）
_STRUCT_CACHE: dict[str, dict] = {}
_STRUCT_TIMEOUT = 40.0


async def structure_note(text: str) -> dict:
    """把散乱正文结构化成「要素」（TL;DR / 风险 / 目标 / 时间线）

    这是规则做不了、模型才做得好的那部分：
    规则能排版、能识别命令和风险编号，但写不出一句真正的 TL;DR，
    也判断不出「哪些是目标资产、哪些是时间线事件」。

    返回的 dict 一定是**校验过的形状**：字段缺了就补空，
    类型不对就丢掉 —— 上层拿到它可以直接渲染，不用再防御。
    """
    empty = {"tldr": [], "sensitivity": "", "tags": [], "risks": [],
             "targets": [], "timeline": [], "sections": []}
    if not _ai_available() or not (text or "").strip():
        return empty

    # 输入截断：太长的抓不住重点，也费 token
    body = text if len(text) <= 6000 else text[:6000] + "\n…（后文截断）"

    import hashlib

    key = hashlib.sha1(body.encode("utf-8", "ignore")).hexdigest()
    if key in _STRUCT_CACHE:
        return dict(_STRUCT_CACHE[key])

    # 交互式预览不能等：超过 25 秒就按规则版走（聊天模型偶尔会慢到一分钟）
    import asyncio

    try:
        resp = await asyncio.wait_for(
            chat_real([
                {"role": "system", "content": _STRUCT_SYSTEM},
                {"role": "user", "content": body},
            ]),
            timeout=_STRUCT_TIMEOUT,
        )
    except Exception:
        return empty
    if not isinstance(resp, str):
        return empty

    raw = resp.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return empty
    try:
        data = json.loads(m.group(0))
    except Exception:
        return empty
    if not isinstance(data, dict):
        return empty

    def _str_list(v, limit=4, maxlen=120):
        out = []
        if isinstance(v, list):
            for x in v:
                if isinstance(x, str) and x.strip():
                    out.append(x.strip()[:maxlen])
        elif isinstance(v, str) and v.strip():
            out.append(v.strip()[:maxlen])
        return out[:limit]

    def _rows(v, keys: tuple[str, ...], limit=12):
        out = []
        if not isinstance(v, list):
            return out
        for x in v:
            if not isinstance(x, dict):
                continue
            row = {k: str(x.get(k, "") or "").strip()[:120] for k in keys}
            if any(row.values()):
                out.append(row)
        return out[:limit]

    sens = str(data.get("sensitivity") or "").strip().lower()
    if sens not in ("secret", "confidential", "public"):
        sens = ""
    tags = []
    for t in _str_list(data.get("tags"), limit=6, maxlen=24):
        t = re.sub(r"[^\w\u4e00-\u9fff-]", "", t.split("#")[-1])
        if t and t not in tags:
            tags.append(t)

    if len(_STRUCT_CACHE) > 32:
        _STRUCT_CACHE.clear()
    _STRUCT_CACHE[key] = result = {
        "tldr": _str_list(data.get("tldr"), limit=3, maxlen=90),
        "sensitivity": sens,
        "tags": tags,
        "risks": _rows(data.get("risks"), ("id", "severity", "title", "evidence")),
        "targets": _rows(data.get("targets"), ("name", "port", "stack", "result")),
        "timeline": _rows(data.get("timeline"), ("time", "event")),
        "sections": _str_list(data.get("sections"), limit=8, maxlen=24),
    }
    return dict(result)


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


async def meeting_minutes(text: str) -> str:
    """会议纪要整理

    把一段散的会议记录整理成结构化纪要：议题、讨论要点、决议、待办。

    为什么专门做这个：会议记录最大的问题是「读完了不知道谁要做什么」，
    所以固定输出「待办事项」这一节 —— 每条待办都要求带负责人和动作，
    没有负责人就写「未指定」，宁可写出来让人补，也别漏掉。
    """
    return await chat_real([
        {"role": "system", "content": (
            "你是会议纪要整理助手。请把下面的会议记录整理成结构化纪要，"
            "严格使用以下 Markdown 结构，不要增减章节：\n\n"
            "## 会议纪要\n\n"
            "**时间**：从原文里找；找不到就写「未注明」\n"
            "**参会人**：从原文里找；找不到就写「未注明」\n"
            "**议题**：一句话概括\n\n"
            "### 讨论要点\n\n"
            "- 每条一个要点，按讨论顺序\n\n"
            "### 决议\n\n"
            "- 已经拍板的事；没有就写「本次无明确决议」\n\n"
            "### 待办事项\n\n"
            "- 格式：`- [ ] 动作（负责人，期限）`；负责人/期限原文没有就写「未指定」\n\n"
            "要求：只整理原文里有的内容，不要编造；不要输出开场白或结束语。"
        )},
        {"role": "user", "content": text},
    ])


async def beautify_layout(text: str) -> str:
    """按《笔记 UI 排版规范》把正文排好 —— **直接给排版后的笔记，不是给建议**

    用户原话：「关于知识库的美化排版只给出了建议，没有进行修改」。
    之前这个接口只输出一份「建议清单」，用户还得自己照着改一遍 ——
    那等于没做。

    现在的做法：
      1. 先用**规则**把确定性的部分做掉（标题 emoji、表格表头加粗、
         代码块标语言、分割线留白、任务列表统一、引用块转 callout）
      2. 有大模型时，让模型做它比规则强的那件事：
         判断哪段是摘要、给标题配语义合适的 emoji、重排混乱的段落
      3. 无论有没有大模型，**输出的一定是排版后的正文**，
         不是建议清单 —— 能不能直接用，是这个接口的底线
    """
    from . import note_format

    # 规则打底：确定性部分先做掉
    ruled = note_format.format_note(text)

    if not _ai_available():
        return ruled

    try:
        polished = await chat_real([
            {"role": "system", "content": (
                "你是笔记排版执行器。给你一段笔记正文，**直接输出排版后的完整正文**。\n\n"
                "必须遵守《笔记 UI 排版规范》：\n"
                "1. 标题层级：H1 只一个（= 笔记名）；H2 = 主要分节；H3 = 子节\n"
                "2. 每个 H2 标题前加一个语义相关的 emoji（背景🎯 步骤🔧 配置⚙️ 数据📊 "
                "警告⚠️ 成功✅ 失败❌ 待办📋 总结📌 链接🔗 时间⏱️）\n"
                "3. 用 Obsidian callout 表达强调：> [!info] > [!tip] > [!warning] > [!danger] "
                "> [!example] > [!success] > [!failure] > [!note] > [!abstract] > [!todo]\n"
                "4. 笔记开头（第一个 H2 之前）放一个 > [!abstract] 摘要块，1-3 行 TL;DR\n"
                "5. 每个 H2 章节第一段用 > [!note] 或 > [!tip] 一句话点出本章核心\n"
                "6. 表格：表头用 **粗体**；单元格里的状态词加 emoji（已完成✅ 进行中🚧 "
                "待开始⏳ 失败❌ 慎用⚠️）\n"
                "7. 代码块必须标语言（```bash / ```python / ```json …）\n"
                "8. 分割线统一用 ---，前后各空一行\n"
                "9. 任务列表用 GitHub 风格：- [x] / - [ ] / - [-] / - [?]\n"
                "10. 不要输出解释、不要输出「以下是排版后的内容」这类前言\n\n"
                "**只输出排版后的正文本身。**"
            )},
            {"role": "user", "content": ruled},
        ])
    except Exception:
        return ruled

    # 模型输出可能不完整（比如它只回了一段）—— 拿规则版兜底
    if not polished or len(polished.strip()) < max(20, len(ruled.strip()) * 0.4):
        return ruled
    return polished.strip() + "\n"


def _ai_available() -> bool:
    """有没有配好大模型（没配就走纯规则）"""
    cfg = cfg_svc.get_full_config()
    return bool(cfg.get("enabled") and cfg.get("api_key") and cfg.get("base_url"))


async def suggest_title(content: str) -> str:
    """基于内容生成标题"""
    return await chat_real([
        {"role": "system", "content": "你是标题助手。基于内容生成一个简洁的标题（10 字以内）。直接返回标题，不要其他文字。"},
        {"role": "user", "content": content},
    ])


async def ask(question: str, context: list[str] | None = None,
              genes: list[dict] | None = None) -> str:
    """AI 问答（只取正文）

    需要知道「有没有被截断」请用 ask_meta()。
    """
    meta = await ask_meta(question, context, genes)
    return meta["content"]


def continuation_tail(text: str, limit: int = 2000) -> str:
    """截取已有回答的尾巴，供「续写」时回灌给模型

    为什么留尾巴而不是全文：
    全文可能好几千 token，回灌一遍就把预算吃光了；
    但续写必须接在最后一句的断点上，所以尾巴不能丢。
    """
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= limit:
        return t
    return "…（前文已省略）\n" + t[-limit:]


async def ask_meta(question: str, context: list[str] | None = None,
                    genes: list[dict] | None = None,
                    continuation: str = "") -> dict:
    """AI 问答（带上下文 + 养料库基因）

    四条提示词规矩，每条都对应一个真实踩过的坑：

    1. **要标出处**：上下文块带【n】编号，答案里对应的句子后面写【n】。
       以前出处只在响应体的 sources[] 里，答案正文一个标记都没有 ——
       用户没法判断哪句话是从哪条资料来的。
    2. **资料里没有就说没有**：明确禁止用常识补齐。
       不写这条的时候，问「中标供应商是谁」这种语料外的问题，
       模型会顺口编一个 —— 检索没命中不等于事实不存在，答案必须说清。
    3. **上下文不能截断到只剩前 5 条**：以前是 context[:5]，
       检索准备了十几块证据，最后只喂了 5 块就扔了剩下的。
       现在按字符预算截，块数不再硬砍。
    4. **基因可以引用**：养料库里的基因是已经提炼过的结论，
       用它回答时标【基因#编号】，让人能点回去看原文。
    """
    sys_msg = (
        "你是知识工作台 AI 助手。基于上下文回答用户问题，简洁准确。\n"
        "规矩：\n"
        "1. 每条结论后面用【n】标明它来自第 n 条上下文（上下文块以【n】开头）。\n"
        "2. 上下文里没有的信息，直接说「资料里没有」，不要用常识或推测补齐。\n"
        "3. 不确定的地方明确说不确定，不要含糊带过。"
    )
    if genes:
        sys_msg += ("\n4. 用了养料库基因作答时，在对应句子后面标【基因#编号】"
                    "（基因块以【基因#编号】开头）。")
    if context:
        # 按字符预算截，而不是按块数硬砍 —— 块数砍掉的是「排在后面的证据」，
        # 而排在后面不等于不重要（跨文档问题的第二份材料常在后面）。
        budget = 12000
        kept: list[str] = []
        used = 0
        for c in context:
            c = c or ""
            if used + len(c) > budget and kept:
                break
            kept.append(c)
            used += len(c)
        sys_msg += "\n\n参考上下文：\n" + "\n---\n".join(kept)

    msgs = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": question},
    ]
    if continuation:
        # 续写：把已写出的内容当成模型自己刚说过的话回灌，
        # 再明确要求「从断点接着写、不要重复」——
        # 不带上下文续写，模型会从头再答一遍，用户看到的就是重复内容。
        msgs.append({"role": "assistant",
                     "content": continuation_tail(continuation)})
        msgs.append({"role": "user", "content": (
            "【继续写作】上面那段回答因为长度上限被截断了。"
            "请从它最后一句被切断的地方接着往下写，"
            "不要重复已经写过的内容，也不要重新开头。"
        )})
    return await chat_real_meta(msgs)


def normalize_gene_citations(text: str, aliases: dict[int, int] | None = None) -> str:
    """把模型写出来的各种基因引用写法归一成【基因#基因编号】

    模型可能写【基因12】【基因 #12】[基因12]【G12】——
    归一之后前端只需要认一种写法。

    aliases 把「上下文块号」映射回「基因编号」：
    模型看到的是上下文里的第 5 块，但它不知道那块的基因编号是 25。
    答案里写【基因#5】时，要还原成【基因#25】，
    否则前端拿着 5 去查基因库，查出来的是另一条。
    """
    t = (text or "")
    t = re.sub(r"[【\[]\s*基因\s*#?\s*(\d+)\s*[】\]]", r"【基因#\1】", t)
    t = re.sub(r"[【\[]\s*G\s*(\d+)\s*[】\]]", r"【基因#\1】", t)
    if aliases:
        def _fix(m):
            n = int(m.group(1))
            return f"【基因#{aliases.get(n, n)}】"
        t = re.sub(r"【基因#(\d+)】", _fix, t)
    return t


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