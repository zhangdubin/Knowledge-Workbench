"""AI 生成应用规格草稿

把一句自然语言需求变成一份「应用 + 数据模型 + 字段 + 关联」的规格草稿。

为什么单独一个服务：
- 草稿的形状必须与 app_template.TEMPLATES 的条目完全一致，
  这样 AI 草稿与内置模板可以共用 app_template.create_app_from_spec 这一条落库路径，
  不会出现「模板一套建表逻辑、AI 另一套」两份实现；
- 草稿只返回给前端展示与编辑，**不落库**。
  AI 不该绕过用户确认直接写库：生成 → 用户审阅改 → 用户点创建。

两条生成路径：
1. 配了大模型：走 ai_svc.chat_real()，提示词要求只回 JSON；
2. 没配大模型（本项目默认就是 mock 模式）：走关键词规则兜底，
   「客户管理」「合同审批」这类描述也能生成像样的模型与字段。
   没有兜底的话，未配 LLM 的部署等于这个功能完全不可用。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import ai as ai_svc
from . import ai_config as cfg_svc
from .model_json import FIELD_TYPES, TYPE_ALIASES, slug_key

logger = logging.getLogger("kb.app_ai")


# ============ 规格的硬约束 ============
# 之所以要设上限：草稿是要给人审阅的，模型/字段太多用户根本看不过来，
# 而且前端一次提交的数据量也不该无上限。
MAX_TYPES = 8
MAX_FIELDS_PER_TYPE = 20
MAX_RELATIONS = 12
MAX_APP_KEY = 32      # EntityType.key 是 64 位，模型 key 还要再拼一段后缀
MAX_TYPE_KEY = 28
MAX_FIELD_KEY = 56
MAX_NAME = 60
MAX_DESC = 400

# 字段类型白名单：直接复用模型 JSON 导入那套（model_json.FIELD_TYPES），
# 避免「AI 能造出前端渲染不出来的字段类型」
ALLOWED_FIELD_TYPES = FIELD_TYPES

# 关联基数白名单
CARDINALITIES = ("one-to-one", "one-to-many", "many-to-one", "many-to-many")

# 图标白名单：应用图标要与前端 utils/icons.js 的 APP_ICON_CHOICES 对齐
# （应用卡片直接用库里的图标渲染，超出这个集合会渲染成空白）；
# 数据模型图标放宽到 Element Plus 全量图标 —— 模型列表其实是按 key 映射图标的，
# 库里存什么只影响模型编辑页。
APP_ICONS = {
    "Grid", "Management", "Notebook", "Coin", "Files", "User", "ShoppingCart",
    "Box", "Money", "TrendCharts", "DataAnalysis", "Connection", "Tickets",
    "Goods", "Avatar", "Histogram", "Briefcase", "SetUp", "Reading", "Service",
    "Monitor", "OfficeBuilding", "Van", "Tools", "Flag", "Collection", "Folder",
    "Document", "Memo", "EditPen", "Star", "Compass", "Aim",
}

# Element Plus 全量图标名（@element-plus/icons-vue）
EP_ICONS = frozenset("""
AddLocation Aim AlarmClock Apple ArrowDown ArrowDownBold ArrowLeft ArrowLeftBold
ArrowRight ArrowRightBold ArrowUp ArrowUpBold Avatar Back Baseball BasketBall Bell
BellFilled Bicycle Bottom BottomLeft BottomRight Bowl Box Briefcase Brush BrushFilled
Burger Calendar Camera CameraFilled CaretBottom CaretLeft CaretRight CaretTop Cellphone
ChatDotRound ChatDotSquare ChatLineRound ChatLineSquare ChatRound ChatSquare Check
Checked Cherry Chicken ChromeFilled CircleCheck CircleCheckFilled CircleClose
CircleCloseFilled CirclePlus CirclePlusFilled Clock Close CloseBold Cloudy Coffee
CoffeeCup Coin ColdDrink Collection CollectionTag Comment Compass Connection
Coordinate CopyDocument Cpu CreditCard Crop DArrowLeft DArrowRight DCaret DataAnalysis
DataBoard DataLine Delete DeleteFilled DeleteLocation Dessert Discount Dish DishDot
Document DocumentAdd DocumentChecked DocumentCopy DocumentDelete DocumentRemove Download
Drizzling Edit EditPen Eleme ElemeFilled ElementPlus Expand Failed Female Files Film
Filter Finished FirstAidKit Flag Fold Folder FolderAdd FolderChecked FolderDelete
FolderOpened FolderRemove Food Football ForkSpoon Fries FullScreen Goblet GobletFull
GobletSquare GobletSquareFull GoldMedal Goods GoodsFilled Grape Grid Guide Handbag
Headset Help HelpFilled Hide Histogram HomeFilled HotWater House IceCream IceCreamRound
IceCreamSquare IceDrink IceTea InfoFilled Iphone Key KnifeFork Lightning Link List
Loading Location LocationFilled LocationInformation Lock Lollipop MagicStick Magnet Male
Management MapLocation Medal Memo Menu Message MessageBox Mic Microphone MilkTea Minus
Money Monitor Moon MoonNight More MoreFilled MostlyCloudy Mouse Mug Mute MuteNotification
NoSmoking Notebook Notification Odometer OfficeBuilding Open Operation Opportunity
Orange Paperclip PartlyCloudy Pear Phone PhoneFilled Picture PictureFilled PictureRounded
PieChart Place Platform Plus Pointer Position Postcard Pouring Present PriceTag Printer
Promotion QuartzWatch QuestionFilled Rank Reading ReadingLamp Refresh RefreshLeft
RefreshRight Refrigerator Remove RemoveFilled Right ScaleToOriginal School Scissor Search
Select Sell SemiSelect Service SetUp Setting Share Ship Shop ShoppingBag ShoppingCart
ShoppingCartFull ShoppingTrolley Smoking Soccer SoldOut Sort SortDown SortUp Stamp Star
StarFilled Stopwatch SuccessFilled Sugar Suitcase SuitcaseLine Sunny Sunrise Sunset
Switch SwitchButton SwitchFilled TakeawayBox Ticket Tickets Timer ToiletPaper Tools Top
TopLeft TopRight TopBottom TrendCharts Trophy TrophyBase TurnOff Umbrella Unlock Upload
UploadFilled User UserFilled Van VideoCamera VideoCameraFilled VideoPause VideoPlay View
Wallet WalletFilled WarnTriangleFilled Warning WarningFilled Watch Watermelon WindPower
ZoomIn ZoomOut
""".split())

# 中文业务名 → 英文 key 兜底：大模型常常直接拿中文当 key，
# 而 key 必须是英文标识；规则引擎与清洗都靠这张表做转写
CN_KEYS = {
    "客户": "customer", "客户信息": "customer", "客户资料": "customer",
    "商机": "opportunity", "机会": "opportunity", "线索": "lead",
    "订单": "order", "订单明细": "order_item", "订单行": "order_item",
    "合同": "contract", "协议": "contract",
    "付款": "payment", "付款计划": "payment", "收款": "payment",
    "项目": "project", "任务": "task", "里程碑": "milestone", "风险": "risk",
    "费用": "expense", "报销": "reimbursement", "报销单": "reimbursement",
    "预算": "budget", "发票": "invoice", "账户": "account", "流水": "transaction",
    "文献": "paper", "论文": "paper", "书籍": "book", "作者": "author",
    "阅读笔记": "reading_note", "笔记": "note",
    "商品": "product", "产品": "product", "仓库": "warehouse",
    "出入库单": "stock_move", "库存": "stock", "供应商": "supplier",
    "部门": "department", "员工": "employee", "职位": "job",
    "候选人": "candidate", "设备": "asset", "借用记录": "borrow",
    "维修记录": "maintenance", "工单": "ticket", "知识条目": "article",
    "会议": "meeting", "会议室": "meeting_room", "议题": "agenda_item",
    "课程": "course", "学员": "student", "考试": "exam",
    "文章": "article", "资讯": "news", "栏目": "category", "分类": "category",
    "活动": "campaign", "渠道": "channel", "采购单": "purchase_order",
    "记录": "record", "附件": "attachment", "日志": "log",
}


# ============ 大模型提示词 ============
# 提示词要点：
# 1. 明确「只返回 JSON」，并给出完整骨架 + 一个例子（大模型最容易照抄例子）；
# 2. 把字段类型白名单写死，避免造出前端不认识的类型；
# 3. 强调 key 用英文、中文只放 name/description；
# 4. 要求 select 给 choices、reference 给 target_ref，
#    这两样缺了字段在录入界面就用不了。
SYSTEM_PROMPT = """你是「知识工作台」的应用设计助手。
用户用一句自然语言描述需求，你要把它拆成可以直接落库的数据模型规格。

只返回一个 JSON 对象，不要任何解释、前言、结语、Markdown 代码块或多余文字。

JSON 结构：
{
  "key": "英文小写唯一标识，如 crm",
  "name": "应用名称",
  "icon": "Element Plus 图标名，如 Grid / User / Files / Money / Box",
  "description": "一句话说明这个应用做什么",
  "types": [
    {
      "key": "英文小写标识，如 customer",
      "name": "模型名称，如 客户",
      "icon": "Element Plus 图标名",
      "description": "这个模型是什么",
      "fields": [
        {"key": "英文小写标识", "name": "字段显示名", "type": "text", "required": true, "help_text": "填写提示"}
      ]
    }
  ],
  "relations": [
    {"key": "英文小写标识", "name": "关联名称", "source": "customer", "target": "opportunity"}
  ]
}

举例（用户说「客户管理」）：
{
  "key": "crm",
  "name": "客户管理",
  "icon": "User",
  "description": "客户主数据与销售跟进",
  "types": [
    {
      "key": "customer", "name": "客户", "icon": "User", "description": "客户主数据",
      "fields": [
        {"key": "name", "name": "客户名称", "type": "text", "required": true},
        {"key": "contact", "name": "联系人", "type": "text"},
        {"key": "level", "name": "客户等级", "type": "select", "options": {"choices": ["A", "B", "C"]}},
        {"key": "phone", "name": "联系电话", "type": "text"},
        {"key": "created_at", "name": "建档日期", "type": "date"},
        {"key": "remark", "name": "备注", "type": "textarea"}
      ]
    }
  ],
  "relations": []
}

硬性要求：
1. 字段 type 只能取：text / textarea / richtext / number / date / datetime / select / multiselect / boolean / file / image / reference。
2. select 与 multiselect 必须给 "options": {"choices": ["甲", "乙"]}；
   reference 必须给 "options": {"target_ref": "目标模型 key"}。
3. 模型 2 到 5 个，每个模型 4 到 10 个字段。
   字段要贴近真实业务（名称、编号、状态、负责人、日期、金额、备注这类），不要只给一个 name。
4. relations 的 source 与 target 必须是 types 里出现过的模型 key。
5. key 一律英文小写加下划线；中文只允许出现在 name / description / help_text 里。
"""


# ============ 小工具 ============

def _as_text(v: Any) -> str:
    """转成干净的一行文本（dict / list 一律当空）"""
    if v is None or isinstance(v, (dict, list)):
        return ""
    return str(v).strip()


def _clip(s: str, n: int) -> str:
    return s[:n]


def _safe_key(raw: Any, fallback: str, *, maxlen: int = MAX_TYPE_KEY) -> str:
    """把任意文本清洗成合法 key：小写字母数字下划线，且以字母开头

    中文名走 CN_KEYS 转写；转写不出来就用 fallback，
    绝不能把中文直接当 key（数据库标识与前端校验都不接受）。
    """
    text = _as_text(raw)
    key = slug_key(text)
    if not key:
        # slug_key 会把中文清空，这里再试一次业务名词表
        key = CN_KEYS.get(text, "")
    key = re.sub(r"[^a-z0-9_]", "", key)
    key = re.sub(r"_{2,}", "_", key).strip("_")
    if not key:
        key = fallback
    if not re.match(r"^[a-z]", key):
        key = f"a_{key}"
    return key[:maxlen]


def _unique_key(base: str, used: set[str]) -> str:
    """同一层级的 key 去重（模型之间、字段之间都要唯一）"""
    key = base
    n = 2
    while key in used:
        key = f"{base}_{n}"
        n += 1
    used.add(key)
    return key


def _extract_json(text: str) -> dict | None:
    """从模型回复里抠出 JSON 对象

    大模型经常在 JSON 外面裹 ```json 代码块，或前后加一句「好的，以下是……」，
    所以不能对整段直接 json.loads。
    """
    if not text:
        return None
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL | re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # 配对扫描大括号：字符串里的括号不能算
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    return None
    return None


def _llm_enabled() -> bool:
    """大模型是否真的可用（没配 Key / 没开开关都算不可用）"""
    cfg = cfg_svc.get_full_config()
    return bool(cfg.get("enabled") and cfg.get("api_key") and cfg.get("base_url"))


# ============ 规则兜底：业务名词 → 模型骨架 ============
# 为什么要有这一整套：本项目默认不配 LLM（mock 模式），
# 只走大模型的话「客户管理」「合同审批」这类描述会完全没法用。
# 规则命中业务名词后按预置骨架拼装模型，字段来自各业务的通用片段。

def _f(key: str, name: str, type_: str, required: bool = False,
       options: dict | None = None) -> dict:
    return {"key": key, "name": name, "type": type_,
            "required": required, "options": options or {}}


def _txt(key: str, name: str, required: bool = False) -> dict:
    return _f(key, name, "text", required)


def _area(key: str, name: str) -> dict:
    return _f(key, name, "textarea")


def _num(key: str, name: str) -> dict:
    return _f(key, name, "number")


def _date(key: str, name: str) -> dict:
    return _f(key, name, "date")


def _dt(key: str, name: str) -> dict:
    return _f(key, name, "datetime")


def _bool(key: str, name: str) -> dict:
    return _f(key, name, "boolean")


def _sel(key: str, name: str, choices: list[str]) -> dict:
    return _f(key, name, "select", options={"choices": list(choices)})


def _ref(key: str, name: str, target: str) -> dict:
    return _f(key, name, "reference", options={"target_ref": target})


def _file(key: str, name: str) -> dict:
    return _f(key, name, "file")


def _m(key: str, name: str, icon: str, desc: str, fields: list[dict]) -> dict:
    return {"key": key, "name": name, "icon": icon, "description": desc, "fields": fields}


def _rel(key: str, name: str, source: str, target: str) -> dict:
    return {"key": key, "name": name, "source": source, "target": target}


# 通用字段片段：命名、编号、状态、负责人、日期、金额、备注
_NAME = lambda n="名称", k="name": _txt(k, n, True)          # noqa: E731
_CODE = lambda n="编号", k="code": _txt(k, n)                # noqa: E731
_OWNER = lambda n="负责人", k="owner": _txt(k, n)            # noqa: E731
_REMARK = lambda n="备注", k="remark": _area(k, n)           # noqa: E731
_DESC = lambda n="说明", k="description": _area(k, n)        # noqa: E731
_AMOUNT = lambda n="金额（元）", k="amount": _num(k, n)      # noqa: E731
_PRIORITY = lambda: _sel("priority", "优先级", ["低", "中", "高", "紧急"])  # noqa: E731


_DOMAINS: list[dict] = [
    {
        "key": "customer", "name": "客户管理", "icon": "User",
        "keywords": ["客户", "crm", "会员", "顾客", "线索", "销售", "获客", "回访"],
        "types": [
            _m("customer", "客户", "User", "客户主数据", [
                _NAME("客户名称"), _txt("contact", "联系人"), _txt("phone", "联系电话"),
                _sel("level", "客户等级", ["A", "B", "C", "D"]),
                _sel("industry", "所属行业", ["制造业", "服务业", "互联网", "其他"]),
                _txt("address", "地址"), _date("signed_at", "合作日期"), _REMARK(),
            ]),
            _m("opportunity", "商机", "TrendCharts", "潜在成交机会", [
                _NAME("商机名称"), _ref("customer", "所属客户", "customer"),
                _sel("stage", "阶段", ["初步接触", "需求确认", "方案报价", "商务谈判", "赢单", "输单"]),
                _AMOUNT("预计金额（元）"), _num("probability", "赢率（%）"),
                _date("expected_close", "预计成交日期"), _OWNER(),
            ]),
            _m("order", "订单", "Tickets", "成交后的订单", [
                _CODE("订单号"), _ref("customer", "客户", "customer"),
                _AMOUNT("订单金额（元）"), _date("sign_date", "签约日期"),
                _sel("status", "状态", ["待付款", "已付款", "已发货", "已完成", "已取消"]),
                _REMARK(),
            ]),
            _m("followup", "跟进记录", "ChatDotRound", "客户跟进流水", [
                _NAME("跟进主题"), _ref("customer", "客户", "customer"),
                _dt("follow_time", "跟进时间"),
                _sel("channel", "跟进方式", ["电话", "拜访", "微信", "邮件", "会议"]),
                _area("content", "跟进内容"), _txt("next_action", "下一步动作"),
            ]),
        ],
        "relations": [
            _rel("customer_opportunity", "客户商机", "customer", "opportunity"),
            _rel("customer_order", "客户订单", "customer", "order"),
        ],
    },
    {
        "key": "contract", "name": "合同管理", "icon": "Files",
        "keywords": ["合同", "协议", "签约", "审批", "法务", "条款", "履约"],
        "types": [
            _m("contract", "合同", "Files", "合同主档，支持上传合同原件", [
                _NAME("合同名称"), _CODE("合同编号"), _txt("counterparty", "相对方"),
                _sel("contract_type", "合同类型", ["销售合同", "采购合同", "服务合同", "框架协议", "保密协议"]),
                _sel("approval_status", "审批状态", ["草拟", "审批中", "已通过", "已驳回"]),
                _AMOUNT("合同金额（元）"), _date("sign_date", "签订日期"),
                _date("start_date", "生效日期"), _date("end_date", "到期日期"),
                _sel("status", "状态", ["草拟", "审批中", "履行中", "已完成", "已终止"]),
                _file("file", "合同原件"), _REMARK(),
            ]),
            _m("payment", "付款计划", "Money", "合同下的收付款节点", [
                _NAME("款项名称"), _ref("contract", "所属合同", "contract"),
                _AMOUNT(), _date("plan_date", "计划日期"),
                _sel("direction", "收/付", ["收款", "付款"]),
                _bool("paid", "已结清"), _date("paid_date", "实际日期"),
            ]),
            _m("vendor", "相对方", "OfficeBuilding", "合作单位 / 供应商主数据", [
                _NAME("单位名称"), _txt("credit_code", "统一社会信用代码"),
                _txt("contact", "联系人"), _txt("phone", "联系电话"),
                _bool("is_supplier", "是供应商"), _bool("is_customer", "是客户"), _REMARK(),
            ]),
        ],
        "relations": [
            _rel("contract_payment", "合同付款计划", "contract", "payment"),
        ],
    },
    {
        "key": "project", "name": "项目管理", "icon": "Management",
        "keywords": ["项目", "立项", "里程碑", "交付", "进度", "工程", "实施"],
        "types": [
            _m("project", "项目", "Briefcase", "一个可交付的项目主体", [
                _NAME("项目名称"), _CODE("项目编号"),
                _sel("status", "状态", ["未开始", "进行中", "已完成", "已暂停"]),
                _OWNER(), _PRIORITY(), _num("budget", "预算（元）"),
                _date("start_date", "开始日期"), _date("end_date", "计划完成"), _DESC(),
            ]),
            _m("task", "任务", "List", "项目下的具体工作项", [
                _NAME("任务名称"), _ref("project", "所属项目", "project"),
                _sel("status", "状态", ["未开始", "进行中", "已完成", "已暂停"]),
                _OWNER(), _PRIORITY(), _date("due_date", "截止日期"),
                _num("progress", "进度（%）"), _DESC(),
            ]),
            _m("milestone", "里程碑", "Flag", "项目关键节点", [
                _NAME("里程碑名称"), _ref("project", "所属项目", "project"),
                _date("due_date", "目标日期"), _bool("done", "是否达成"), _DESC(),
            ]),
            _m("risk", "风险", "Warning", "项目风险登记册", [
                _NAME("风险描述"), _ref("project", "所属项目", "project"),
                _sel("level", "等级", ["低", "中", "高"]), _area("strategy", "应对措施"),
                _bool("closed", "已关闭"),
            ]),
        ],
        "relations": [
            _rel("project_task", "项目包含任务", "project", "task"),
            _rel("project_milestone", "项目里程碑", "project", "milestone"),
            _rel("project_risk", "项目风险", "project", "risk"),
        ],
    },
    {
        "key": "task", "name": "任务管理", "icon": "List",
        "keywords": ["任务", "待办", "事项", "工作计划", "个人事务"],
        "types": [
            _m("task", "任务", "List", "待办与任务清单", [
                _NAME("任务名称"), _CODE("任务编号"),
                _sel("status", "状态", ["未开始", "进行中", "已完成", "已暂停"]),
                _OWNER(), _PRIORITY(), _date("due_date", "截止日期"), _DESC(),
            ]),
            _m("task_category", "任务分类", "Collection", "任务分组", [
                _NAME("分类名称"), _txt("owner", "负责人"), _DESC(),
            ]),
        ],
        "relations": [
            _rel("category_task", "分类任务", "task_category", "task"),
        ],
    },
    {
        "key": "order", "name": "订单管理", "icon": "Tickets",
        "keywords": ["订单", "订货", "销售单", "发货", "收货"],
        "types": [
            _m("order", "订单", "Tickets", "订单主档", [
                _CODE("订单号"), _txt("customer_name", "客户名称"),
                _AMOUNT("订单金额（元）"), _date("order_date", "下单日期"),
                _sel("status", "状态", ["待付款", "已付款", "已发货", "已完成", "已取消"]),
                _OWNER(), _REMARK(),
            ]),
            _m("order_item", "订单明细", "Goods", "订单里的商品行", [
                _NAME("商品名称"), _num("qty", "数量"), _num("price", "单价（元）"),
                _num("amount", "小计（元）"), _REMARK(),
            ]),
        ],
        "relations": [
            _rel("order_item", "订单包含明细", "order", "order_item"),
        ],
    },
    {
        "key": "expense", "name": "费用管理", "icon": "Money",
        "keywords": ["费用", "报销", "预算", "发票", "财务", "开支", "成本", "记账"],
        "types": [
            _m("expense", "费用记录", "Money", "每一笔费用支出", [
                _NAME("费用名称"), _sel("category", "费用类别", ["差旅", "招待", "办公", "采购", "其他"]),
                _AMOUNT("金额（元）"), _date("expense_date", "发生日期"),
                _sel("status", "状态", ["待提交", "审批中", "已通过", "已驳回"]),
                _OWNER(), _file("invoice", "发票附件"), _REMARK(),
            ]),
            _m("reimbursement", "报销单", "Tickets", "一次报销申请", [
                _CODE("报销单号"), _txt("applicant", "报销人"),
                _AMOUNT("报销金额（元）"), _date("apply_date", "申请日期"),
                _sel("status", "状态", ["草稿", "审批中", "已通过", "已驳回"]),
                _OWNER("审批人"), _DESC(),
            ]),
            _m("budget", "预算", "Histogram", "科目预算额度", [
                _NAME("预算名称"), _txt("subject", "预算科目"),
                _AMOUNT("预算金额（元）"), _num("used", "已使用（元）"),
                _date("period", "预算周期"), _REMARK(),
            ]),
        ],
        "relations": [
            _rel("reimbursement_expense", "报销包含费用", "reimbursement", "expense"),
        ],
    },
    {
        "key": "paper", "name": "文献管理", "icon": "Reading",
        "keywords": ["文献", "论文", "书籍", "期刊", "阅读", "读书", "资料库", "研究"],
        "types": [
            _m("paper", "文献", "Reading", "论文 / 报告元数据", [
                _txt("title", "标题", True), _txt("authors", "作者"),
                _num("year", "年份"), _txt("venue", "期刊/会议"),
                _txt("doi", "DOI"), _txt("url", "链接"),
                _sel("read_status", "阅读状态", ["待读", "在读", "已读", "精读"]),
                _num("rating", "评分"), _file("pdf", "PDF 原件"), _area("abstract", "摘要"),
            ]),
            _m("author", "作者", "Avatar", "作者 / 研究团队", [
                _NAME("姓名"), _txt("affiliation", "所属机构"),
                _txt("email", "邮箱"), _txt("homepage", "主页"),
                _txt("research_field", "研究方向"),
            ]),
            _m("reading_note", "阅读笔记", "Notebook", "对文献的批注与摘录", [
                _NAME("标题"), _ref("paper", "对应文献", "paper"),
                _area("content", "笔记内容"), _REMARK("我的评价"),
            ]),
        ],
        "relations": [
            _rel("paper_note", "文献笔记", "paper", "reading_note"),
        ],
    },
    {
        "key": "product", "name": "库存管理", "icon": "Box",
        "keywords": ["商品", "库存", "仓库", "进货", "出库", "存货", "盘点", "货架"],
        "types": [
            _m("product", "商品", "Goods", "商品主数据", [
                _NAME("商品名称"), _txt("sku", "SKU 编码"),
                _sel("category", "分类", ["电子", "耗材", "办公", "其他"]),
                _txt("spec", "规格"), _num("price", "单价（元）"),
                _num("stock", "当前库存"), _num("safety_stock", "安全库存"), _REMARK(),
            ]),
            _m("warehouse", "仓库", "OfficeBuilding", "仓库 / 库位", [
                _NAME("仓库名称"), _txt("location", "所在位置"),
                _txt("manager", "管理员"), _num("capacity", "容量"),
            ]),
            _m("stock_move", "出入库单", "Sort", "库存变动流水", [
                _CODE("单号"), _ref("product", "商品", "product"),
                _ref("warehouse", "仓库", "warehouse"),
                _sel("move_type", "类型", ["入库", "出库", "盘点"]),
                _num("qty", "数量"), _date("move_date", "日期"),
                _txt("operator", "经办人"),
            ]),
            _m("supplier", "供应商", "Van", "上游供应商", [
                _NAME("供应商名称"), _txt("contact", "联系人"),
                _txt("phone", "电话"), _num("lead_time", "供货周期（天）"), _REMARK(),
            ]),
        ],
        "relations": [
            _rel("product_move", "商品出入库", "product", "stock_move"),
            _rel("warehouse_move", "仓库流水", "warehouse", "stock_move"),
        ],
    },
    {
        "key": "hr", "name": "人事管理", "icon": "User",
        "keywords": ["员工", "人事", "招聘", "部门", "考勤", "离职", "薪酬", "候选人", "岗位"],
        "types": [
            _m("department", "部门", "OfficeBuilding", "组织架构节点", [
                _NAME("部门名称"), _txt("manager", "负责人"),
                _num("headcount", "编制人数"), _DESC(),
            ]),
            _m("employee", "员工", "Avatar", "员工档案", [
                _NAME("姓名"), _txt("employee_no", "工号"),
                _ref("department", "所属部门", "department"),
                _txt("position", "岗位"), _date("hire_date", "入职日期"),
                _sel("status", "状态", ["在职", "试用", "离职", "停薪留职"]),
                _txt("phone", "手机号"), _file("resume", "简历附件"),
            ]),
            _m("job", "招聘职位", "Briefcase", "在招岗位", [
                _NAME("职位名称"), _ref("department", "所属部门", "department"),
                _num("headcount", "招聘人数"),
                _sel("status", "状态", ["开放", "暂停", "已关闭"]),
                _area("jd", "职位描述"),
            ]),
            _m("candidate", "候选人", "UserFilled", "应聘者与进度", [
                _NAME("姓名"), _ref("job", "应聘职位", "job"),
                _txt("phone", "电话"),
                _sel("stage", "阶段", ["简历筛选", "初试", "复试", "offer", "入职", "淘汰"]),
                _num("expect_salary", "期望薪资"), _file("resume", "简历"),
            ]),
        ],
        "relations": [
            _rel("dept_employee", "部门员工", "department", "employee"),
            _rel("job_candidate", "职位候选人", "job", "candidate"),
        ],
    },
    {
        "key": "asset", "name": "设备资产管理", "icon": "Monitor",
        "keywords": ["设备", "资产", "借用", "维修", "固定资产", "机器", "仪器"],
        "types": [
            _m("asset", "设备", "Monitor", "设备资产台账", [
                _NAME("设备名称"), _txt("asset_no", "资产编号"),
                _sel("category", "类别", ["服务器", "网络设备", "办公设备", "其他"]),
                _txt("model", "型号"), _date("purchase_date", "采购日期"),
                _num("price", "采购价格（元）"),
                _sel("status", "状态", ["在用", "闲置", "维修中", "报废"]),
                _txt("keeper", "保管人"), _file("manual", "说明书"),
            ]),
            _m("borrow", "借用记录", "Sort", "设备借用与归还", [
                _ref("asset", "设备", "asset"), _txt("borrower", "借用人", True),
                _date("borrow_date", "借出日期"), _date("return_date", "归还日期"),
                _bool("returned", "已归还"), _REMARK("备注"),
            ]),
            _m("maintenance", "维修记录", "Tools", "故障与维护", [
                _ref("asset", "设备", "asset"), _f("fault", "故障描述", "textarea", True),
                _date("report_date", "报修日期"), _date("done_date", "完成日期"),
                _num("cost", "维修费用（元）"), _txt("engineer", "处理人"),
                _bool("finished", "已修复"),
            ]),
        ],
        "relations": [
            _rel("asset_borrow", "设备借用", "asset", "borrow"),
            _rel("asset_maintenance", "设备维修", "asset", "maintenance"),
        ],
    },
    {
        "key": "support", "name": "客户支持", "icon": "Service",
        "keywords": ["工单", "客服", "售后", "服务", "报障", "问题反馈", "投诉", "工单系统"],
        "types": [
            _m("customer", "客户", "User", "报障客户", [
                _NAME("客户名称"), _txt("contact", "联系人"),
                _txt("phone", "电话"),
                _sel("level", "服务等级", ["标准", "优先", "VIP"]),
            ]),
            _m("ticket", "工单", "Tickets", "客户问题工单", [
                _NAME("工单标题"), _ref("customer", "客户", "customer"),
                _sel("priority", "优先级", ["低", "中", "高", "紧急"]),
                _sel("status", "状态", ["待受理", "处理中", "待确认", "已关闭"]),
                _sel("channel", "来源", ["电话", "邮件", "在线", "现场"]),
                _txt("assignee", "处理人"), _area("detail", "问题描述"),
            ]),
            _m("article", "知识条目", "Notebook", "沉淀的解决手册", [
                _NAME("标题"), _sel("category", "分类", ["安装部署", "使用问题", "故障排查", "其他"]),
                _area("content", "内容"), _REMARK(),
            ]),
        ],
        "relations": [
            _rel("customer_ticket", "客户工单", "customer", "ticket"),
        ],
    },
    {
        "key": "meeting", "name": "会议管理", "icon": "Collection",
        "keywords": ["会议", "日程", "行程", "例会", "周会", "会议室", "安排"],
        "types": [
            _m("meeting", "会议", "Collection", "会议安排与纪要", [
                _NAME("会议主题"), _dt("start_time", "开始时间"),
                _dt("end_time", "结束时间"), _txt("host", "主持人"),
                _sel("status", "状态", ["未开始", "进行中", "已结束", "已取消"]),
                _area("content", "会议纪要"),
            ]),
            _m("meeting_room", "会议室", "OfficeBuilding", "会议场地", [
                _NAME("会议室名称"), _num("capacity", "容纳人数"),
                _txt("location", "位置"), _bool("available", "可用"),
            ]),
            _m("agenda_item", "议题", "List", "会议议题", [
                _NAME("议题"), _ref("meeting", "所属会议", "meeting"),
                _txt("owner", "汇报人"), _num("duration", "时长（分钟）"),
            ]),
        ],
        "relations": [
            _rel("meeting_agenda", "会议议题", "meeting", "agenda_item"),
            _rel("room_meeting", "会议室会议", "meeting_room", "meeting"),
        ],
    },
    {
        "key": "course", "name": "学习管理", "icon": "Reading",
        "keywords": ["课程", "学习", "考试", "学员", "培训", "题库", "成绩"],
        "types": [
            _m("course", "课程", "Notebook", "课程与安排", [
                _NAME("课程名称"), _txt("teacher", "授课教师"),
                _num("hours", "课时"), _num("credit", "学分"),
                _sel("status", "状态", ["未开课", "进行中", "已结课"]), _DESC(),
            ]),
            _m("student", "学员", "Avatar", "学习者", [
                _NAME("姓名"), _txt("student_no", "学号"),
                _txt("department", "部门"), _txt("email", "邮箱"),
            ]),
            _m("exam", "考试", "Tickets", "考试与成绩", [
                _NAME("考试名称"), _ref("course", "所属课程", "course"),
                _ref("student", "考生", "student"),
                _num("score", "成绩"), _date("exam_date", "考试日期"),
            ]),
        ],
        "relations": [
            _rel("course_exam", "课程考试", "course", "exam"),
        ],
    },
    {
        "key": "content", "name": "内容管理", "icon": "Memo",
        "keywords": ["文章", "资讯", "博客", "内容", "公众号", "推文", "稿件", "发布"],
        "types": [
            _m("article", "文章", "Memo", "内容稿件", [
                _NAME("标题"), _sel("column", "所属栏目", ["产品动态", "行业观察", "案例", "其他"]),
                _txt("author", "作者"), _dt("publish_time", "发布时间"),
                _sel("status", "状态", ["草稿", "待审", "已发布", "已下线"]), _area("summary", "摘要"),
            ]),
            _m("column", "栏目", "Collection", "内容栏目", [
                _NAME("栏目名称"), _txt("owner", "负责人"), _DESC(),
            ]),
        ],
        "relations": [
            _rel("column_article", "栏目文章", "column", "article"),
        ],
    },
    {
        "key": "purchase", "name": "采购管理", "icon": "Van",
        "keywords": ["采购", "供应商", "招标", "比价", "询价", "求购", "进货单"],
        "types": [
            _m("purchase_order", "采购单", "Tickets", "采购申请与订单", [
                _CODE("采购单号"), _ref("supplier", "供应商", "supplier"),
                _AMOUNT("采购金额（元）"), _date("order_date", "采购日期"),
                _sel("status", "状态", ["待审批", "审批中", "已下单", "已入库", "已取消"]),
                _OWNER("采购员"), _DESC(),
            ]),
            _m("supplier", "供应商", "Van", "上游供应商", [
                _NAME("供应商名称"), _txt("contact", "联系人"),
                _txt("phone", "电话"), _num("lead_time", "供货周期（天）"),
                _sel("level", "供应商等级", ["A", "B", "C"]), _REMARK(),
            ]),
            _m("quote", "询价比价", "Document", "供应商报价记录", [
                _NAME("报价主题"), _ref("supplier", "供应商", "supplier"),
                _AMOUNT("报价金额（元）"), _date("quote_date", "报价日期"),
                _sel("result", "比价结果", ["采用", "待定", "未采用"]),
            ]),
        ],
        "relations": [
            _rel("supplier_purchase", "供应商采购单", "supplier", "purchase_order"),
            _rel("supplier_quote", "供应商报价", "supplier", "quote"),
        ],
    },
]


# 去掉描述里的常见口语前缀：用户说「我要做一个客户管理工具」，
# 应用名取「客户管理」比取整句通顺得多
_NAME_JUNK = (
    "我想做一个", "我要做一个", "我需要做一个", "帮我做一个", "帮我建一个",
    "帮我创建", "我想管理", "我要管理", "我需要管理", "做一个", "建一个",
    "创建", "新建", "管理", "我要", "我想", "我需要", "帮我", "请",
)


def _clean_app_name(text: str) -> str:
    """从用户描述里挑一个像应用名的短句"""
    s = _as_text(text)
    for junk in _NAME_JUNK:
        if s.startswith(junk):
            s = s[len(junk):]
            break
    s = s.strip("的 　")
    for sep in ("。", "，", ",", "、", "；", ";", "！", "!", "？", "?"):
        if sep in s:
            s = s.split(sep)[0]
            break
    return _clip(s.strip(), 20)


def _match_domains(prompt: str) -> list[dict]:
    """按业务名词命中预置骨架（命中多个时按命中强度排序）"""
    text = (prompt or "").lower()
    hits: list[tuple[int, dict]] = []
    for d in _DOMAINS:
        score = 0
        for kw in d["keywords"]:
            if kw.lower() in text:
                score += 1
        if score:
            hits.append((score, d))
    # 命中多的排前面；命中数相同时保持预置顺序（预置顺序本身就是常见度）
    hits.sort(key=lambda x: -x[0])
    return [d for _, d in hits]


def _generic_spec(prompt: str) -> dict:
    """没命中任何业务名词时的通用骨架

    给一个能用的「记录」模型：名称、编号、状态、负责人、日期、金额、备注，
    用户确认后还能继续加字段 —— 总比只报错强。
    """
    name = _clean_app_name(prompt) or "AI 生成应用"
    return {
        "key": "ai_app",
        "name": name,
        "icon": "Grid",
        "description": f"根据「{_clip(_as_text(prompt), 60)}」生成的通用模型，可在创建后继续增删字段。",
        "types": [_m("record", "业务记录", "Document", "通用业务记录", [
            _NAME("名称"), _CODE("编号"),
            _sel("status", "状态", ["未开始", "进行中", "已完成", "已暂停"]),
            _OWNER(), _date("record_date", "日期"),
            _AMOUNT(), _REMARK(),
        ])],
        "relations": [],
    }


def _rule_spec(prompt: str) -> dict:
    """规则兜底：把命中的业务骨架拼成一份规格"""
    domains = _match_domains(prompt)
    if not domains:
        return _generic_spec(prompt)

    types: list[dict] = []
    type_keys: set[str] = set()
    relations: list[dict] = []
    rel_keys: set[str] = set()
    for d in domains:
        for t in d["types"]:
            if t["key"] in type_keys:
                continue          # 多个业务同时命中时同名模型只保留一份
            type_keys.add(t["key"])
            types.append(t)
            if len(types) >= MAX_TYPES:
                break
        for r in d["relations"]:
            if r["key"] in rel_keys:
                continue
            rel_keys.add(r["key"])
            relations.append(r)

    names = [d["name"] for d in domains[:2]]
    app_name = names[0] if len(names) == 1 else "、".join(names)
    type_names = "、".join(t["name"] for t in types[:5])
    return {
        "key": domains[0]["key"],
        "name": app_name,
        "icon": domains[0]["icon"],
        "description": f"{type_names}（按描述中的业务关键词自动生成，可在确认前继续调整）",
        "types": types,
        "relations": relations,
    }


# ============ 规格清洗 ============

def _norm_field(raw: Any, idx: int, used: set[str],
                ref_aliases: dict[str, str], warnings: list[str]) -> dict | None:
    """清洗单个字段：类型归一 + 补缺省值 + 剔除多余键"""
    if isinstance(raw, str):
        raw = {"name": raw, "type": "text"}
    if not isinstance(raw, dict):
        warnings.append(f"第 {idx + 1} 个字段不是对象，已忽略")
        return None

    name = _as_text(raw.get("name") or raw.get("label") or raw.get("title"))
    key = _safe_key(raw.get("key") or name, f"field_{idx + 1}", maxlen=MAX_FIELD_KEY)
    base = key
    key = _unique_key(key, used)
    if key != base:
        warnings.append(f"字段 key「{base}」重复，已改为「{key}」")
    if not name:
        name = key
        warnings.append(f"字段「{key}」没有名称，已用 key 代替")

    # 类型：只认白名单，别名归一（复用模型 JSON 导入那套别名表）
    raw_type = _as_text(raw.get("type")).lower()
    if raw_type in TYPE_ALIASES:
        ftype = TYPE_ALIASES[raw_type]
    elif raw_type in ALLOWED_FIELD_TYPES:
        ftype = raw_type
    else:
        warnings.append(f"字段「{name}」的类型「{raw.get('type')}」无法识别，已按单行文本处理")
        ftype = "text"

    options = raw.get("options")
    options = dict(options) if isinstance(options, dict) else {}
    if "choices" not in options and raw.get("choices") is not None:
        options["choices"] = raw.get("choices")

    clean_options: dict = {}
    if ftype in ("select", "multiselect"):
        choices = options.get("choices")
        if not isinstance(choices, list):
            choices = []
        choices = [_as_text(c) for c in choices]
        choices = [c for c in choices if c]
        if not choices:
            warnings.append(f"字段「{name}」是选择类型但没有选项，已置为空选项")
        clean_options["choices"] = choices
    elif ftype == "reference":
        target = _as_text(options.get("target_ref") or options.get("target"))
        resolved = ref_aliases.get(target)
        if resolved:
            clean_options["target_ref"] = resolved
        else:
            warnings.append(
                f"字段「{name}」引用的目标模型「{target or '空'}」不存在，已按单行文本处理"
            )
            ftype = "text"
    else:
        for k, v in options.items():
            if k not in ("choices", "target", "target_ref"):
                clean_options[k] = v

    required = raw.get("required")
    if isinstance(required, str):
        required = required.strip().lower() in ("1", "true", "yes", "y", "是", "必填")
    else:
        required = bool(required)

    field = {
        "key": key,
        "name": _clip(name, MAX_NAME),
        "type": ftype,
        "required": required,
        "options": clean_options,
    }
    help_text = _as_text(raw.get("help_text") or raw.get("hint"))
    if help_text:
        field["help_text"] = _clip(help_text, 120)
    return field


def normalize_spec(raw: Any, *, ensure_ref_fields: bool = False) -> dict:
    """把任意来源的规格清洗成可直接建库的标准形状

    做什么：
    1. 只保留白名单内的字段类型（并把「金额」「string」之类的别名归一）；
    2. 补齐缺省值（key / name / required / options / 图标），剔除多余键；
    3. 引用字段与关联的两端必须真实存在，否则降级或丢弃 ——
       建库时这些键会拼成外键，指向不存在的模型会在录入时才炸；
    4. ensure_ref_fields=True 时给每条关联补一个引用字段，
       让「关联」在录入界面里能选到对方（模板自带引用字段，不受影响）。
    """
    warnings: list[str] = []
    if not isinstance(raw, dict):
        raw = {}

    # ---- 应用层 ----
    name = _as_text(raw.get("name") or raw.get("title"))
    key = _safe_key(raw.get("key") or name, "ai_app", maxlen=MAX_APP_KEY)
    icon = _as_text(raw.get("icon"))
    if icon not in APP_ICONS:
        icon = "Grid"
    description = _clip(_as_text(raw.get("description")), MAX_DESC)

    # ---- 模型层 ----
    types_raw = raw.get("types")
    if not isinstance(types_raw, list):
        types_raw = raw.get("models") if isinstance(raw.get("models"), list) else []

    # 第一遍：先把模型 key 定下来 —— 引用字段与关联都要指向这些 key，
    # 先定 key 再定字段，才知道引用是否有效
    raw_types: list[tuple[dict, str]] = []
    used_type_keys: set[str] = set()
    ref_aliases: dict[str, str] = {}
    for i, t in enumerate(types_raw):
        if not isinstance(t, dict):
            warnings.append(f"第 {i + 1} 个模型不是对象，已忽略")
            continue
        base = _safe_key(t.get("key") or t.get("name"), f"model_{i + 1}", maxlen=MAX_TYPE_KEY)
        tk = _unique_key(base, used_type_keys)
        if tk != base:
            warnings.append(f"模型 key「{base}」重复，已改为「{tk}」")
        ref_aliases.setdefault(tk, tk)
        raw_name = _as_text(t.get("name"))
        if raw_name:
            ref_aliases.setdefault(raw_name, tk)
        cn = CN_KEYS.get(raw_name)
        if cn:
            ref_aliases.setdefault(cn, tk)
        raw_types.append((t, tk))
        if len(raw_types) >= MAX_TYPES:
            warnings.append(f"模型过多，只保留前 {MAX_TYPES} 个")
            break

    # 第二遍：清洗字段
    types: list[dict] = []
    for t, tk in raw_types:
        fields_raw = t.get("fields")
        if not isinstance(fields_raw, list):
            fields_raw = []
        used_field_keys: set[str] = set()
        fields: list[dict] = []
        for i, f in enumerate(fields_raw):
            nf = _norm_field(f, i, used_field_keys, ref_aliases, warnings)
            if nf:
                fields.append(nf)
            if len(fields) >= MAX_FIELDS_PER_TYPE:
                warnings.append(f"模型「{tk}」的字段过多，只保留前 {MAX_FIELDS_PER_TYPE} 个")
                break
        t_icon = _as_text(t.get("icon"))
        if t_icon not in EP_ICONS:
            t_icon = "Grid"
        types.append({
            "key": tk,
            "name": _clip(_as_text(t.get("name")) or tk, MAX_NAME),
            "icon": t_icon,
            "description": _clip(_as_text(t.get("description")), MAX_DESC),
            "fields": fields,
        })

    type_by_key = {t["key"]: t for t in types}

    # ---- 关联层 ----
    relations_raw = raw.get("relations")
    if not isinstance(relations_raw, list):
        relations_raw = []
    relations: list[dict] = []
    used_rel_keys: set[str] = set()
    for i, r in enumerate(relations_raw):
        if not isinstance(r, dict):
            continue
        source = ref_aliases.get(_as_text(r.get("source")))
        target = ref_aliases.get(_as_text(r.get("target")))
        if not source or not target or source == target:
            warnings.append(f"第 {i + 1} 条关联的两端模型不存在或相同，已忽略")
            continue
        base = _safe_key(r.get("key") or f"{source}_{target}", f"rel_{i + 1}", maxlen=40)
        rk = _unique_key(base, used_rel_keys)
        if rk != base:
            warnings.append(f"关联 key「{base}」重复，已改为「{rk}」")
        card = _as_text(r.get("cardinality")) or "many-to-many"
        if card not in CARDINALITIES:
            card = "many-to-many"
        rel = {
            "key": rk,
            "name": _clip(_as_text(r.get("name"))
                         or f"{type_by_key[source]['name']} - {type_by_key[target]['name']}",
                         MAX_NAME),
            "source": source,
            "target": target,
            "cardinality": card,
        }
        desc = _as_text(r.get("description"))
        if desc:
            rel["description"] = _clip(desc, MAX_DESC)
        relations.append(rel)
        if len(relations) >= MAX_RELATIONS:
            warnings.append(f"关联过多，只保留前 {MAX_RELATIONS} 条")
            break

    # ---- 关联 ↔ 引用字段 ----
    # 关联定义只是元数据，真正能在录入界面里选到对方的是「引用字段」。
    # AI 草稿里模型字段是模型自己列的，不一定带引用字段，这里补齐。
    if ensure_ref_fields:
        for rel in relations:
            t = type_by_key.get(rel["target"])
            if t is None:
                continue
            has_ref = any(
                f.get("type") == "reference"
                and (f.get("options") or {}).get("target_ref") == rel["source"]
                for f in t["fields"]
            )
            if has_ref:
                continue
            used = {f["key"] for f in t["fields"]}
            fkey = rel["source"]
            if fkey in used:
                fkey = f"{rel['source']}_ref"
            fkey = _unique_key(fkey, used)
            t["fields"].append({
                "key": fkey,
                "name": f"关联{type_by_key[rel['source']]['name']}",
                "type": "reference",
                "required": False,
                "options": {"target_ref": rel["source"]},
            })

    return {
        "key": key,
        "name": _clip(name or key, MAX_NAME),
        "icon": icon,
        "description": description,
        "types": types,
        "relations": relations,
        "warnings": warnings,
    }


# ============ 对外入口 ============

async def generate_app_spec(prompt: str) -> dict:
    """一句自然语言 → 应用规格草稿（不落库）

    返回结构与前端审阅界面一一对应：
    key / name / icon / description / types[].fields[] / relations[]，
    外加 source（llm / rules）与 notice（给用户看的人话提示）。
    """
    prompt = _as_text(prompt)
    if not prompt:
        raise ValueError("请先描述你要的应用")
    if len(prompt) > 500:
        prompt = prompt[:500]

    source = "rules"
    notice = ""
    raw: dict | None = None

    if _llm_enabled():
        try:
            text = await ai_svc.chat_real([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ])
            if isinstance(text, str):
                raw = _extract_json(text)
        except Exception as e:
            # 大模型挂掉不该让整个功能不可用，退回规则即可
            logger.warning("AI 生成应用规格失败，退回关键词规则：%s", e)
        if raw:
            source = "llm"
        else:
            notice = "大模型返回的内容无法解析成规格，已按描述里的业务关键词生成草稿，请确认后再创建。"
    else:
        notice = "当前未配置大模型（本地规则模式），已按描述里的业务关键词生成草稿，可继续手动调整。"

    if raw is None:
        raw = _rule_spec(prompt)

    # 引用字段一定要补齐：关联只是元数据，
    # 没有引用字段的话关联在录入界面里用不了
    spec = normalize_spec(raw, ensure_ref_fields=True)
    if not spec["types"]:
        # 大模型给了一份空壳（解析成功但没有模型），还是用规则兜底
        spec = normalize_spec(_rule_spec(prompt), ensure_ref_fields=True)
        source = "rules"
        notice = notice or "大模型没有给出可用的模型，已按业务关键词生成草稿。"

    return {
        "key": spec["key"],
        "name": spec["name"],
        "icon": spec["icon"],
        "description": spec["description"],
        "types": spec["types"],
        "relations": spec["relations"],
        "source": source,
        "notice": notice,
        "warnings": spec.get("warnings") or [],
    }
