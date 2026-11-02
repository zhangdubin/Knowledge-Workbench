"""AI 路由"""
import logging
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from ..database import get_db
from ..services.auth import require_feature, current_principal, Principal
from ..services import ai as ai_svc
from ..services import agent as agent_svc
from ..services import ai_config as ai_cfg_svc
from ..services import document as doc_svc
from ..services import embedding as embed_svc

log = logging.getLogger("kb.ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])

# AI 是独立授权项（会消耗 token、会把内容发给外部服务）
_AI = [Depends(require_feature("ai"))]


class ConfigIn(BaseModel):
    provider: str = "mock"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7
    # 回答长度上限：默认 4096（1024 太小，写两句就被切断）
    max_tokens: int = 4096
    # 被截断时自动加大长度重试
    auto_retry_on_truncation: bool = True
    # 自动重试时长度上限能涨到的天花板
    max_tokens_ceiling: int = 32768
    enabled: bool = False
    system_prompt: str = ""
    # True 清空 chat Key；传 "embed_api_key" 清空 embedding Key
    clear_api_key: bool | str = False

    # ---- 向量化 ----
    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_model: str = "embo-01"
    embed_style: str = "auto"
    embed_group_id: str = ""
    embed_timeout: int = 30
    embed_dim: int = 0


class SummarizeIn(BaseModel):
    text: str


class TagsIn(BaseModel):
    text: str
    max_tags: int = 5


class RewriteIn(BaseModel):
    text: str
    style: str = "polish"


class MeetingIn(BaseModel):
    text: str


class BeautifyIn(BaseModel):
    text: str


class NoteTemplateIn(BaseModel):
    title: str = ""
    tags: list[str] = []
    source: str = "human"
    scope: str = "concept"
    status: str = "draft"
    summary: str = ""


class TitleIn(BaseModel):
    content: str


class AskIn(BaseModel):
    question: str
    context: list[str] | None = None
    # 指定要参考的文件；留空时自动检索最相关的文件与笔记
    document_ids: list[int] | None = None
    auto_retrieve: bool = True
    # 钉住的养料库基因：不钉的话也会自动挑相关的基因，
    # 钉住的是「明确要用这一条」
    gene_ids: list[int] | None = None
    # 续写：把已经写出来（被截断）的答案回灌，让模型从断点接着写
    continuation: str = ""


class AgentIn(BaseModel):
    question: str
    history: list[dict] | None = None
    # 续写：把已经写出来（被截断）的内容回灌，让模型从断点接着写
    continuation: str = ""


class AgentConfirmIn(BaseModel):
    """用户点「确认执行」时回传的待办写操作

    参数由前端原样回传，但后端执行前会重新做一遍权限与字段校验，
    不信任客户端内容。
    """
    question: str = ""
    history: list[dict] | None = None
    tool: str
    args: dict = {}
    digest: list[str] | None = None
    # 续写（与 AgentIn 同义）：确认执行后如果回答又被截断，可以接着写
    continuation: str = ""


@router.post("/agent", dependencies=_AI)
async def agent(
    payload: AgentIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    """AI 操作中枢：自然语言 → 工具调用

    查询/统计类工具当场执行；新建/修改/删除只生成「待确认操作」
    （status=awaiting_confirmation），用户确认后走 /agent/confirm。
    工具一律按当前登录主体的模型级权限过滤。
    """
    return await agent_svc.run_agent(db, payload.question, principal,
                                   payload.history,
                                   continuation=payload.continuation or "")


@router.post("/agent/confirm", dependencies=_AI)
async def agent_confirm(
    payload: AgentConfirmIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    """执行用户已确认的 AI 写操作，并把结果交给模型收尾"""
    return await agent_svc.run_agent(
        db, payload.question, principal, payload.history,
        continuation=payload.continuation or "",
        confirmed={
            "tool": payload.tool,
            "args": payload.args or {},
            "digest": (payload.digest or [])[:20],
        },
    )



@router.get("/config", dependencies=_AI)
def get_config() -> dict:
    return ai_cfg_svc.get_public_config()


@router.put("/config", dependencies=_AI)
def update_config(payload: ConfigIn) -> dict:
    cfg = ai_cfg_svc.save_config(payload.model_dump())
    public = ai_cfg_svc.get_public_config()
    return {"ok": True, "config": public}


@router.post("/test", dependencies=_AI)
async def test_connection() -> dict:
    return await ai_svc.test_connection()


@router.get("/embedding", dependencies=_AI)
async def embedding_status() -> dict:
    """向量化配置状态（脱敏）"""
    return embed_svc.config_summary()


@router.post("/test-embedding", dependencies=_AI)
async def test_embedding(db: AsyncSession = Depends(get_db)) -> dict:
    """测试向量化连通性，并报告模型实际维度"""
    result = await embed_svc.test_embedding()
    if result.get("ok") and result.get("dim"):
        # 探测到维度后立刻建向量表，不必等下次重启
        cfg = ai_cfg_svc.load_config()
        cfg["embed_dim"] = int(result["dim"])
        ai_cfg_svc.save_config(cfg)
        from ..services import docindex
        await docindex.ensure_vec_table(db, int(result["dim"]))
        await db.commit()
        result["vec_table"] = "ready"
    return result



@router.post("/summarize", dependencies=_AI)
async def summarize(payload: SummarizeIn) -> dict:
    if not payload.text.strip():
        raise HTTPException(400, "文本为空")
    summary = await ai_svc.summarize(payload.text)
    return {"summary": summary}


@router.post("/tags", dependencies=_AI)
async def tags(payload: TagsIn) -> dict:
    if not payload.text.strip():
        raise HTTPException(400, "文本为空")
    t = await ai_svc.extract_tags(payload.text, payload.max_tags)
    return {"tags": t}


@router.post("/meeting-minutes", dependencies=_AI)
async def meeting_minutes(payload: MeetingIn) -> dict:
    """会议记录 → 结构化纪要（议题 / 讨论要点 / 决议 / 待办）"""
    if not payload.text.strip():
        raise HTTPException(400, "文本为空")
    result = await ai_svc.meeting_minutes(payload.text)
    return {"text": result}


@router.post("/beautify-layout", dependencies=_AI)
async def beautify_layout(payload: BeautifyIn) -> dict:
    """针对内容给出具体的排版改进建议"""
    if not payload.text.strip():
        raise HTTPException(400, "文本为空")
    result = await ai_svc.beautify_layout(payload.text)
    return {"text": result}


@router.post("/note-template", dependencies=_AI)
async def note_template(payload: NoteTemplateIn) -> dict:
    """新建笔记的模板（按《笔记 UI 排版规范》）

    和 Obsidian 里「从模板新建」是一回事：一建出来就是规范形态，
    不用事后再排一遍。
    """
    from ..services import note_format
    text = note_format.note_template(
        payload.title,
        tags=payload.tags,
        source=payload.source,
        scope=payload.scope,
        status=payload.status,
        summary=payload.summary,
    )
    return {"text": text}


@router.post("/rewrite", dependencies=_AI)
async def rewrite(payload: RewriteIn) -> dict:
    if not payload.text.strip():
        raise HTTPException(400, "文本为空")
    result = await ai_svc.rewrite(payload.text, payload.style)
    return {"text": result}


@router.post("/title", dependencies=_AI)
async def title(payload: TitleIn) -> dict:
    if not payload.content.strip():
        raise HTTPException(400, "内容为空")
    return {"title": await ai_svc.suggest_title(payload.content)}


@router.post("/ask", dependencies=_AI)
async def ask(payload: AskIn, db: AsyncSession = Depends(get_db),
              principal: Principal = Depends(current_principal)) -> dict:
    """AI 问答

    上下文来源按优先级：
      1. 前端显式传入的 context
      2. 显式指定的 document_ids
      3. 自动混合检索（关键词 + 向量）命中的文件与笔记

    检索到的内容按提问者的权限裁剪：读不了的文件与没权限的笔记
    不进上下文 —— 否则 AI 会把用户看不到的内容原样复述出来。
    """
    if not payload.question.strip():
        raise HTTPException(400, "问题为空")

    # 离线模式：模型调用要网络，断网时改成「直答」——
    # 把养料库里的基因与原文原样端出来，不做生成。
    # 宁可给不出漂亮答案，也不要给一个编出来的答案。
    try:
        from ..services import dna_library
        if await dna_library.is_offline(db):
            off = await dna_library.answer_offline(db, payload.question, limit=5)
            return {"answer": off["text"], "context_count": len(off["citations"]),
                    "sources": off["citations"], "offline": True,
                    "genes": off["genes"],
                    # 离线直答是把原文端出来，不存在长度截断
                    "truncated": False, "finish_reason": "offline"}
    except Exception:
        pass

    context = list(payload.context or [])
    sources: list[dict] = []

    if payload.document_ids or (payload.auto_retrieve and not context):
        try:
            picked = await doc_svc.build_ai_context(
                db, payload.question, payload.document_ids, principal=principal
            )
            context.extend(picked["chunks"])
            sources = picked["sources"]
        except Exception:
            pass

    # 养料库基因：钉住的优先，没钉的自动挑相关的
    genes = await _collect_genes(db, principal, payload.question,
                                 payload.gene_ids or [])
    # 基因块也要有编号：上下文块统一按【n】编号，
    # 模型引用时才能同时标「第 n 条」和「哪条基因」。
    # 编号接着已有的往后排，不跟文件块撞号。
    base_no = 0
    for c in context:
        m = re.match(r"^【(\d+)】", c or "")
        if m:
            base_no = max(base_no, int(m.group(1)))
    for i, g in enumerate(genes, start=1):
        no = base_no + i
        context.append(
            f"【{no} · 基因#{g['id']}】{g['title']}（{g['kind_label']}）\n{g['content']}")
        g["citation"] = no

    # 用 ask_meta 拿结构化信息：正文 + 是否被截断 + finish_reason。
    # 以前只拿一段字符串，前端根本不知道「模型写了一半」。
    meta = await ai_svc.ask_meta(payload.question, context, genes=genes,
                                  continuation=payload.continuation or "")
    answer = meta.get("content") or ""
    # 模型写的是「上下文第几块」，要还原成基因自己的编号 ——
    # 不还原的话，答案里的【基因#5】会被当成 5 号基因，而实际上是 25 号。
    aliases = {g["citation"]: g["id"] for g in genes if g.get("citation")}
    answer = ai_svc.normalize_gene_citations(answer, aliases)

    # 知识缺口：答不上来的问题记一笔；补上知识后同名缺口自动关闭。
    # 「不断喂养、不断自主进化」要闭环，光有吸收不够 ——
    # 得知道缺什么，才知道下一轮该喂什么。
    try:
        from ..services import dna_ingest
        if dna_ingest.looks_like_no_answer(answer):
            await dna_ingest.record_gap(db, payload.question, answer)
        else:
            await dna_ingest.close_matching_gaps(
                db, payload.question,
                filled_by=",".join(f"基因#{g['id']}" for g in genes[:3]))
    except Exception as e:
        log.warning("知识缺口记录失败：%s", e)

    return {"answer": answer, "context_count": len(context),
            "sources": sources, "genes": genes,
            # 截断信息：前端据此提示「回答被截断」并给「继续写」入口
            "truncated": bool(meta.get("truncated")),
            "finish_reason": meta.get("finish_reason"),
            "max_tokens": meta.get("max_tokens"),
            "retried": bool(meta.get("retried"))}


async def _collect_genes(db, principal, question: str,
                          gene_ids: list[int]) -> list[dict]:
    """凑出这次问答要用的养料库基因

    钉住的基因一定用上（用户明确指定了）；
    没钉的时候自动挑几条相关的 ——
    「在系统任何地方直接可以引用」的意思是：
    不需要用户先知道库里有什么，问答自己会去用。
    """
    from ..services import dna_library as dna_lib
    out: list[dict] = []
    seen: set[int] = set()
    if gene_ids:
        for gid in gene_ids[:12]:
            try:
                g = await dna_lib.get_gene(db, gid)
            except Exception:
                continue
            if g is None or g.id in seen:
                continue
            seen.add(g.id)
            out.append(_gene_ref(g))
    if not out:
        try:
            # 自动挑的时候只挑 3 条、正文只带 500 字：
            # 自动注入是「提个醒」，不是「倒一桶」——
            # 上下文里塞太多，模型会顺着写成长表格，答案写到一半被 max_tokens 截断。
            hits = await dna_lib.search_genes(db, question, limit=3,
                                              kinds=["method", "experience",
                                                     "policy", "interface"])
        except Exception:
            hits = []
        for h in hits:
            g = h.get("gene")
            if g is None or g.id in seen:
                continue
            if (g.confidence or 0) < 0.7:
                continue
            seen.add(g.id)
            ref = _gene_ref(g)
            ref["content"] = (ref["content"] or "")[:500]
            out.append(ref)
    return out


def _gene_ref(g) -> dict:
    return {
        "id": g.id,
        "kind": g.kind,
        "kind_label": dna_kind_label(g.kind),
        "title": g.title,
        "content": (g.content or "")[:1500],
        "source_title": g.source_title or "",
        "source_ref": g.source_ref or "",
        "usage_count": g.usage_count or 0,
        "confidence": g.confidence or 0,
        "citation": 0,
    }


def dna_kind_label(kind: str) -> str:
    return {"fact": "事实", "method": "方法", "experience": "经验",
            "interface": "接口", "policy": "约定"}.get(kind, kind or "基因")
