"""Optional vector recall and model reranking of already-authorized candidates.

No database search, document lookup, or implicit mock evidence lives here. The
caller supplies only fully authorized, applicable, accepted documentary facts.
"""

import json
import math
from ..services import embedding, ai, ai_config

CANDIDATE_LIMIT = 50
TEXT_LIMIT = 512
INPUT_CHAR_LIMIT = 32000
RERANK_LIMIT = 20
RERANK_TOKENS = 512
VECTOR_THRESHOLD = 0.35


def configuration():
    vector = embedding.get_embed_config()
    model = ai_config.get_full_config()
    return dict(
        embedding_enabled=bool(vector.get("enabled")),
        rerank_enabled=bool(
            model.get("enabled") and model.get("api_key") and model.get("base_url")
        ),
        embedding_model=vector.get("model"),
        model=model.get("model"),
    )


def cosine(a, b):
    if (
        not a
        or len(a) != len(b)
        or not all(type(x) in (int, float) and math.isfinite(x) for x in [*a, *b])
    ):
        raise ValueError("向量响应格式无效")
    denominator = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else 0.0


async def rank(p, question, candidates, lexical_ids, budget):
    cfg = configuration()
    trace = dict(
        status="disabled",
        candidate_limit=CANDIDATE_LIMIT,
        input_char_limit=INPUT_CHAR_LIMIT,
        rerank_limit=RERANK_LIMIT,
        max_tokens_ceiling=RERANK_TOKENS,
        max_retries=0,
        candidate_count=0,
        truncated=False,
        usage=None,
    )
    budget["ranking"] = trace
    if not p.has_feature("ai") or not cfg.get("embedding_enabled"):
        return {}, set(), []
    trace["truncated"] = len(candidates) > CANDIDATE_LIMIT
    batch = candidates[:CANDIDATE_LIMIT]
    if not batch:
        trace["status"] = "no_candidates"
        return {}, set(), []
    texts = [str(c["text"])[:TEXT_LIMIT] for c in batch]
    trace.update(
        candidate_count=len(batch),
        input_characters=len(question) + sum(map(len, texts)),
        embedding_model=cfg.get("embedding_model"),
        model_version=cfg.get("model"),
    )
    if trace["input_characters"] > INPUT_CHAR_LIMIT:
        trace["status"] = "budget_exhausted"
        return {}, set(), []
    dependencies = [c["id"] for c in batch]
    try:
        query = await embedding.embed_query(question)
        vectors = await embedding.embed_texts(texts, kind="db")
        if not vectors or len(vectors) != len(batch):
            raise ValueError("向量检索不可用")
        scores = {c["id"]: cosine(query, vector) for c, vector in zip(batch, vectors)}
        recalled = {rid for rid, score in scores.items() if score >= VECTOR_THRESHOLD}
        eligible = [c for c in batch if c["id"] in recalled or c["id"] in lexical_ids]
        eligible.sort(key=lambda c: (-scores[c["id"]], c["id"]))
        trace["status"] = "vector_ranked"
        if cfg.get("rerank_enabled") and eligible:
            shortlist = eligible[:RERANK_LIMIT]
            payload = [
                dict(id=c["id"], text=str(c["text"])[:TEXT_LIMIT]) for c in shortlist
            ]
            meta = await ai.chat_real_meta(
                [
                    dict(
                        role="system",
                        content='仅重排给定候选。输出JSON {"items":[{"id":整数候选ID,"score":0到1}]}。禁止新增候选、正文或推理。',
                    ),
                    dict(
                        role="user",
                        content=json.dumps(
                            dict(question=question, items=payload), ensure_ascii=False
                        ),
                    ),
                ],
                max_tokens=RERANK_TOKENS,
                max_tokens_ceiling=RERANK_TOKENS,
                max_retries=0,
            )
            trace.update(
                {
                    k: meta.get(k)
                    for k in (
                        "usage",
                        "max_tokens",
                        "retried",
                        "retry_count",
                        "finish_reason",
                    )
                }
            )
            if (
                meta.get("mock")
                or meta.get("truncated")
                or meta.get("finish_reason") in ("mock", "mock_fallback")
            ):
                raise ValueError("重排未获得完整真实响应")
            rows = json.loads(meta["content"]).get("items")
            allowed = {c["id"] for c in shortlist}
            if not isinstance(rows, list) or not rows or len(rows) > RERANK_LIMIT:
                raise ValueError("重排候选格式无效")
            seen = set()
            for row in rows:
                rid = row.get("id")
                value = row.get("score")
                if (
                    type(rid) is not int
                    or rid not in allowed
                    or rid in seen
                    or type(value) not in (int, float)
                    or not math.isfinite(value)
                    or not 0 <= value <= 1
                ):
                    raise ValueError("重排包含集合外候选或错误分数")
                seen.add(rid)
                scores[rid] = 1.0 + value
            trace["status"] = "ranked"
        return scores, recalled, dependencies
    except Exception:
        trace["status"] = "error"
        # Authorized lexical search remains available; never trust model IDs.
        return {}, set(), dependencies
