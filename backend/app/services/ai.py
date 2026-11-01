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
                for attempt in range(2):
                    r = await client.post(url, json=payload, headers=headers)
                    r.raise_for_status()
                    data = r.json()
                    raw = (data["choices"][0]["message"].get("content") or "")
                    out = scrub_reasoning(raw)
                    if out.strip():
                        return out
                    # 空回答有两种来路：模型把 max_tokens 全花在思考块上，
                    # 或者正文本身被 max_tokens 截断在思考块里。
                    # 两种都表现为「剥掉思考块之后什么都不剩」——
                    # 实测问「中标供应商」时命中过，接口 200，答案却是空的。
                    # 这时候加 token 再问一次，比把空答案扔给用户强。
                    logger.warning("AI 返回空内容（第 %s 次），加大 max_tokens 重试", attempt + 1)
                    try:
                        payload["max_tokens"] = int(payload.get("max_tokens") or 1024) * 2
                    except (TypeError, ValueError):
                        payload["max_tokens"] = 2048
                return await chat_mock(messages)
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

    return await chat_real([
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": question},
    ])


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