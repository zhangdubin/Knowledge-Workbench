"""AI 路由"""
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

router = APIRouter(prefix="/api/ai", tags=["ai"])

# AI 是独立授权项（会消耗 token、会把内容发给外部服务）
_AI = [Depends(require_feature("ai"))]


class ConfigIn(BaseModel):
    provider: str = "mock"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
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


class TitleIn(BaseModel):
    content: str


class AskIn(BaseModel):
    question: str
    context: list[str] | None = None
    # 指定要参考的文件；留空时自动检索最相关的文件与笔记
    document_ids: list[int] | None = None
    auto_retrieve: bool = True


class AgentIn(BaseModel):
    question: str
    history: list[dict] | None = None


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
    return await agent_svc.run_agent(db, payload.question, principal, payload.history)


@router.post("/agent/confirm", dependencies=_AI)
async def agent_confirm(
    payload: AgentConfirmIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    """执行用户已确认的 AI 写操作，并把结果交给模型收尾"""
    return await agent_svc.run_agent(
        db, payload.question, principal, payload.history,
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
async def ask(payload: AskIn, db: AsyncSession = Depends(get_db)) -> dict:
    """AI 问答

    上下文来源按优先级：
      1. 前端显式传入的 context
      2. 显式指定的 document_ids
      3. 自动混合检索（关键词 + 向量）命中的文件与笔记
    """
    if not payload.question.strip():
        raise HTTPException(400, "问题为空")

    context = list(payload.context or [])
    sources: list[dict] = []

    if payload.document_ids or (payload.auto_retrieve and not context):
        try:
            picked = await doc_svc.build_ai_context(
                db, payload.question, payload.document_ids
            )
            context.extend(picked["chunks"])
            sources = picked["sources"]
        except Exception:
            pass

    answer = await ai_svc.ask(payload.question, context)
    return {"answer": answer, "context_count": len(context), "sources": sources}

