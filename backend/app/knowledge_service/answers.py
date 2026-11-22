"""Optional generation is restricted to this execution's verified citations."""

import json
from ..services import ai, ai_config

PROMPT_VERSION = "knowledge-evidence/1"


def model_config():
    return ai_config.get_full_config()


async def generate(p, request, result):
    if not request.get("generate"):
        return
    cfg = model_config()
    if not cfg.get("enabled") or not cfg.get("api_key") or not cfg.get("base_url"):
        result["generation"] = "disabled"
        result["reasons"].append("生成式答复未启用，可继续查阅结构化知识和原文。")
        return
    if not p.has_feature("ai"):
        result["generation"] = "disabled"
        result["reasons"].append("当前用户未获准使用生成式答复。")
        return
    if result["status"] != "supported" or not result["citations"]:
        result["generation"] = "not_requested"
        return
    result["model_version"] = cfg.get("model")
    budget = dict(
        max_tokens_ceiling=1200,
        input_char_limit=32000,
        max_retries=0,
        max_tokens=None,
        retry_count=0,
        retried=False,
        usage=None,
        finish_reason=None,
    )
    result["budget"]["generation"] = budget
    allowed = {c["id"]: c for c in result["citations"]}
    context = [
        dict(evidence_id=c["id"], quote=c["quote"], start=c["start"], end=c["end"])
        for c in allowed.values()
    ]
    messages = [
        dict(
            role="system",
            content='仅依据给定证据作答。输出 JSON：{"answer":"中文答复","citations":[{"evidence_id":"...","quote":"逐字引文","start":0,"end":1}]}。每条答复必须有证据，禁止引入集合外信息。',
        ),
        dict(
            role="user",
            content=json.dumps(
                dict(question=request["question"], evidence=context), ensure_ascii=False
            ),
        ),
    ]
    budget["input_characters"] = sum(len(m["content"]) for m in messages)
    if budget["input_characters"] > budget["input_char_limit"]:
        result.update(answer=None, generation="error")
        result["reasons"].append("本次证据超过生成输入预算，请缩小筛选范围。")
        return
    try:
        meta = await ai.chat_real_meta(
            messages, max_tokens=1200, max_tokens_ceiling=1200, max_retries=0
        )
        budget.update(
            {
                k: meta.get(k)
                for k in (
                    "max_tokens",
                    "retry_count",
                    "retried",
                    "usage",
                    "finish_reason",
                )
            }
        )
        if (
            meta.get("mock")
            or meta.get("truncated")
            or meta.get("finish_reason") in ("mock", "mock_fallback")
        ):
            raise ValueError("未获得完整真实响应")
        content = json.loads(meta["content"])
        citations = content.get("citations")
        if (
            not isinstance(content.get("answer"), str)
            or not content["answer"].strip()
            or not isinstance(citations, list)
            or not citations
        ):
            raise ValueError("缺少引文")
        for c in citations:
            original = allowed.get(c.get("evidence_id"))
            if (
                not original
                or type(c.get("start")) is not int
                or type(c.get("end")) is not int
                or any(c.get(k) != original[k] for k in ("quote", "start", "end"))
            ):
                raise ValueError("引文不属于本次集合")
        result.update(
            answer=content["answer"],
            generation="generated",
            model_version=meta.get("model"),
        )
    except Exception:
        # Never promote the mock fallback or invalid model text into a grounded answer.
        result.update(answer=None, generation="error")
        result["reasons"].append("生成答复未通过证据校验，请查阅结构化结果与原文。")
