"""JSON 工具 API：解析、序列化、树形展开

前端本身有原生 JSON.parse，这个路由存在的意义是：
- 统一「解析失败」的报错口径（带行列信息）
- 给 AI / 外部脚本一个稳定的读取与构造入口
- 大文档由服务端展开成树，前端只负责渲染
"""
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from ..services import jsontree as svc

router = APIRouter(prefix="/api/json", tags=["json"])


class ParseIn(BaseModel):
    text: str


class ValueIn(BaseModel):
    value: Any = None
    text: str | None = None


class ParseOut(BaseModel):
    value: Any = None
    tree: list = []
    summary: dict = {}


@router.post("/parse", response_model=ParseOut)
def parse(payload: ParseIn):
    """JSON 文本 → 对象 + 树 + 统计"""
    try:
        value = svc.parse(payload.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"value": value, "tree": svc.to_tree(value), "summary": svc.get_summary(value)}


@router.post("/serialize")
def serialize(payload: ValueIn = Body(...)):
    """对象 → JSON 文本"""
    return {"text": svc.dumps(payload.value)}


@router.post("/to-tree", response_model=ParseOut)
def to_tree(payload: ValueIn = Body(...)):
    """文本或对象 → 树（前端只拿到能直接渲染的节点数组）"""
    try:
        value = svc.parse(payload.text) if payload.text else payload.value
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"value": value, "tree": svc.to_tree(value), "summary": svc.get_summary(value)}
