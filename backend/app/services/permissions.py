"""权限点定义 —— 后端与前端共用同一份枚举

放在单独模块里而不是散在路由中：前端登录后会拿到 `pages` / `features`
两份清单，菜单过滤与按钮显隐都靠它们，两边口径必须一致。
改动这里的 key 等于改动接口契约。
"""
from __future__ import annotations

# 允许分配权限的页面 key（与前端路由 meta.perm 一一对应）
PAGES = [
    "dashboard",       # 工作台
    "dashboards",      # 驾驶舱
    "library",         # 数据中心
    "notes",           # 知识库
    "apps",            # 应用中心
    "types",           # 数据模型
    "records",         # 记录
    "relations",       # 关联定义
    "graph",           # 关联图谱
    "knowledge_graph", # 知识图谱
    "search",          # 全局搜索
    "guide",           # 使用指南
    "ai",              # AI 设置
    "system",          # 系统管理（用户/角色/审计）
]

PAGE_LABELS = {
    "dashboard": "工作台",
    "dashboards": "可视化驾驶舱",
    "library": "数据中心",
    "notes": "知识库",
    "apps": "应用中心",
    "types": "数据模型",
    "records": "业务记录",
    "relations": "关联定义",
    "graph": "关联图谱",
    "knowledge_graph": "知识图谱",
    "search": "全局搜索",
    "guide": "使用指南",
    "ai": "AI 设置",
    "system": "系统管理",
}

# 功能位：跨页面的操作级权限
#
# 注意这里**没有**「录入记录」这种权限点 —— 记录能否写由模型级
# 权限（models: {key: read|write}）决定。两套机制重叠只会让人
# 搞不清该改哪一个，所以操作级只保留「模型结构/文件/关联」这类
# 不属于任何单个模型的权限。
FEATURES = [
    "model_manage",     # 新建/修改/删除数据模型
    "relation_manage",  # 维护关联定义与关联关系
    "file_write",       # 上传/改文件元数据
    "file_delete",      # 删除文件（含彻底删除）
    "dashboard_write",  # 编辑驾驶舱
    "ai",               # 调用 AI 能力
    "user_manage",      # 用户管理
    "role_manage",      # 角色管理
    "audit_view",       # 查看审计日志
    "storage_manage",   # 存储诊断与维护（含备份、回收空间）
    "system_config",    # 修改运行期配置（备份目录、保留份数、初始口令）
]

FEATURE_LABELS = {
    "model_manage": "维护数据模型",
    "relation_manage": "维护关联关系",
    "file_write": "上传 / 修改文件",
    "file_delete": "删除文件",
    "dashboard_write": "编辑驾驶舱",
    "ai": "使用 AI 能力",
    "user_manage": "用户管理",
    "role_manage": "角色管理",
    "audit_view": "查看审计日志",
    "storage_manage": "存储与备份管理",
    "system_config": "系统配置管理",
}

MODEL_LEVELS = ["none", "read", "write"]
MODEL_LEVEL_LABELS = {"none": "不可见", "read": "只读", "write": "可读写"}


def _all_features(on: bool = True) -> dict:
    return {k: on for k in FEATURES}


def admin_perms() -> dict:
    return {"all": True, "pages": list(PAGES), "models": {"*": "write"},
            "features": _all_features(True)}


def editor_perms() -> dict:
    """编辑：业务数据读写，但不碰系统管理与模型结构"""
    feats = _all_features(False)
    feats.update({
        "relation_manage": True,
        "file_write": True, "file_delete": True,
        "dashboard_write": True, "ai": True,
    })
    return {
        "all": False,
        "pages": [p for p in PAGES if p != "system"],
        "models": {"*": "write"},
        "features": feats,
    }


def viewer_perms() -> dict:
    """只读：能看能搜能用 AI，任何写操作都被拦住"""
    feats = _all_features(False)
    feats["ai"] = True
    return {
        "all": False,
        "pages": [p for p in PAGES if p != "system"],
        "models": {"*": "read"},
        "features": feats,
    }


BUILTIN_ROLES = [
    {"key": "admin", "name": "管理员", "description": "全部权限，含用户与角色管理", "perms": admin_perms()},
    {"key": "editor", "name": "编辑", "description": "可录入与修改业务数据，不能管理用户与模型结构", "perms": editor_perms()},
    {"key": "viewer", "name": "只读", "description": "只能查看、搜索与问答，不能修改任何数据", "perms": viewer_perms()},
]
