"""养料 DNA 路由：只读的体检与基因图谱

接口路径固定（前端只依赖这几个）：
    GET /api/dna/overview
    GET /api/dna/documents
    GET /api/dna/documents/{id}
    GET /api/dna/tree
    GET /api/dna/graph             （关联脉络图：nodes/edges/stats）
    GET /api/dna/report            （Markdown 文本）
    GET /api/dna/report.json

鉴权口径说明（一个容易踩的坑）：
    这里只挂 current_principal，**不**挂 require_page("dna")。
    原因：permissions.PAGES 里加 "dna" 只对**新建**的内置角色生效 ——
    bootstrap.ensure_builtin_roles 只在角色缺失时才建，
    不会覆盖库里已经存好的 perms JSON。
    线上库里的编辑/只读角色因此没有 "dna" 这个页面位，
    一旦在这里硬拦，页面会直接 403，而且升级路径根本不会自愈。
    真正的内容边界靠 services/access 那条统一规则（文件读权限）来兜。
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import dna as svc
from ..services.auth import Principal, current_principal

router = APIRouter(prefix="/api/dna", tags=["dna"])

REPORT_FILENAME = "养料-DNA.md"


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db),
                   principal: Principal = Depends(current_principal)):
    """总览：成分 + 指纹 + 体检清单 + 健康分"""
    return await svc.build_overview(db, principal)


@router.get("/documents")
async def documents(db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    """文档谱系列表"""
    return await svc.build_documents(db, principal)


@router.get("/documents/{doc_id}")
async def document_detail(doc_id: int, db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    """单篇 DNA：结构树 + 块清单 + 主题词 + 关联 + 这篇的问题"""
    detail = await svc.build_document_detail(db, principal, doc_id)
    if detail is None:
        # 404 而不是 403：读不到的文件与不存在的文件不在这条接口里区分，
        # 「这个文件你打不开」这句话本身就泄露了它的存在。
        raise HTTPException(404, "文件不存在或无权查看")
    return detail


@router.get("/tree")
async def tree(db: AsyncSession = Depends(get_db),
                principal: Principal = Depends(current_principal)):
    """全库结构索引"""
    return await svc.build_tree(db, principal)


@router.get("/graph")
async def graph(db: AsyncSession = Depends(get_db),
                principal: Principal = Depends(current_principal)):
    """关联脉络图：文件骨架 + 文件挂载 + 记录关联

    前端 vis-network 直接吃这个形状：节点三种（文件/小节/记录），
    边三种（章节/挂载/关联），id 前缀固定。
    """
    return await svc.build_graph(db, principal)


@router.get("/report")
async def report(db: AsyncSession = Depends(get_db),
                 principal: Principal = Depends(current_principal)):
    """Markdown 版总索引（文件名 养料-DNA.md）

    这份 Markdown 就是 OpenKB 的 AGENTS.md 的等价物 ——
    人和模型都靠它快速搞清「这批资料里有什么、能不能用」。
    """
    data = await svc.build_report_json(db, principal)
    text = svc.render_report_markdown(data)
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={
            # 中文文件名必须走 RFC 5987 编码，否则 header 非法
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(REPORT_FILENAME)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/report.json")
async def report_json(db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    """完整 JSON 报告（overview + documents + tree）"""
    return await svc.build_report_json(db, principal)
