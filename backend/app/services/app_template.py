"""应用模板：一键生成「应用 + 数据模型 + 字段 + 关联定义」

解决"不知道新建应用怎么用、数据模型怎么用"的问题：
用户选一个业务模板，系统直接给出可用的模型骨架，立刻能录数据。

模板内 type/relation 的 key 会被加上 `<app_key>_` 前缀，
因为 EntityType.key 全局唯一，同一模板建两次必须不冲突。
reference 字段用 "target_ref" 指向模板内的相对 key，落库时翻译成前缀 key。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import App, EntityType, FieldDefinition, RelationDef


def _f(key, name, type_, required=False, options=None, help_text=""):
    d = {"key": key, "name": name, "type": type_, "required": required,
         "options": options or {}}
    if help_text:
        d["help_text"] = help_text
    return d


# 常用字段片段，减少重复
STATUS = lambda: _f("status", "状态", "select", options={"choices": ["未开始", "进行中", "已完成", "已暂停"]})
OWNER = lambda: _f("owner", "负责人", "text")
PRIORITY = lambda: _f("priority", "优先级", "select",
                      options={"choices": ["低", "中", "高", "紧急"]})
AMOUNT = lambda: _f("amount", "金额（元）", "number")
DESC = lambda: _f("description", "说明", "textarea")


def _text(key, name, required=False, help_text=""):
    return _f(key, name, "text", required, help_text=help_text)


TEMPLATES: dict[str, dict] = {
    "blank": {
        "key": "blank",
        "name": "空白应用",
        "icon": "Grid",
        "description": "不预置任何模型，从零开始定义",
        "types": [],
        "relations": [],
    },

    "project": {
        "key": "project",
        "name": "项目管理",
        "icon": "Management",
        "description": "项目 / 任务 / 里程碑 / 风险，含模型间关联",
        "types": [
            {
                "key": "project", "name": "项目", "icon": "Briefcase",
                "description": "一个可交付的项目主体",
                "fields": [
                    _text("name", "项目名称", True, "列表页会优先显示这个字段"),
                    _f("code", "项目编号", "text"),
                    STATUS(),
                    OWNER(),
                    PRIORITY(),
                    _f("budget", "预算（元）", "number"),
                    _f("start_date", "开始日期", "date"),
                    _f("end_date", "计划完成", "date"),
                    DESC(),
                    _f("files", "项目文档", "file"),
                ],
            },
            {
                "key": "task", "name": "任务", "icon": "List",
                "description": "项目下的具体工作项",
                "fields": [
                    _text("name", "任务名称", True),
                    _f("project", "所属项目", "reference", options={"target_ref": "project"}),
                    STATUS(),
                    OWNER(),
                    PRIORITY(),
                    _f("due_date", "截止日期", "date"),
                    _f("progress", "进度（%）", "number"),
                    DESC(),
                    _f("attachments", "附件", "file"),
                ],
            },
            {
                "key": "milestone", "name": "里程碑", "icon": "Flag",
                "description": "项目关键节点",
                "fields": [
                    _text("name", "里程碑名称", True),
                    _f("project", "所属项目", "reference", options={"target_ref": "project"}),
                    _f("due_date", "目标日期", "date"),
                    _f("done", "是否达成", "boolean"),
                    DESC(),
                ],
            },
            {
                "key": "risk", "name": "风险", "icon": "Warning",
                "description": "项目风险登记册",
                "fields": [
                    _text("name", "风险描述", True),
                    _f("project", "所属项目", "reference", options={"target_ref": "project"}),
                    _f("level", "等级", "select", options={"choices": ["低", "中", "高"]}),
                    _f("strategy", "应对措施", "textarea"),
                    _f("closed", "已关闭", "boolean"),
                ],
            },
        ],
        "relations": [
            {"key": "project_task", "name": "项目包含任务", "source": "project", "target": "task"},
            {"key": "project_milestone", "name": "项目里程碑", "source": "project", "target": "milestone"},
            {"key": "project_risk", "name": "项目风险", "source": "project", "target": "risk"},
        ],
    },

    "sales": {
        "key": "sales",
        "name": "销售管理",
        "icon": "ShoppingCart",
        "description": "客户 / 商机 / 订单 / 跟进记录",
        "types": [
            {
                "key": "customer", "name": "客户", "icon": "User",
                "description": "客户主数据",
                "fields": [
                    _text("name", "客户名称", True),
                    _f("industry", "所属行业", "text"),
                    _f("level", "客户等级", "select",
                       options={"choices": ["A", "B", "C", "D"]}),
                    _text("contact", "联系人"),
                    _text("phone", "联系电话"),
                    _text("email", "邮箱"),
                    _f("address", "地址", "text"),
                    DESC(),
                ],
            },
            {
                "key": "opportunity", "name": "商机", "icon": "TrendCharts",
                "description": "潜在成交机会",
                "fields": [
                    _text("name", "商机名称", True),
                    _f("customer", "客户", "reference", options={"target_ref": "customer"}),
                    _f("stage", "阶段", "select",
                       options={"choices": ["初步接触", "需求确认", "方案报价", "商务谈判", "赢单", "输单"]}),
                    AMOUNT(),
                    _f("probability", "赢率（%）", "number"),
                    _f("expected_close", "预计成交", "date"),
                    OWNER(),
                    DESC(),
                ],
            },
            {
                "key": "order", "name": "订单", "icon": "Tickets",
                "description": "成交后的订单",
                "fields": [
                    _text("code", "订单号", True),
                    _f("customer", "客户", "reference", options={"target_ref": "customer"}),
                    AMOUNT(),
                    _f("sign_date", "签约日期", "date"),
                    _f("status", "状态", "select",
                       options={"choices": ["待付款", "已付款", "已发货", "已完成", "已取消"]}),
                    DESC(),
                ],
            },
            {
                "key": "followup", "name": "跟进记录", "icon": "ChatDotRound",
                "description": "销售跟进流水",
                "fields": [
                    _text("name", "跟进主题", True),
                    _f("customer", "客户", "reference", options={"target_ref": "customer"}),
                    _f("follow_time", "跟进时间", "datetime"),
                    _f("channel", "方式", "select",
                       options={"choices": ["电话", "拜访", "微信", "邮件", "会议"]}),
                    _f("content", "跟进内容", "textarea"),
                    _f("next_action", "下一步", "text"),
                ],
            },
        ],
        "relations": [
            {"key": "customer_opportunity", "name": "客户商机", "source": "customer", "target": "opportunity"},
            {"key": "customer_order", "name": "客户订单", "source": "customer", "target": "order"},
            {"key": "opportunity_order", "name": "商机成交", "source": "opportunity", "target": "order"},
        ],
    },

    "contract": {
        "key": "contract",
        "name": "合同管理",
        "icon": "Files",
        "description": "合同 / 付款计划 / 相对方",
        "types": [
            {
                "key": "contract", "name": "合同", "icon": "Files",
                "description": "合同主档，支持上传合同 PDF 原件",
                "fields": [
                    _text("name", "合同名称", True),
                    _text("code", "合同编号"),
                    _f("counterparty", "相对方", "text"),
                    _f("type", "合同类型", "select",
                       options={"choices": ["销售合同", "采购合同", "服务合同", "框架协议", "保密协议"]}),
                    AMOUNT(),
                    _f("sign_date", "签订日期", "date"),
                    _f("start_date", "生效日期", "date"),
                    _f("end_date", "到期日期", "date"),
                    _f("status", "状态", "select",
                       options={"choices": ["草拟", "审批中", "履行中", "已完成", "已终止"]}),
                    _f("file", "合同原件（PDF/Word）", "file"),
                    DESC(),
                ],
            },
            {
                "key": "payment", "name": "付款计划", "icon": "Money",
                "description": "合同下的收付款节点",
                "fields": [
                    _text("name", "款项名称", True),
                    _f("contract", "所属合同", "reference", options={"target_ref": "contract"}),
                    AMOUNT(),
                    _f("plan_date", "计划日期", "date"),
                    _f("direction", "收/付", "select", options={"choices": ["收款", "付款"]}),
                    _f("paid", "已结清", "boolean"),
                    _f("paid_date", "实际日期", "date"),
                    _f("invoice", "票据附件", "file"),
                ],
            },
            {
                "key": "vendor", "name": "相对方", "icon": "OfficeBuilding",
                "description": "合作单位 / 供应商主数据",
                "fields": [
                    _text("name", "单位名称", True),
                    _text("credit_code", "统一社会信用代码"),
                    _text("contact", "联系人"),
                    _text("phone", "联系电话"),
                    _f("is_supplier", "是供应商", "boolean"),
                    _f("is_customer", "是客户", "boolean"),
                    DESC(),
                ],
            },
        ],
        "relations": [
            {"key": "contract_payment", "name": "合同付款计划", "source": "contract", "target": "payment"},
        ],
    },

    "inventory": {
        "key": "inventory",
        "name": "库存管理",
        "icon": "Box",
        "description": "商品 / 仓库 / 出入库流水 / 供应商",
        "types": [
            {
                "key": "product", "name": "商品", "icon": "Goods",
                "description": "商品主数据",
                "fields": [
                    _text("name", "商品名称", True),
                    _text("sku", "SKU 编码"),
                    _f("category", "分类", "select",
                       options={"choices": ["电子", "耗材", "办公", "其他"]}),
                    _f("spec", "规格", "text"),
                    _f("price", "单价（元）", "number"),
                    _f("stock", "当前库存", "number"),
                    _f("safety_stock", "安全库存", "number"),
                    _f("image", "商品图片", "image"),
                    DESC(),
                ],
            },
            {
                "key": "warehouse", "name": "仓库", "icon": "OfficeBuilding",
                "description": "仓库 / 库位",
                "fields": [
                    _text("name", "仓库名称", True),
                    _f("location", "所在位置", "text"),
                    _text("manager", "管理员"),
                    _f("capacity", "容量", "number"),
                ],
            },
            {
                "key": "stock_move", "name": "出入库单", "icon": "Sort",
                "description": "库存变动流水",
                "fields": [
                    _text("code", "单号", True),
                    _f("product", "商品", "reference", options={"target_ref": "product"}),
                    _f("warehouse", "仓库", "reference", options={"target_ref": "warehouse"}),
                    _f("move_type", "类型", "select", options={"choices": ["入库", "出库", "盘点"]}),
                    _f("qty", "数量", "number"),
                    _f("move_date", "日期", "date"),
                    _text("operator", "经办人"),
                    DESC(),
                ],
            },
            {
                "key": "supplier", "name": "供应商", "icon": "Van",
                "description": "上游供应商",
                "fields": [
                    _text("name", "供应商名称", True),
                    _text("contact", "联系人"),
                    _text("phone", "电话"),
                    _f("lead_time", "供货周期（天）", "number"),
                    DESC(),
                ],
            },
        ],
        "relations": [
            {"key": "product_move", "name": "商品出入库", "source": "product", "target": "stock_move"},
            {"key": "warehouse_move", "name": "仓库流水", "source": "warehouse", "target": "stock_move"},
        ],
    },

    "research": {
        "key": "research",
        "name": "文献管理",
        "icon": "Reading",
        "description": "文献 / 作者 / 阅读笔记，适合论文与调研",
        "types": [
            {
                "key": "paper", "name": "文献", "icon": "Reading",
                "description": "论文 / 报告元数据，可上传 PDF 原件",
                "fields": [
                    _text("title", "标题", True),
                    _text("authors", "作者"),
                    _f("year", "年份", "number"),
                    _f("venue", "期刊/会议", "text"),
                    _f("doi", "DOI", "text"),
                    _f("url", "链接", "text"),
                    _f("keywords", "关键词", "multiselect", options={"choices": []}),
                    _f("rating", "评分", "select", options={"choices": ["1", "2", "3", "4", "5"]}),
                    _f("read_status", "阅读状态", "select",
                       options={"choices": ["待读", "在读", "已读", "精读"]}),
                    _f("pdf", "PDF 原件", "file", help_text="上传后可在数据中心在线翻阅"),
                    _f("abstract", "摘要", "textarea"),
                ],
            },
            {
                "key": "author", "name": "作者", "icon": "Avatar",
                "description": "作者 / 研究团队",
                "fields": [
                    _text("name", "姓名", True),
                    _f("affiliation", "所属机构", "text"),
                    _text("email", "邮箱"),
                    _f("homepage", "主页", "text"),
                    _f("research_field", "研究方向", "text"),
                ],
            },
            {
                "key": "reading_note", "name": "阅读笔记", "icon": "Notebook",
                "description": "对文献的批注与摘录",
                "fields": [
                    _text("title", "标题", True),
                    _f("paper", "对应文献", "reference", options={"target_ref": "paper"}),
                    _f("content", "笔记内容", "textarea",
                       help_text="支持 [[双链]] 关联知识库其他笔记"),
                    _f("tags", "标签", "multiselect", options={"choices": []}),
                ],
            },
        ],
        "relations": [
            {"key": "paper_note", "name": "文献笔记", "source": "paper", "target": "reading_note"},
        ],
    },

    "support": {
        "key": "support",
        "name": "客户支持",
        "icon": "Service",
        "description": "工单 / 客户 / 知识条目",
        "types": [
            {
                "key": "customer", "name": "客户", "icon": "User",
                "description": "报障客户",
                "fields": [
                    _text("name", "客户名称", True),
                    _text("contact", "联系人"),
                    _text("phone", "电话"),
                    _f("level", "服务等级", "select", options={"choices": ["标准", "优先", "VIP"]}),
                ],
            },
            {
                "key": "ticket", "name": "工单", "icon": "Tickets",
                "description": "客户问题工单",
                "fields": [
                    _text("title", "工单标题", True),
                    _f("customer", "客户", "reference", options={"target_ref": "customer"}),
                    _f("priority", "优先级", "select", options={"choices": ["低", "中", "高", "紧急"]}),
                    _f("status", "状态", "select",
                       options={"choices": ["待受理", "处理中", "待确认", "已关闭"]}),
                    _f("channel", "来源", "select",
                       options={"choices": ["电话", "邮件", "在线", "现场"]}),
                    _text("assignee", "处理人"),
                    _f("detail", "问题描述", "textarea"),
                    _f("screenshots", "截图", "image"),
                ],
            },
            {
                "key": "article", "name": "知识条目", "icon": "Notebook",
                "description": "沉淀的解决手册",
                "fields": [
                    _text("title", "标题", True),
                    _f("category", "分类", "select",
                       options={"choices": ["安装部署", "使用问题", "故障排查", "其他"]}),
                    _f("content", "内容", "textarea",
                       help_text="支持 [[双链]]，可与知识库笔记互通"),
                    _f("tags", "标签", "multiselect", options={"choices": []}),
                ],
            },
        ],
        "relations": [
            {"key": "customer_ticket", "name": "客户工单", "source": "customer", "target": "ticket"},
        ],
    },

    "hr": {
        "key": "hr",
        "name": "人事管理",
        "icon": "User",
        "description": "员工 / 部门 / 招聘职位 / 候选人",
        "types": [
            {
                "key": "department", "name": "部门", "icon": "OfficeBuilding",
                "description": "组织架构节点",
                "fields": [
                    _text("name", "部门名称", True),
                    _f("manager", "负责人", "text"),
                    _f("headcount", "编制人数", "number"),
                    DESC(),
                ],
            },
            {
                "key": "employee", "name": "员工", "icon": "Avatar",
                "description": "员工档案",
                "fields": [
                    _text("name", "姓名", True),
                    _text("employee_no", "工号"),
                    _f("department", "所属部门", "reference", options={"target_ref": "department"}),
                    _f("position", "岗位", "text"),
                    _f("hire_date", "入职日期", "date"),
                    _f("status", "状态", "select",
                       options={"choices": ["在职", "试用", "离职", "停薪留职"]}),
                    _text("phone", "手机号"),
                    _f("avatar", "照片", "image"),
                    _f("resume", "简历附件", "file"),
                ],
            },
            {
                "key": "job", "name": "招聘职位", "icon": "Briefcase",
                "description": "在招岗位",
                "fields": [
                    _text("name", "职位名称", True),
                    _f("department", "所属部门", "reference", options={"target_ref": "department"}),
                    _f("headcount", "招聘人数", "number"),
                    _f("status", "状态", "select",
                       options={"choices": ["开放", "暂停", "已关闭"]}),
                    _f("jd", "职位描述", "textarea"),
                ],
            },
            {
                "key": "candidate", "name": "候选人", "icon": "UserFilled",
                "description": "应聘者与进度",
                "fields": [
                    _text("name", "姓名", True),
                    _f("job", "应聘职位", "reference", options={"target_ref": "job"}),
                    _text("phone", "电话"),
                    _f("stage", "阶段", "select",
                       options={"choices": ["简历筛选", "初试", "复试", "offer", "入职", "淘汰"]}),
                    _f("expect_salary", "期望薪资", "number"),
                    _f("resume", "简历", "file"),
                    _f("interview_note", "面试记录", "textarea"),
                ],
            },
        ],
        "relations": [
            {"key": "dept_employee", "name": "部门员工", "source": "department", "target": "employee"},
            {"key": "job_candidate", "name": "职位候选人", "source": "job", "target": "candidate"},
        ],
    },

    "asset": {
        "key": "asset",
        "name": "设备资产管理",
        "icon": "Monitor",
        "description": "设备台账 / 借用归还 / 维修记录",
        "types": [
            {
                "key": "asset", "name": "设备", "icon": "Monitor",
                "description": "设备资产台账",
                "fields": [
                    _text("name", "设备名称", True),
                    _text("asset_no", "资产编号"),
                    _f("category", "类别", "select",
                       options={"choices": ["服务器", "网络设备", "办公设备", "其他"]}),
                    _f("model", "型号", "text"),
                    _f("purchase_date", "采购日期", "date"),
                    _f("price", "采购价格（元）", "number"),
                    _f("status", "状态", "select",
                       options={"choices": ["在用", "闲置", "维修中", "报废"]}),
                    _text("keeper", "保管人"),
                    _f("photo", "设备照片", "image"),
                    _f("manual", "说明书", "file"),
                ],
            },
            {
                "key": "borrow", "name": "借用记录", "icon": "Sort",
                "description": "设备借用与归还",
                "fields": [
                    _f("asset", "设备", "reference", options={"target_ref": "asset"}),
                    _text("borrower", "借用人", True),
                    _f("borrow_date", "借出日期", "date"),
                    _f("return_date", "归还日期", "date"),
                    _f("returned", "已归还", "boolean"),
                    _f("note", "备注", "textarea"),
                ],
            },
            {
                "key": "maintenance", "name": "维修记录", "icon": "Tools",
                "description": "故障与维护",
                "fields": [
                    _f("asset", "设备", "reference", options={"target_ref": "asset"}),
                    _f("fault", "故障描述", "textarea", required=True),
                    _f("report_date", "报修日期", "date"),
                    _f("done_date", "完成日期", "date"),
                    _f("cost", "维修费用（元）", "number"),
                    _text("engineer", "处理人"),
                    _f("finished", "已修复", "boolean"),
                ],
            },
        ],
        "relations": [
            {"key": "asset_borrow", "name": "设备借用", "source": "asset", "target": "borrow"},
            {"key": "asset_maintenance", "name": "设备维修", "source": "asset", "target": "maintenance"},
        ],
    },
}


def list_templates() -> list[dict]:
    """给前端的模板概要（不含字段细节）"""
    out = []
    for t in TEMPLATES.values():
        field_count = sum(len(x["fields"]) for x in t["types"])
        out.append({
            "key": t["key"],
            "name": t["name"],
            "icon": t["icon"],
            "description": t["description"],
            "types": [
                {"key": x["key"], "name": x["name"], "icon": x["icon"],
                 "field_count": len(x["fields"])}
                for x in t["types"]
            ],
            "type_count": len(t["types"]),
            "field_count": field_count,
            "relation_count": len(t["relations"]),
        })
    return out


async def create_app_from_template(db: AsyncSession, payload: dict) -> dict:
    """按模板创建应用；同时创建模型、字段与关联定义"""
    tpl_key = payload.get("template") or "blank"
    tpl = TEMPLATES.get(tpl_key)
    if not tpl:
        raise ValueError(f"未知模板：{tpl_key}")

    app_key = (payload.get("key") or "").strip()
    if not app_key:
        raise ValueError("应用 Key 必填")

    existing = (
        await db.execute(select(App).where(App.key == app_key))
    ).scalar_one_or_none()
    if existing:
        raise ValueError(f"应用 Key「{app_key}」已存在")

    app = App(
        key=app_key,
        name=(payload.get("name") or tpl["name"]).strip(),
        icon=payload.get("icon") or tpl["icon"],
        description=payload.get("description") or tpl["description"],
        order=int(payload.get("order") or 99),
    )
    db.add(app)
    await db.flush()

    keymap: dict[str, int] = {}
    created_types = []
    for i, t in enumerate(tpl["types"]):
        tkey = f"{app_key}_{t['key']}"
        et = EntityType(
            key=tkey, name=t["name"], icon=t["icon"],
            description=t["description"], app=app_key, order=i,
        )
        db.add(et)
        await db.flush()
        for j, f in enumerate(t["fields"]):
            opts = dict(f.get("options") or {})
            ref = opts.pop("target_ref", None)
            if ref:
                opts["target"] = f"{app_key}_{ref}"
            db.add(FieldDefinition(
                entity_type_id=et.id, key=f["key"], name=f["name"],
                type=f["type"], required=bool(f.get("required")),
                options=opts, order=j,
            ))
        keymap[t["key"]] = et.id
        created_types.append({"id": et.id, "key": tkey, "name": t["name"]})

    created_relations = []
    for r in tpl["relations"]:
        if r["source"] not in keymap or r["target"] not in keymap:
            continue
        rd = RelationDef(
            key=f"{app_key}_{r['key']}",
            name=r["name"],
            source_type_id=keymap[r["source"]],
            target_type_id=keymap[r["target"]],
            cardinality=r.get("cardinality", "many-to-many"),
            description=r.get("description", ""),
        )
        db.add(rd)
        created_relations.append(r["name"])

    await db.commit()
    return {
        "ok": True,
        "app": {"id": app.id, "key": app.key, "name": app.name, "icon": app.icon},
        "types": created_types,
        "relations": created_relations,
        "template": tpl_key,
    }
