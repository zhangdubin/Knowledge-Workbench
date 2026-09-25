"""预置应用种子：项目管理 / 销售管理 / 合同管理

启动时如果数据库为空则自动创建。已存在则跳过。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EntityType, FieldDefinition, RelationDef, EntityRecord


SEED_APPS = [
    {
        "key": "project",
        "name": "项目管理",
        "icon": "📋",
        "description": "项目、任务、里程碑、成员管理",
        "order": 1,
        "fields": [
            {"key": "name", "name": "项目名称", "type": "text", "required": True, "order": 1},
            {"key": "code", "name": "项目代号", "type": "text", "order": 2},
            {"key": "status", "name": "状态", "type": "select",
             "options": {"choices": ["规划中", "进行中", "已完成", "已归档"]}, "order": 3},
            {"key": "owner", "name": "负责人", "type": "text", "order": 4},
            {"key": "start_date", "name": "开始日期", "type": "date", "order": 5},
            {"key": "end_date", "name": "结束日期", "type": "date", "order": 6},
            {"key": "budget", "name": "预算(¥)", "type": "number", "order": 7},
            {"key": "description", "name": "项目说明", "type": "textarea", "order": 8},
        ],
    },
    {
        "key": "task",
        "name": "任务",
        "icon": "✅",
        "description": "任务清单",
        "app": "project",
        "order": 2,
        "fields": [
            {"key": "name", "name": "任务名称", "type": "text", "required": True, "order": 1},
            {"key": "project", "name": "所属项目", "type": "reference",
             "options": {"target": "project"}, "order": 2},
            {"key": "assignee", "name": "负责人", "type": "text", "order": 3},
            {"key": "status", "name": "状态", "type": "select",
             "options": {"choices": ["待办", "进行中", "已完成", "已取消"]}, "order": 4},
            {"key": "priority", "name": "优先级", "type": "select",
             "options": {"choices": ["低", "中", "高", "紧急"]}, "order": 5},
            {"key": "due_date", "name": "截止日期", "type": "date", "order": 6},
            {"key": "description", "name": "描述", "type": "textarea", "order": 7},
        ],
    },
    # 销售管理
    {
        "key": "customer",
        "name": "客户",
        "icon": "🏢",
        "description": "客户档案",
        "app": "sales",
        "order": 1,
        "fields": [
            {"key": "name", "name": "客户名称", "type": "text", "required": True, "order": 1},
            {"key": "contact", "name": "联系人", "type": "text", "order": 2},
            {"key": "phone", "name": "联系电话", "type": "text", "order": 3},
            {"key": "email", "name": "邮箱", "type": "text", "order": 4},
            {"key": "level", "name": "客户级别", "type": "select",
             "options": {"choices": ["普通", "VIP", "战略"]}, "order": 5},
            {"key": "industry", "name": "行业", "type": "text", "order": 6},
            {"key": "address", "name": "地址", "type": "text", "order": 7},
            {"key": "notes", "name": "备注", "type": "textarea", "order": 8},
        ],
    },
    {
        "key": "opportunity",
        "name": "商机",
        "icon": "💼",
        "description": "销售商机",
        "app": "sales",
        "order": 2,
        "fields": [
            {"key": "name", "name": "商机名称", "type": "text", "required": True, "order": 1},
            {"key": "customer", "name": "客户", "type": "reference",
             "options": {"target": "customer"}, "order": 2},
            {"key": "amount", "name": "预期金额(¥)", "type": "number", "order": 3},
            {"key": "stage", "name": "阶段", "type": "select",
             "options": {"choices": ["初步接洽", "需求确认", "方案报价", "商务谈判", "成交", "丢单"]},
             "order": 4},
            {"key": "owner", "name": "负责人", "type": "text", "order": 5},
            {"key": "expected_close", "name": "预计成交日", "type": "date", "order": 6},
            {"key": "description", "name": "说明", "type": "textarea", "order": 7},
        ],
    },
    {
        "key": "order",
        "name": "订单",
        "icon": "📦",
        "description": "客户订单",
        "app": "sales",
        "order": 3,
        "fields": [
            {"key": "code", "name": "订单号", "type": "text", "required": True, "order": 1},
            {"key": "customer", "name": "客户", "type": "reference",
             "options": {"target": "customer"}, "order": 2},
            {"key": "opportunity", "name": "来源商机", "type": "reference",
             "options": {"target": "opportunity"}, "order": 3},
            {"key": "amount", "name": "订单金额(¥)", "type": "number", "order": 4},
            {"key": "status", "name": "状态", "type": "select",
             "options": {"choices": ["待付款", "已付款", "已发货", "已完成", "已取消"]},
             "order": 5},
            {"key": "order_date", "name": "下单日期", "type": "date", "order": 6},
            {"key": "notes", "name": "备注", "type": "textarea", "order": 7},
        ],
    },
    # 合同管理
    {
        "key": "contract",
        "name": "合同",
        "icon": "📄",
        "description": "商务合同档案",
        "app": "contract",
        "order": 1,
        "fields": [
            {"key": "code", "name": "合同编号", "type": "text", "required": True, "order": 1},
            {"key": "title", "name": "合同标题", "type": "text", "required": True, "order": 2},
            {"key": "customer", "name": "客户", "type": "reference",
             "options": {"target": "customer"}, "order": 3},
            {"key": "opportunity", "name": "关联商机", "type": "reference",
             "options": {"target": "opportunity"}, "order": 4},
            {"key": "amount", "name": "合同金额(¥)", "type": "number", "order": 5},
            {"key": "status", "name": "状态", "type": "select",
             "options": {"choices": ["草稿", "生效中", "已到期", "已终止"]},
             "order": 6},
            {"key": "sign_date", "name": "签订日期", "type": "date", "order": 7},
            {"key": "expire_date", "name": "到期日期", "type": "date", "order": 8},
            {"key": "owner", "name": "经办人", "type": "text", "order": 9},
            {"key": "attachment", "name": "合同附件", "type": "file", "order": 10},
            {"key": "description", "name": "备注", "type": "textarea", "order": 11},
        ],
    },
    {
        "key": "payment",
        "name": "付款计划",
        "icon": "💰",
        "description": "分期付款",
        "app": "contract",
        "order": 2,
        "fields": [
            {"key": "contract", "name": "合同", "type": "reference",
             "options": {"target": "contract"}, "required": True, "order": 1},
            {"key": "phase", "name": "期次", "type": "text", "order": 2},
            {"key": "amount", "name": "金额(¥)", "type": "number", "order": 3},
            {"key": "due_date", "name": "应付款日", "type": "date", "order": 4},
            {"key": "paid_date", "name": "实付日期", "type": "date", "order": 5},
            {"key": "status", "name": "状态", "type": "select",
             "options": {"choices": ["待付", "已付", "逾期"]}, "order": 6},
        ],
    },
]


SEED_SAMPLES = [
    # 项目管理
    ("project", "project", [
        {"name": "KB Workbench 开发", "code": "KB-2026-01", "status": "进行中",
         "owner": "张三", "start_date": "2026-08-01", "end_date": "2026-12-31",
         "budget": 500000, "description": "搭建统一的知识管理与应用平台"},
        {"name": "客户案例库建设", "code": "CASE-2026", "status": "规划中",
         "owner": "李四", "start_date": "2026-09-01", "end_date": "2026-11-30",
         "budget": 80000, "description": "整理历史客户案例"},
    ]),
    ("project", "task", [
        {"name": "后端 Meta-Schema 设计", "project": "KB Workbench 开发",
         "assignee": "张三", "status": "已完成", "priority": "高", "due_date": "2026-09-15"},
        {"name": "前端动态表单", "project": "KB Workbench 开发",
         "assignee": "王五", "status": "进行中", "priority": "高", "due_date": "2026-10-10"},
        {"name": "图谱可视化", "project": "KB Workbench 开发",
         "assignee": "王五", "status": "待办", "priority": "中", "due_date": "2026-10-20"},
        {"name": "客户访谈", "project": "客户案例库建设",
         "assignee": "李四", "status": "进行中", "priority": "中", "due_date": "2026-10-01"},
    ]),
    # 销售管理
    ("sales", "customer", [
        {"name": "深圳前海科技有限公司", "contact": "张总", "phone": "13800138001",
         "email": "zhang@qh-tech.com", "level": "VIP", "industry": "互联网",
         "address": "深圳市南山区"},
        {"name": "上海智云信息", "contact": "刘经理", "phone": "13800138002",
         "email": "liu@zhiyun.cn", "level": "战略", "industry": "金融科技",
         "address": "上海市浦东新区"},
        {"name": "北京蓝海咨询", "contact": "陈总", "phone": "13800138003",
         "email": "chen@bluelake.cn", "level": "普通", "industry": "咨询服务",
         "address": "北京市海淀区"},
    ]),
    ("sales", "opportunity", [
        {"name": "Q4 知识库采购项目", "customer": "深圳前海科技有限公司",
         "amount": 280000, "stage": "方案报价", "owner": "销售-A",
         "expected_close": "2026-10-31"},
        {"name": "金融数据中台", "customer": "上海智云信息",
         "amount": 1200000, "stage": "商务谈判", "owner": "销售-B",
         "expected_close": "2026-11-15"},
    ]),
    # 合同管理
    ("contract", "contract", [
        {"code": "HT-2026-001", "title": "前海科技知识库采购合同",
         "customer": "深圳前海科技有限公司", "amount": 280000, "status": "生效中",
         "sign_date": "2026-09-15", "expire_date": "2027-09-14", "owner": "销售-A"},
    ]),
]


SEED_RELATIONS = [
    {"key": "task_of_project", "name": "所属项目",
     "source": "task", "target": "project", "cardinality": "many-to-one"},
    {"key": "opp_of_customer", "name": "所属客户",
     "source": "opportunity", "target": "customer", "cardinality": "many-to-one"},
    {"key": "order_of_customer", "name": "客户订单",
     "source": "order", "target": "customer", "cardinality": "many-to-one"},
    {"key": "order_of_opp", "name": "订单关联商机",
     "source": "order", "target": "opportunity", "cardinality": "many-to-one"},
    {"key": "contract_of_customer", "name": "客户合同",
     "source": "contract", "target": "customer", "cardinality": "many-to-one"},
    {"key": "contract_of_opp", "name": "合同关联商机",
     "source": "contract", "target": "opportunity", "cardinality": "many-to-one"},
    {"key": "payment_of_contract", "name": "付款计划",
     "source": "payment", "target": "contract", "cardinality": "many-to-one"},
]


async def run_seed(db: AsyncSession):
    """运行种子。如果已有任何实体类型则跳过。"""
    existing = (await db.execute(select(EntityType))).first()
    if existing:
        return  # 已初始化

    # 创建实体类型
    type_by_key: dict[str, EntityType] = {}
    for spec in SEED_APPS:
        app = spec.get("app", spec["key"])
        et = EntityType(
            key=spec["key"],
            name=spec["name"],
            icon=spec.get("icon", "📦"),
            description=spec.get("description", ""),
            app=app,
            order=spec.get("order", 0),
        )
        db.add(et)
        await db.flush()
        for f in spec["fields"]:
            db.add(FieldDefinition(
                entity_type_id=et.id,
                key=f["key"],
                name=f["name"],
                type=f["type"],
                required=f.get("required", False),
                options=f.get("options", {}),
                order=f.get("order", 0),
            ))
        type_by_key[spec["key"]] = et

    # 创建关系定义
    for rel in SEED_RELATIONS:
        src = type_by_key.get(rel["source"])
        tgt = type_by_key.get(rel["target"])
        if not src or not tgt:
            continue
        db.add(RelationDef(
            key=rel["key"],
            name=rel["name"],
            source_type_id=src.id,
            target_type_id=tgt.id,
            cardinality=rel["cardinality"],
        ))

    # 创建样例记录（先建不依赖外键的，再建依赖外键的，按顺序处理）
    # 第一遍：创建所有非 reference 字段记录的"主体"，先记住映射
    record_map: dict[str, dict[str, EntityRecord]] = {}
    for app, type_key, samples in SEED_SAMPLES:
        et = type_by_key[type_key]
        record_map[type_key] = {}
        for data in samples:
            rec = EntityRecord(
                entity_type_id=et.id,
                data=data,
                search_text=" ".join(str(v) for v in data.values() if isinstance(v, (str, int))),
            )
            db.add(rec)
            await db.flush()
            record_map[type_key][data.get("name") or data.get("code")] = rec

    # 第二遍：解析 reference 字段（按名称匹配）
    from ..services.record import build_search_text
    for app, type_key, samples in SEED_SAMPLES:
        et = type_by_key[type_key]
        # 取该类型字段定义（顶层已导入 FieldDefinition，避免在函数体内重复 import）
        f_q = select(FieldDefinition).where(FieldDefinition.entity_type_id == et.id)
        fields = (await db.execute(f_q)).scalars().all()

        # 重读 records 来更新
        for data in samples:
            key = data.get("name") or data.get("code")
            rec = record_map[type_key].get(key)
            if not rec:
                continue
            new_data = dict(data)
            for f in fields:
                if f.type == "reference":
                    target_key = (f.options or {}).get("target")
                    target_name = data.get(f.key)
                    if target_key and target_name and target_key in record_map:
                        target_rec = record_map[target_key].get(target_name)
                        if target_rec:
                            new_data[f.key] = target_rec.id  # reference 存 ID
            rec.data = new_data
            rec.search_text = build_search_text(fields, new_data)

    await db.commit()