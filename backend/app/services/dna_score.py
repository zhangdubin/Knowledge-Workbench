"""基因评分：表达度与置信度 —— 让「这条知识有多好」变成看得见的分项

旧版只有两个裸数字，而且两个都答不上「为什么」：

    confidence  抽取时按启发式拍的一个常数（0.6 / 0.75 / 0.85 …），
                之后再吸收同一条知识只会取 max()，永远只涨不跌；
    usage_count 被检索/引用过几次，跟知识本身的质量毫无关系，
                却顶着「表达度」这个名字。

这一版把两个数字拆成**可解释的分项**：

    表达度（expressiveness）——「这条基因说清楚了没有」
        具体度   描述里有没有可辨认的锚点（标识符/路径/版本/数字）
        可执行性 有没有触发条件、步骤、边界、产出这四要素
        可检索性 标题够不够有区分度、标签齐不齐、正文能不能被命中
        被复用度 真的被人用过没有（用过几次、复用后成功率如何）

    置信度（confidence）——「这条基因有多可信」
        来源权威度 这条知识是从哪来的（源码实证 > 官方文档 > 开源参考 > 手贴）
        交叉验证   有几个**不同来源**说过同一件事
        复用成功率 真的拿去用之后，成功了几次
        时效性     依赖的版本/接口是不是已经过期

两个原则，贯穿整个模块：

1. **黑盒不出数**。任何一个分数都必须能展开成分项与依据，
   界面上要能回答「为什么这条只有 0.42」。

2. **增量更新**。评分只依赖这条基因自己的状态（内容、来源、计数器），
   所以新增/使用/纠正时只重算**这一条**，不做全量重算。
   全量重算只在回填脚本里出现（scripts/dna_rescore.py）。

分数镜像回 dna_gene.confidence / dna_gene.expressiveness 两列，
是为了让已有的排序、筛选代码不用改 —— 权威值在 dna_gene_score 表里，
分项与依据都在那儿。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DnaGene, DnaGeneScore

log = __import__("logging").getLogger("kb.dna_score")

# 评分模型版本：改权重或改口径时 +1。
# 存在 dna_gene_score.score_version 里，回填脚本只重算版本落后的行。
SCORE_VERSION = 2

# ---------- 表达度分项 ----------
EXPRESS_SPECIFICITY = "specificity"
EXPRESS_ACTIONABILITY = "actionability"
EXPRESS_RETRIEVABILITY = "retrievability"
EXPRESS_REUSE = "reuse"

# 权重之和必须为 1（回填脚本会校验）
EXPRESS_WEIGHTS = {
    EXPRESS_SPECIFICITY: 0.25,
    EXPRESS_ACTIONABILITY: 0.30,
    EXPRESS_RETRIEVABILITY: 0.20,
    EXPRESS_REUSE: 0.25,
}

# ---------- 置信度分项 ----------
CONF_AUTHORITY = "authority"
CONF_CORROBORATION = "corroboration"
CONF_USAGE_SUCCESS = "usage_success"
CONF_FRESHNESS = "freshness"

CONF_WEIGHTS = {
    CONF_AUTHORITY: 0.25,
    CONF_CORROBORATION: 0.25,
    CONF_USAGE_SUCCESS: 0.25,
    CONF_FRESHNESS: 0.25,
}

# 扣分上限：惩罚可以叠加，但不能把一条知识打到 0 以下
MAX_CORRECTION_PENALTY = 0.40
MAX_FAILURE_PENALTY = 0.25
CORRECTION_PENALTY = 0.12
FAILURE_PENALTY = 0.05

# 没有被用过 ≠ 不可信：没记录时给中性分，别让「冷基因」一律低置信
NEUTRAL_USAGE_SUCCESS = 0.50
# 没有第二个来源印证 ≠ 不可信：基线给一点点，别让所有新知识都低置信
BASE_CORROBORATION = 0.15

# 来源权威度基线。
# 为什么这么排：源码实证 > 文档 > 记录 > 手工粘贴。
# 外部开源仓库（openkb）排得比较靠后 —— 它是**别人的**知识，
# 没在本地验证过，只能当参考；这跟「本地源码」不是一回事。
AUTHORITY_BASE = {
    "code": 0.92,       # 本地源码实证：有代码佐证
    "document": 0.78,   # 正式文档
    "note": 0.72,
    "derived": 0.66,    # 合成/派生出来的
    "openkb": 0.62,     # 外部开源仓库：可参考，未本地验证
    "record": 0.60,     # 业务记录：陈述性强，佐证弱
    "manual": 0.52,     # 人工粘贴
}
AUTHORITY_NO_SOURCE = 0.35

# 会被「用旧了」拖累的知识类型。
# 业务事实（记录、约定）不会因为时间流逝而失效，
# 技术知识（源码、接口、文档、外部仓库）会 —— 版本一改就过期。
DECAYING_SOURCE_KINDS = {"code", "document", "openkb", "interface"}
FRESHNESS_HALFLIFE_DAYS = 365.0

# 人工确认过的知识：权威度直接顶格附近
VERIFIED_BONUS = 0.12
AUTHORITY_CAP = 0.98

# copyleft 许可证的外部代码，引用进产品是有合规风险的：
# 权威度不给加分，反而轻轻扣一点，提醒人去看许可证
COPYLEFT_PENALTY = 0.05


# ============ 工具 ============

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _round(v: float, n: int = 3) -> float:
    return round(float(v) + 0.0, n)


# ============ 具体信号（表达度第一项） ============

# 具体锚点：这几类信号出现得越多，说明这段话越「指着一件具体的事」
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
_CAMEL_RE = re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]*\b")
_SNAKE_RE = re.compile(r"\b[a-z]+_[a-z_]+\b")
_PATH_RE = re.compile(r"(?:[\w.-]+/){1,}[\w.-]+")
_VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")
_NUMBER_RE = re.compile(r"\b\d{2,}\b")
_URL_RE = re.compile(r"https?://[^\s）)】]+")
_COMMAND_RE = re.compile(r"(?:^|\n)\s*(?:\$|>|#)\s*\S+")
_FIELD_RE = re.compile(r"(?:^|\n)\s*[-*]?\s*[\w.\-]+\s*[:：=]\s*\S+")

_SPECIFIC_SIGNALS = (
    ("点号路径", _IDENTIFIER_RE),
    ("驼峰标识符", _CAMEL_RE),
    ("下划线标识符", _SNAKE_RE),
    ("文件路径", _PATH_RE),
    ("版本号", _VERSION_RE),
    ("URL", _URL_RE),
    ("命令行", _COMMAND_RE),
    ("字段赋值", _FIELD_RE),
)

# 通用标题：这些标题等于没标题，检索时谁也分不清
_GENERIC_TITLES = {
    "未命名片段", "（无标题基因）", "untitled", "readme", "readme.md",
    "标题", "无标题", "片段", "片段 1", "文档", "说明",
}


@dataclass
class Part:
    """一个分项：分数 + 权重 + 人话依据"""
    key: str
    label: str
    score: float
    weight: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "score": _round(self.score), "weight": self.weight,
                "detail": self.detail}


@dataclass
class Penalty:
    """一条扣分：负反馈必须看得见，不能悄悄把分打下去"""
    key: str
    label: str
    amount: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "amount": _round(self.amount), "detail": self.detail}


@dataclass
class ScoreResult:
    score: float
    parts: list[Part] = field(default_factory=list)
    penalties: list[Penalty] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": _round(self.score),
            "parts": [p.to_dict() for p in self.parts],
            "penalties": [p.to_dict() for p in self.penalties],
            "version": SCORE_VERSION,
        }


# ============ 表达度 ============

def _specificity(gene: DnaGene) -> Part:
    """具体度：这段话指的是不是一件**具体**的事

    判据不是「字数多」—— 一大段抄来的原文也不具体。
    判据是「有没有可辨认的锚点」：类名、路径、版本号、命令、字段。
    """
    content = gene.content or ""
    title = (gene.title or "").strip()
    hits = []
    for label, rx in _SPECIFIC_SIGNALS:
        m = rx.search(content) or rx.search(title)
        if m:
            hits.append(label)
    body_len = len(content)
    # 长度只做「过短/过长」两端的修正，不做线性加分
    length_adj = 0.0
    if body_len < 40:
        length_adj -= 0.25
    elif body_len > 4000:
        length_adj -= 0.08
    generic_title = title.lower() in _GENERIC_TITLES
    if generic_title:
        length_adj -= 0.15
    score = _clamp(0.30 + 0.12 * len(hits) + length_adj)
    detail = ("命中锚点：" + "、".join(hits)) if hits else "正文里没有可辨认的具体锚点"
    if body_len < 40:
        detail += "；正文过短"
    elif body_len > 4000:
        detail += "；正文过长，像整段搬运"
    if generic_title:
        detail += "；标题是通用词"
    return Part(EXPRESS_SPECIFICITY, "具体度", score,
                EXPRESS_WEIGHTS[EXPRESS_SPECIFICITY], detail)


# 可执行四要素：触发条件 / 步骤 / 边界 / 产出。
# 为什么要四要素而不是「像不像说明书」：
# 「说清楚了」在工程上就等于这四件事有没有交代清楚 ——
# 什么时候用、怎么做、什么不能做、用完得到什么。
_ACTION_ELEMENTS = {
    "trigger": ("触发条件", ("当", "如果", "一旦", "前提", "触发", "情况下",
                               "什么时候", "when ", "if ", "unless")),
    "steps": ("步骤", ("步骤", "第一步", "流程", "先", "然后", "接着", "依次",
                        "顺序", "第一步", "how to", "recipe")),
    "boundary": ("边界", ("边界", "限制", "注意", "不要", "不能", "禁止",
                           "必须", "范围", "上限", "最多", "至少", "例外",
                           "前提", "红线")),
    "output": ("产出", ("产出", "结果", "返回", "输出", "效果", "生成",
                         "落库", "得到", "会变成", "表现为")),
}


def _actionability(gene: DnaGene) -> Part:
    """可执行性：有没有把「怎么用」交代清楚"""
    text = f"{gene.title or ''}\n{gene.content or ''}".lower()
    found = []
    for key, (label, words) in _ACTION_ELEMENTS.items():
        if any(w in text for w in words):
            found.append(label)
    score = _clamp(len(found) / len(_ACTION_ELEMENTS))
    if found:
        detail = "交代了：" + "、".join(found)
    else:
        detail = "触发条件/步骤/边界/产出 四要素一个都没交代"
    return Part(EXPRESS_ACTIONABILITY, "可执行性", score,
                EXPRESS_WEIGHTS[EXPRESS_ACTIONABILITY], detail)


def _retrievability(gene: DnaGene) -> Part:
    """可检索性：能不能被找出来、找出来能不能认出是它

    判据：标题有区分度、有标签、正文够长（能被分词索引）、
    不是一坨纯代码（纯代码切片后基本没法检索）。
    """
    title = (gene.title or "").strip()
    content = gene.content or ""
    score = 0.0
    notes = []
    if title and title.lower() not in _GENERIC_TITLES and 4 <= len(title) <= 80:
        score += 0.35
        notes.append("标题有区分度")
    else:
        notes.append("标题缺区分度")
    tags = gene.tags or []
    if len(tags) >= 1:
        score += 0.20
        notes.append(f"标签 {len(tags)} 个")
    else:
        notes.append("没有标签")
    if len(content) >= 60:
        score += 0.25
    else:
        notes.append("正文过短")
    code_lines = sum(1 for ln in content.splitlines()
                     if ln.strip().startswith(("def ", "class ", "function ",
                                               "return ", "import ", "from ")))
    total_lines = max(1, len([ln for ln in content.splitlines() if ln.strip()]))
    if code_lines / total_lines < 0.7:
        score += 0.20
    else:
        notes.append("正文基本是代码，检索命中后认不出说的是什么")
    return Part(EXPRESS_RETRIEVABILITY, "可检索性", _clamp(score),
                EXPRESS_WEIGHTS[EXPRESS_RETRIEVABILITY], "；".join(notes))


def _reuse(usage_count: int, use_success: int, use_fail: int) -> Part:
    """被复用度：这条知识真的被人拿去用过没有

    用饱和函数而不是线性：被用 10 次和被用 30 次，
    差别远没有 0 次和 3 次的差别大。
    """
    n = max(0, int(usage_count or 0))
    score = 1.0 - math.exp(-n / 3.0)
    detail = f"被检索/引用 {n} 次"
    if use_success or use_fail:
        total = use_success + use_fail
        rate = use_success / total if total else 0
        # 成功率对表达度的影响是**双向**的：用过且成功，说明说得清楚；
        # 用过但总失败，说明写得不清楚（这是表达度问题，不是可信度问题）
        score = _clamp(score * (0.6 + 0.4 * rate))
        detail += f"；复用 {total} 次，成功 {use_success} 次"
    return Part(EXPRESS_REUSE, "被复用度", score,
                EXPRESS_WEIGHTS[EXPRESS_REUSE], detail)


def score_expressiveness(gene: DnaGene, *, usage_count: int = 0,
                         use_success: int = 0, use_fail: int = 0) -> ScoreResult:
    """表达度总分：这条基因「说清楚了没有」"""
    parts = [
        _specificity(gene),
        _actionability(gene),
        _retrievability(gene),
        _reuse(usage_count, use_success, use_fail),
    ]
    total = sum(p.score * p.weight for p in parts)
    return ScoreResult(score=_clamp(total), parts=parts)


# ============ 置信度 ============

def _authority(gene: DnaGene, meta: dict, extraction_confidence: float) -> Part:
    """来源权威度：这条知识是从哪来的

    抽取时的启发式置信度（0.6/0.75/0.85 那种）保留下来参与计算，
    但不再单独当「置信度」—— 它只说明「抽取这一步有多确定」，
    说明不了「这条知识本身对不对」。
    """
    meta = meta or {}
    source_kind = (gene.source_kind or "").strip()
    if not (gene.source_ref or "").strip():
        base = AUTHORITY_NO_SOURCE
        notes = "说不出出处"
    else:
        base = AUTHORITY_BASE.get(source_kind, 0.55)
        notes = f"来源形态 {source_kind or '未知'}"
    # 抽取置信度占 30%：它是一个独立信号（规则匹配得多准），
    # 但不能主导 —— 一个来自权威文档、规则匹配置信度低的知识，
    # 依然比一个手贴的、规则匹配置信度高的知识可靠。
    extraction = _clamp(float(extraction_confidence or 0.7))
    score = 0.7 * base + 0.3 * extraction
    if meta.get("verified"):
        score += VERIFIED_BONUS
        notes += "；人工确认过"
    if gene.kind == "interface":
        # 接口类知识是可核对的东西（字段对不对，一查就知道）
        score += 0.05
        notes += "；接口类可核对"
    license_id = str(meta.get("license") or "").lower()
    if license_id:
        if any(k in license_id for k in ("gpl", "agpl", "sspl", "osl")):
            score -= COPYYLEFT_PENALTY
            notes += f"；许可证 {license_id} 属传染性，复用前要看清"
        else:
            score += 0.03
            notes += f"；许可证 {license_id}"
    score = _clamp(score, 0.0, AUTHORITY_CAP)
    return Part(CONF_AUTHORITY, "来源权威度", score,
                CONF_WEIGHTS[CONF_AUTHORITY], notes)


def _corroboration(distinct_sources: int, link_count: int,
                   strong_links: int) -> Part:
    """交叉验证：有几个**不同来源**说过同一件事

    「同一个来源说了三遍」不算印证 —— 那是重复，不是交叉验证。
    """
    n = max(0, int(distinct_sources or 0))
    if n <= 1:
        score = BASE_CORROBORATION
        detail = "只有 1 个来源，尚未交叉印证"
    else:
        score = _clamp(0.35 + 0.45 * (1 - math.exp(-(n - 1) / 1.5)))
        detail = f"{n} 个不同来源提到过同一件事"
    if strong_links:
        score = _clamp(score + min(0.15, 0.05 * strong_links))
        detail += f"；另有 {strong_links} 条高度相似的既有知识"
    elif link_count:
        detail += f"；另有 {link_count} 条相关知识（相似度不足）"
    return Part(CONF_CORROBORATION, "交叉验证", score,
                CONF_WEIGHTS[CONF_CORROBORATION], detail)


def _usage_success(use_success: int, use_fail: int) -> Part:
    """复用成功率：真的拿去用之后，成功了几次"""
    s = max(0, int(use_success or 0))
    f = max(0, int(use_fail or 0))
    total = s + f
    if total == 0:
        return Part(CONF_USAGE_SUCCESS, "复用成功率", NEUTRAL_USAGE_SUCCESS,
                    CONF_WEIGHTS[CONF_USAGE_SUCCESS],
                    "还没有被复用过，按中性计（用过才算数）")
    score = s / total
    return Part(CONF_USAGE_SUCCESS, "复用成功率", score,
                CONF_WEIGHTS[CONF_USAGE_SUCCESS],
                f"复用 {total} 次：成功 {s}、失败 {f}")


def _freshness(gene: DnaGene, meta: dict, now: datetime) -> Part:
    """时效性：依赖的版本/接口是不是已经过期"""
    meta = meta or {}
    if gene.status == "superseded":
        return Part(CONF_FRESHNESS, "时效性", 0.10, CONF_WEIGHTS[CONF_FRESHNESS],
                    "已被更新的版本取代")
    version = str(meta.get("version") or meta.get("pinned") or "").strip()
    if version:
        return Part(CONF_FRESHNESS, "时效性", 0.90, CONF_WEIGHTS[CONF_FRESHNESS],
                    f"锚定了版本 {version}")
    updated = gene.updated_at or gene.created_at
    if not updated:
        return Part(CONF_FRESHNESS, "时效性", 0.50, CONF_WEIGHTS[CONF_FRESHNESS],
                    "没有时间信息，按中性计")
    age_days = max(0.0, (now - updated).total_seconds() / 86400.0)
    if (gene.source_kind or "") not in DECAYING_SOURCE_KINDS:
        # 业务事实不会因为放久了就变假
        return Part(CONF_FRESHNESS, "时效性", 0.85, CONF_WEIGHTS[CONF_FRESHNESS],
                    f"业务知识不随时间失效（已 {int(age_days)} 天）")
    # 半衰期衰减：一年前的技术知识还留一半可信度
    score = 0.5 ** (age_days / FRESHNESS_HALFLIFE_DAYS)
    return Part(CONF_FRESHNESS, "时效性", _clamp(score), CONF_WEIGHTS[CONF_FRESHNESS],
                f"距上次更新 {int(age_days)} 天（技术知识按一年半衰期衰减）")


def score_confidence(gene: DnaGene, *, meta: dict | None = None,
                     extraction_confidence: float = 0.7,
                     distinct_sources: int = 1,
                     link_count: int = 0, strong_links: int = 0,
                     use_success: int = 0, use_fail: int = 0,
                     corrections: int = 0,
                     now: datetime | None = None) -> ScoreResult:
    """置信度总分：这条基因「有多可信」

    扣分项（负反馈）在这里生效：
      - 被人工纠正过 → 每次扣一点，最多扣 0.4
      - 复用失败过   → 每次扣一点，最多扣 0.25
    负反馈必须真的把分拉下来，否则「纠正」这个动作就没有意义。
    """
    meta = meta or {}
    now = now or _now()
    parts = [
        _authority(gene, meta, extraction_confidence),
        _corroboration(distinct_sources, link_count, strong_links),
        _usage_success(use_success, use_fail),
        _freshness(gene, meta, now),
    ]
    total = sum(p.score * p.weight for p in parts)
    penalties: list[Penalty] = []
    c = max(0, int(corrections or 0))
    if c:
        amount = min(MAX_CORRECTION_PENALTY, CORRECTION_PENALTY * c)
        penalties.append(Penalty("corrections", "人工纠正", amount,
                                 f"被纠正 {c} 次"))
    f = max(0, int(use_fail or 0))
    if f:
        amount = min(MAX_FAILURE_PENALTY, FAILURE_PENALTY * f)
        penalties.append(Penalty("use_fail", "复用失败", amount,
                                 f"复用失败 {f} 次"))
    for p in penalties:
        total -= p.amount
    return ScoreResult(score=_clamp(total), parts=parts, penalties=penalties)


# ============ 落库 ============

async def ensure_score_schema(conn) -> bool:
    """给 dna_gene 补评分列、建评分表（幂等）

    为什么要有这一步：dna_gene 是老表，SQLAlchemy 的 create_all
    **只建缺���的表，不会给已存在的表加列**。
    而模型里一旦声明了 expressiveness 列，ORM 每次 SELECT 都会带上它，
    列不存在就直接「no such column」—— 整个养料库都用不了。

    所以补列必须跟 create_all 一样在启动期做掉，而不是等到用的时候。
    """
    try:
        cols = {r[1] for r in (await conn.execute(
            text("pragma table_info(dna_gene)"))).all()}
    except Exception as e:
        log.warning("读取 dna_gene 列信息失败：%s", e)
        return False
    if not cols:
        # 表还不存在（全新库）：create_all 会按模型建好，列自然有
        return True
    try:
        if "expressiveness" not in cols:
            await conn.execute(text(
                "alter table dna_gene add column expressiveness real default 0"))
        if "score_version" not in cols:
            await conn.execute(text(
                "alter table dna_gene add column score_version integer default 0"))
        await conn.execute(text(
            "create table if not exists dna_gene_score ("
            "id integer primary key autoincrement,"
            "gene_id integer not null unique,"
            "expressiveness real default 0,"
            "confidence real default 0,"
            "express_parts text default '{}',"
            "confidence_parts text default '{}',"
            "evidence text default '{}',"
            "use_success integer default 0,"
            "use_fail integer default 0,"
            "corrections integer default 0,"
            "corroborations integer default 0,"
            "distinct_sources integer default 1,"
            "extraction_confidence real default 0.7,"
            "version integer default 0,"
            "last_scored_at datetime,"
            "created_at datetime default (datetime('now')),"
            "updated_at datetime default (datetime('now')) )"))
        await conn.execute(text(
            "create index if not exists ix_gene_score_conf on dna_gene_score(confidence)"))
        await conn.execute(text(
            "create index if not exists ix_gene_score_expr on dna_gene_score(expressiveness)"))
        return True
    except Exception as e:
        log.warning("评分表结构补齐失败：%s", e)
        return False


def _json_load(raw, default):
    import json
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return default
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return val if val is not None else default


async def _load_scores(db: AsyncSession, gene_ids: list[int]) -> dict[int, DnaGeneScore]:
    if not gene_ids:
        return {}
    rows = (await db.execute(
        select(DnaGeneScore).where(DnaGeneScore.gene_id.in_(gene_ids))
    )).scalars().all()
    return {r.gene_id: r for r in rows}


async def _distinct_source_counts(db: AsyncSession,
                                   genes: list[DnaGene]) -> dict[int, int]:
    """同内容出现在几个不同来源里（交叉验证的原料）

    按指纹分组统计来源数 —— 指纹只算正文，所以
    「同一段话被抄进五份文档」会算成五个来源，
    而「同一段话在两处出现」也确实算印证（用户自己说的两处）。
    """
    fps = {(g.fingerprint or "") for g in genes if g.fingerprint}
    counts: dict[int, int] = {}
    if not fps:
        return {g.id: 1 for g in genes}
    rows = (await db.execute(
        select(DnaGene.fingerprint, DnaGene.source_ref)
        .where(DnaGene.fingerprint.in_(list(fps)),
               DnaGene.status == "active"))).all()
    per_fp: dict[str, set] = {}
    for fp, ref in rows:
        per_fp.setdefault(fp or "", set()).add((ref or "").strip() or "?")
    for g in genes:
        counts[g.id] = len(per_fp.get(g.fingerprint or "", {"?"}))
    return counts


def _link_stats(meta: dict) -> tuple[int, int]:
    """从 meta.links 里数出「相关」与「高度相似」

    相似度 ≥ 0.8 才算强印证：0.55 的相似多半只是同一片代码里的
    邻居函数，说它们互相印证是自欺欺人。
    """
    links = (meta or {}).get("links") or []
    total = len(links)
    strong = sum(1 for l in links
                 if isinstance(l, dict) and float(l.get("sim") or 0) >= 0.8)
    return total, strong


async def rescore_genes(db: AsyncSession, gene_ids: list[int], *,
                        commit: bool = True) -> dict:
    """重算一批基因的评分（增量更新的核心）

    只重算传进来的这几条 —— 新增/使用/纠正时都走这里，
    代价与基因总数无关。
    """
    ids = [int(i) for i in dict.fromkeys(gene_ids or []) if i]
    if not ids:
        return {"scored": 0, "changed": 0}
    genes = (await db.execute(
        select(DnaGene).where(DnaGene.id.in_(ids)))).scalars().all()
    if not genes:
        return {"scored": 0, "changed": 0}
    # usage_count 要单独查一遍，不能直接读 ORM 对象上的属性：
    # mark_gene_used 走的是批量 update（synchronize_session=False），
    # 会话又关掉了 expire_on_commit —— 对象里那个值是旧的。
    # 拿旧值算分，等于「被用过」这件事对分数不起作用。
    usage_rows = (await db.execute(
        select(DnaGene.id, DnaGene.usage_count)
        .where(DnaGene.id.in_(ids)))).all()
    usage_map = {int(r[0]): int(r[1] or 0) for r in usage_rows}
    scores = await _load_scores(db, [g.id for g in genes])
    src_counts = await _distinct_source_counts(db, genes)
    now = _now()
    changed = 0
    for g in genes:
        row = scores.get(g.id)
        meta = g.meta or {}
        extraction = row.extraction_confidence if row else None
        if extraction is None:
            # 第一次评分：把旧版那条裸 confidence 留下来当「抽取置信度」，
            # 它是独立信号（规则匹配置信度），不能被新分数直接顶掉
            extraction = float(g.confidence or 0.7)
        use_success = int(row.use_success or 0) if row else 0
        use_fail = int(row.use_fail or 0) if row else 0
        corrections = int(row.corrections or 0) if row else 0
        link_count, strong_links = _link_stats(meta)
        ex = score_expressiveness(
            g, usage_count=usage_map.get(g.id, int(g.usage_count or 0)),
            use_success=use_success, use_fail=use_fail)
        cf = score_confidence(
            g, meta=meta, extraction_confidence=extraction,
            distinct_sources=src_counts.get(g.id, 1),
            link_count=link_count, strong_links=strong_links,
            use_success=use_success, use_fail=use_fail,
            corrections=corrections, now=now)
        if row is None:
            row = DnaGeneScore(gene_id=g.id)
            db.add(row)
            row.extraction_confidence = extraction
            row.distinct_sources = src_counts.get(g.id, 1)
        row.expressiveness = ex.score
        row.confidence = cf.score
        row.express_parts = {p.key: p.to_dict() for p in ex.parts}
        row.confidence_parts = {p.key: p.to_dict() for p in cf.parts}
        row.evidence = {"expressiveness": ex.to_dict(),
                        "confidence": cf.to_dict()}
        row.use_success = use_success
        row.use_fail = use_fail
        row.corrections = corrections
        row.version = SCORE_VERSION
        row.last_scored_at = now
        row.updated_at = now
        if row.created_at is None:
            row.created_at = now
        # 镜像回基因表：老代码（排序、筛选）读的是这两列
        if abs(float(g.expressiveness or 0) - ex.score) > 1e-6:
            changed += 1
        g.expressiveness = ex.score
        g.confidence = cf.score
        g.score_version = SCORE_VERSION
        g.updated_at = g.updated_at or now
    if commit:
        await db.commit()
    return {"scored": len(genes), "changed": changed}


async def rescore_gene(db: AsyncSession, gene_id: int, *,
                       commit: bool = True) -> dict | None:
    """重算单条基因（新增/使用/纠正时走这里）"""
    res = await rescore_genes(db, [gene_id], commit=commit)
    if not res["scored"]:
        return None
    row = (await db.execute(
        select(DnaGeneScore).where(DnaGeneScore.gene_id == gene_id)
    )).scalar_one_or_none()
    return score_to_dict(row) if row else None


async def record_use(db: AsyncSession, gene_ids: list[int], *,
                     success: bool | None = None,
                     commit: bool = True) -> dict:
    """记一次「被用过」，并让分数跟着变

    success=None 表示「只是被检索命中」（还不知道有没有用对）；
    success=True/False 是复用后的真实结果 —— 它是置信度里
    「复用成功率」这一项的唯一来源。

    这里必须真的改分：不然「学 → 用 → 更准」这条闭环是假的。
    """
    ids = [int(i) for i in dict.fromkeys(gene_ids or []) if i]
    if not ids:
        return {"genes": 0}
    now = _now()
    scores = await _load_scores(db, ids)
    for gid in ids:
        row = scores.get(gid)
        if row is None:
            row = DnaGeneScore(gene_id=gid)
            db.add(row)
            row.created_at = now
            row.updated_at = now
            row.extraction_confidence = 0.7
            row.distinct_sources = 1
        if success is True:
            row.use_success = int(row.use_success or 0) + 1
        elif success is False:
            row.use_fail = int(row.use_fail or 0) + 1
        row.updated_at = now
    if commit:
        await db.commit()
    await rescore_genes(db, ids, commit=commit)
    return {"genes": len(ids), "success": success}


async def record_correction(db: AsyncSession, gene_id: int, *,
                             note: str = "", commit: bool = True) -> dict | None:
    """记一次人工纠正 —— 纠正必须真的扣分

    没有这一步，「纠正」只是一个按钮；有了它，
    错过的知识会自己沉下去，正确的知识会浮上来。
    """
    row = (await db.execute(
        select(DnaGeneScore).where(DnaGeneScore.gene_id == gene_id)
    )).scalar_one_or_none()
    now = _now()
    if row is None:
        row = DnaGeneScore(gene_id=gene_id)
        db.add(row)
        row.created_at = now
        row.extraction_confidence = 0.7
        row.distinct_sources = 1
    row.corrections = int(row.corrections or 0) + 1
    row.updated_at = now
    if commit:
        await db.commit()
    return await rescore_gene(db, gene_id, commit=commit)


async def note_source(db: AsyncSession, gene: DnaGene, source_ref: str,
                      *, commit: bool = False) -> None:
    """记下这条知识还出现在哪些来源里（交叉验证的原料）

    同一条知识被第二次从**另一个**来源抽到时，来源要多记一份。
    """
    ref = (source_ref or "").strip()
    if not ref:
        return
    meta = dict(gene.meta or {})
    sources = list(meta.get("sources") or [])
    if ref not in sources:
        sources.append(ref)
        meta["sources"] = sources[:12]
        gene.meta = meta
    if commit:
        await db.commit()


def score_to_dict(row: DnaGeneScore | None) -> dict:
    """把评分行序列化成给前端看的形状"""
    if row is None:
        return {"expressiveness": 0.0, "confidence": 0.0,
                "express_parts": {}, "confidence_parts": {}, "evidence": {},
                "use_success": 0, "use_fail": 0, "corrections": 0,
                "version": 0}
    return {
        "gene_id": row.gene_id,
        "expressiveness": _round(row.expressiveness or 0),
        "confidence": _round(row.confidence or 0),
        "express_parts": _json_load(row.express_parts, {}),
        "confidence_parts": _json_load(row.confidence_parts, {}),
        "evidence": _json_load(row.evidence, {}),
        "use_success": int(row.use_success or 0),
        "use_fail": int(row.use_fail or 0),
        "corrections": int(row.corrections or 0),
        "corroborations": int(row.corroborations or 0),
        "distinct_sources": int(row.distinct_sources or 1),
        "version": int(row.version or 0),
        "last_scored_at": row.last_scored_at.isoformat()
        if row.last_scored_at else None,
    }


async def get_score(db: AsyncSession, gene_id: int) -> dict:
    """取一条基因的评分（详情页用）"""
    row = (await db.execute(
        select(DnaGeneScore).where(DnaGeneScore.gene_id == gene_id)
    )).scalar_one_or_none()
    return score_to_dict(row)


async def rescore_all(db: AsyncSession, *, batch: int = 200,
                      only_stale: bool = True, commit: bool = True) -> dict:
    """全量回填（给脚本与维护接口用）

    only_stale=True 时只重算 score_version 落后的行 ——
    日常增量更新已经把大部分行刷新过了。
    """
    total = 0
    offset = 0
    while True:
        stmt = select(DnaGene.id)
        if only_stale:
            stmt = stmt.where(
                (DnaGene.score_version != SCORE_VERSION)
                | (DnaGene.score_version.is_(None)))
        stmt = stmt.order_by(DnaGene.id).offset(offset).limit(batch)
        ids = [r[0] for r in (await db.execute(stmt)).all()]
        if not ids:
            break
        res = await rescore_genes(db, ids, commit=commit)
        total += res["scored"]
        offset += len(ids)
        if len(ids) < batch:
            break
    if commit:
        await db.commit()
    return {"scored": total, "version": SCORE_VERSION}
