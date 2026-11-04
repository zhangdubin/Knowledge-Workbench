"""软件开发四阶段流水线：需求理解 → 需求补全 → 需求转化 → 项目生成

为什么要有流水线，而不是「一次调用出一段方案」：
    一次调用出方案的做法，产出的是「看起来像那么回事」的东西 ——
    需求里没说的地方模型自己编、结构由模型说了算、技术栈被偷偷换掉。
    专业的做法是四段推进，每段有交付物、有闸门、能被人改：
        clarify   需求理解：模型先说它以为的需求是什么，并提出要澄清的问题
        specify   需求补全：把需求写成可验收的用户故事、非功能需求、数据模型
        design    需求转化：架构、模块、表、接口，以及带依赖的任务拆解
        implement 项目生成：产出真能跑起来的项目文件
    段与段之间有闸门：前一段没过关就不许进下一段 ——
    「先跑再失败」是最浪费用户时间的做法。

这一版踩过的坑，都被写进提示词与校验里：
    1. 提示词必须带 schema：summary / architecture 是**字符串**、tasks 是数组、
       每项有 title/description/acceptance/depends_on、不要改动用户指定的技术栈。
       不约束，模型就会自作主张（把 Python 换成 Java、把字符串写成对象）。
    2. 模型输出被 max_tokens 截断时，要能**抢救 JSON**，而不是报「生成失败」。
    3. 作业进度必须有真实的 total 与 processed —— 前端不该再看到永远 50%。
    4. 状态只存 dev_project.plan_json["pipeline"]，不新增数据库列、不动迁移。

本模块不修改 dev.py：模型调用、JSON 解析、安全扫描都复用那边已有的实现，
这里只做「阶段编排 + 闸门 + 状态机 + 作业进度 + 导出」。
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (DevArtifact, DevCitation, DevProject, DevSession, DnaJob)
from . import dev as dev_svc
from . import dev_config

log = logging.getLogger("kb.dev.pipeline")


# ============ 阶段与状态机 ============

STAGES = ("clarify", "specify", "design", "implement")

STAGE_TITLES = {
    "clarify": "需求理解",
    "specify": "需求补全",
    "design": "需求转化",
    "implement": "项目生成",
}

STAGE_STATUSES = ("pending", "running", "needs_input", "done", "failed")

# 每个阶段的真实步骤（作业的 total 用它）
# 为什么不用 total=1：前端进度条按 processed/total 算，
# total 写 1 或 0 都会让「进行中」变成假进度。
STAGE_STEPS = {
    "clarify": ["检索相关知识", "调用模型生成需求理解与澄清问题",
                "校验结构", "保存阶段产出"],
    "specify": ["检索相关知识", "调用模型生成需求规格",
                "校验结构", "保存阶段产出"],
    "design": ["检索相关知识", "调用模型生成设计与任务拆解",
               "校验结构", "写入任务表", "保存阶段产出"],
    "implement": ["组装上下文与文件清单", "逐个生成文件",
                  "补齐缺失的必需文件", "校验文件与安全", "保存产出物"],
}

# 阶段闸门：跑某个阶段前，必须先做完哪个阶段
GATE_REQUIRES = {
    "clarify": "",
    "specify": "clarify",
    "design": "specify",
    "implement": "design",
}

# 闸门没过时给用户的说法（说清楚「在哪儿做什么」，而不是只说「不允许」）
GATE_HOW = {
    "clarify": "到「需求理解」阶段跑一次，回答模型提出的澄清问题",
    "specify": "到「需求补全」阶段跑一次并审阅需求规格",
    "design": "到「需求转化」阶段跑一次，产出设计与任务拆解",
    "implement": "到「项目生成」阶段跑一次，产出可运行的项目文件",
}


class PipelineError(dev_svc.DevError):
    """流水线错误。

    继承 DevError 是为了复用同一套错误口径：
    {ok:false, detail, missing[], how_to_fix[]} ——
    前端拿 missing / how_to_fix 直接渲染成一张可执行的清单。
    """


def _now() -> datetime:
    return datetime.now()


def _now_iso() -> str:
    return _now().isoformat()


# ============ 流水线状态（存在 plan_json["pipeline"] 里） ============

def empty_pipeline() -> dict:
    """一条空流水线。

    四个阶段都是 pending —— 前端左栏一进来就能看到完整的骨架，
    而不是「阶段信息不存在」。
    """
    return {
        "current_stage": "clarify",
        "stages": {k: {"status": "pending", "at": "", "data": {},
                       "answers": {}, "notes": "", "error": "",
                       "summary": ""} for k in STAGES},
        "updated_at": "",
    }


def get_pipeline(project: DevProject) -> dict:
    """读出流水线状态；老项目没有这段数据时补一份空的。

    为什么不在读的时候直接改库：读接口可能被前端高频轮询，
    每次都写一遍库没意义 —— 真正要写的是「跑阶段」和「提交答案」。
    """
    raw = {}
    try:
        raw = (project.plan_json or {}).get("pipeline") or {}
    except Exception:
        raw = {}
    pipeline = empty_pipeline()
    if isinstance(raw, dict):
        stages = raw.get("stages") or {}
        for key in STAGES:
            src = stages.get(key) or {}
            if not isinstance(src, dict):
                src = {}
            dst = pipeline["stages"][key]
            status = src.get("status") or "pending"
            dst["status"] = status if status in STAGE_STATUSES else "pending"
            dst["at"] = src.get("at") or ""
            dst["data"] = src.get("data") or {}
            dst["answers"] = src.get("answers") or {}
            dst["notes"] = src.get("notes") or ""
            dst["error"] = src.get("error") or ""
            dst["summary"] = src.get("summary") or ""
        pipeline["current_stage"] = raw.get("current_stage") or "clarify"
    # current_stage 永远指向第一个没做完的阶段：
    # 阶段被重跑后这个值必须跟着回退，否则界面会停在错的阶段上
    pipeline["current_stage"] = first_unfinished(pipeline)
    return pipeline


def first_unfinished(pipeline: dict) -> str:
    for key in STAGES:
        if pipeline["stages"][key]["status"] != "done":
            return key
    return STAGES[-1]


async def save_pipeline(db: AsyncSession, project: DevProject,
                        pipeline: dict) -> None:
    """把流水线状态写回 plan_json。

    注意是**合并**而不是整体覆盖 plan_json ——
    那边还存着老流程生成的方案对象，覆盖掉就把方案弄没了。

    为什么写之前要深拷贝：
        SQLAlchemy 判断「这个值变了没有」用的是相等比较，
        而流水线状态是就地改的（st["status"] = ...）。
        不拷贝的话，前后两次赋的是同一个字典对象，
        相等比较说「没变」，UPDATE 根本不会发出去 ——
        结果就是状态永远停在 running。这类 bug 极难查：
        代码看着都对，值也确实是新的，只是没落库。
    """
    snapshot = json.loads(json.dumps(pipeline))
    data = dict(project.plan_json or {})
    data["pipeline"] = snapshot
    project.plan_json = data
    project.updated_at = _now()
    await db.commit()


def stage_summary(key: str, stage: dict) -> str:
    """给左栏导航用的一句人话。

    为什么要专门写一句人话：前端左栏只有阶段名，用户不知道「跑到哪一步了」。
    这一句比状态标签更能说明「现在这个阶段到底产出了什么」。
    """
    status = stage.get("status") or "pending"
    data = stage.get("data") or {}
    if status == "pending":
        return "还没开始"
    if status == "running":
        return "正在跑"
    if status == "failed":
        return "失败了：" + (stage.get("error") or "原因未知")
    if status == "needs_input":
        qs = data.get("questions") or []
        pending = unanswered_questions(stage)
        return "有 %d 个问题待回答（还剩 %d 个）" % (len(qs), len(pending))
    if key == "clarify":
        return "已理解需求%s" % ("（无需澄清）" if not (data.get("questions") or [])
                                else "，澄清问题已回答")
    if key == "specify":
        return "%d 条用户故事 · %d 条非功能需求" % (
            len(data.get("stories") or []), len(data.get("nonfunctional") or []))
    if key == "design":
        return "%d 个模块 · %d 张表 · %d 个任务" % (
            len(data.get("modules") or []), len(data.get("data_tables") or []),
            len(data.get("task_ids") or []))
    if key == "implement":
        files = data.get("files") or []
        return "已生成 %d 个项目文件" % len(files)
    return "已完成"


def stages_view(pipeline: dict) -> list[dict]:
    """左栏导航用的精简视图（顺序固定）"""
    current = pipeline.get("current_stage") or "clarify"
    out = []
    for key in STAGES:
        st = pipeline["stages"][key]
        out.append({
            "key": key,
            "title": STAGE_TITLES[key],
            "status": st.get("status") or "pending",
            "summary": stage_summary(key, st),
            "blocking": (key == current and (st.get("status") or "") != "done"),
        })
    return out


def gates_of(pipeline: dict) -> dict:
    """闸门状态：前端据此决定「能不能点下一个阶段」"""
    stages = pipeline.get("stages") or {}
    done = {k: (stages.get(k) or {}).get("status") == "done" for k in STAGES}
    return {
        "can_specify": done["clarify"],
        "can_design": done["specify"],
        "can_implement": done["design"],
    }


def unanswered_questions(stage: dict) -> list[dict]:
    """还没回答的澄清问题。

    判据是「问题 id 出现在 answers 里」而不是「答案非空」——
    用户选了「都不需要」也是一种回答，答案是空串也算数。
    """
    data = stage.get("data") or {}
    answers = stage.get("answers") or {}
    return [q for q in (data.get("questions") or [])
            if str(q.get("id") or "") not in answers]


def check_gate(pipeline: dict, stage: str, *, force: bool = False) -> None:
    """闸门检查：不过就抛 409，绝不「先跑再失败」。

    抛 409 而不是 400：409 表达的是「状态冲突」——
    前端据此提示「先去完成上一阶段」，而不是「你请求写错了」。
    """
    if stage not in STAGES:
        raise PipelineError("阶段只能是 %s" % " / ".join(STAGES),
                            status=400, missing=["stage"],
                            how_to_fix=["检查阶段名"])
    req = GATE_REQUIRES[stage]
    if req:
        prev = pipeline["stages"][req]
        if prev.get("status") != "done":
            raise PipelineError(
                "「%s」还没完成，先把「%s」做完" % (
                    STAGE_TITLES[req], STAGE_TITLES[req]),
                status=409, missing=[req],
                how_to_fix=[GATE_HOW[req]],
                detail={"required_stage": req,
                       "required_status": prev.get("status") or "pending"})
    cur = pipeline["stages"][stage]
    if (cur.get("status") == "done") and not force:
        raise PipelineError(
            "「%s」已经完成，要重跑请开启强制重跑" % STAGE_TITLES[stage],
            status=409, missing=[stage],
            how_to_fix=["确认要覆盖旧产出后，开启「强制重跑」再执行"],
            detail={"stage": stage})


# ============ 提示词 ============

_SCHEMA_RULES = """
通用要求：
1. 只输出一个 JSON 对象，不要在 JSON 前后加任何解释性文字。
2. 严格按给定的字段结构输出，字段名不要改、不要增删顶层键。
3. 标了「必须是字符串」的字段就输出字符串，不要写成对象或数组。
4. 标了「必须是数组」的字段就输出数组，元素是对象时字段名照抄。
5. **不要改动用户指定的技术栈**：只能用给定的技术栈，需要别的能力就用标准库实现。
6. 控制在长度上限以内（宁可少写几条，也不要写太长被截断）。
""".strip()

CLARIFY_SYSTEM = """你是一位资深需求分析师，正在为一个知识库工作台里的「软件开发」模块做需求理解。

输出结构（固定）：
{
  "understanding": "一段话：这个系统给谁用、解决什么问题、边界在哪",
  "assumptions": ["我们默认……（写下来让用户去推翻）"],
  "questions": [
    {"id": "q1", "question": "要澄清的问题",
     "why": "为什么必须问清楚（不答会导致做错什么）",
     "options": ["候选1", "候选2"], "allow_free": true}
  ]
}

细则：
- understanding 必须是**字符串**（不要写成对象）。
- questions 必须是数组；每项都要有 id / question / why / options / allow_free。
- options 给 2~4 个候选答案，allow_free 表示是否允许用户自由填写。
- 最多 8 个问题，只问「不问就会做错」的问题；需求已经清楚时 questions 给空数组 []。
""" + _SCHEMA_RULES

SPECIFY_SYSTEM = """你是一位资深需求分析师，正在把需求写成可验收的规格。

输出结构（固定）：
{
  "stories": [
    {"id": "S1", "title": "用户故事标题", "as_a": "角色", "i_want": "想要什么",
     "so_that": "为了什么", "acceptance": ["可判定的验收标准", "另一条标准"]}
  ],
  "nonfunctional": ["性能：列表查询 P95 < 500ms", "安全：仅内网可访问"],
  "data_model": [{"entity": "实体名", "fields": ["字段1", "字段2"]}],
  "edge_cases": ["边界与异常场景"],
  "out_of_scope": ["明确不做的范围"]
}

细则：
- stories 必须是数组；每项都要有 id / title / as_a / i_want / so_that / acceptance，
  acceptance 是**数组**，每条都能拿它对照检查。
- data_model 每项的 fields 必须是数组；out_of_scope 要写清「这次不做什么」。
- 最多 6 条用户故事、6 条非功能需求、6 个实体、6 条边界、5 条不做范围。
- **宁可少写几条**：写多了既慢又容易被截断。
""" + _SCHEMA_RULES

DESIGN_SYSTEM = """你是一位资深软件架构师，正在把需求规格转成可实施的设计。

输出结构（固定）：
{
  "architecture": "一段话讲清楚整体形态与关键取舍",
  "modules": [{"name": "模块名", "responsibility": "职责", "depends_on": []}],
  "data_tables": [{"name": "表名", "columns": [{"name": "列名", "type": "类型"}]}],
  "apis": [{"method": "GET", "path": "/api/xxx", "purpose": "用途"}],
  "risks": ["风险与对策"],
  "tasks": [
    {"title": "任务标题", "description": "这一步具体做什么",
     "acceptance": "可判定的验收标准", "depends_on": []}
  ]
}

细则：
- architecture 必须是**字符串**（不要写成对象）。
- modules / data_tables / apis / tasks 都必须是数组；
  data_tables 每项的 columns 必须是数组，元素含 name / type。
- tasks 每项都要有 title / description / acceptance / depends_on；
  depends_on 填**同一 tasks 数组里的下标**（从 0 开始），没有前置就是 []。
- 最多 6 个模块、6 张表、10 个接口、8 个任务；任务粒度半天到一天能做完。
- **宁可少写几条**：写多了既慢又容易被截断。
""" + _SCHEMA_RULES

IMPLEMENT_SYSTEM = """你是一位资深工程师，正在为一个项目生成**真实可运行**的代码文件。

输出结构（固定）：
{
  "files": [
    {"path": "backend/app/main.py", "language": "python", "content": "完整文件内容"}
  ],
  "notes": "实现说明：关键取舍、怎么跑、怎么测"
}

细则：
- content 必须是**完整文件内容**，不要用「……此处省略」代替代码。
- 路径用项目内相对路径，不要绝对路径，也不要 ../ 往上跳。
- 必须包含这五类文件，缺一类就不算可用项目：
  README.md（怎么装、怎么跑、怎么测）、依赖清单（requirements.txt 或 package.json）、
  至少一个可运行入口（main.py / app.py / index.js / main.go）、
  至少一个测试文件（test_*.py 或 *.test.js）、
  启动脚本或 Dockerfile（start.sh / Dockerfile / Makefile）。
- 严禁硬编码密钥、口令、令牌；需要凭据的地方用环境变量或配置占位。
- 严禁破坏性命令（rm -rf /、mkfs、dd 写裸设备等）。
- 一次最多 8 个文件，单个文件尽量控制在 150 行以内；
  文件多了先保证上面那五类必需文件。
- **别展开长篇推理**：直接给文件内容。
""" + _SCHEMA_RULES

# 项目生成一次只问一个文件：
# 为什么要一个文件一次问：一次要一整套文件，推理型模型很容易把输出预算花光、
# 正文只写一半甚至一个字没写（实测 MiniMax-M3.1-Flash 预算不够时正文 0 字）。
# 一个文件一次问之后每次都是小任务：更稳、更快，失败也只需要重问那一个。
IMPLEMENT_ONE_FILE = """
【这一次只写这一个文件】
要写的文件：%s
这个文件要做什么：%s
验收标准：%s

只输出一个 JSON 对象：{"files": [{"path": "...", "content": "..."}]}
files 里最多两个文件，而且必须包含上面这个文件；path 用项目内相对路径；
content 给完整内容，不要省略号、不要写「此处省略」。
"""

IMPLEMENT_KIND_FILE = """
【这一次只补一个文件：%s】
%s

只输出一个 JSON 对象：{"files": [{"path": "...", "content": "..."}]}
path 用项目内相对路径；content 给完整内容，不要省略号。
"""

# 项目生成阶段同时问模型几个文件（有限并发）。
#
# 为什么默认 3 路：
#     实测一个文件要 3~9 分钟，8 个文件串行 = 25~70 分钟 ——
#     用户等一半就以为功能坏了，并发是让它「能用」的关键。
#     但模型服务有并发配额，超了会被限流，反而更慢甚至全挂；
#     3 路是「明显变快」与「不把模型端点打爆」之间的折中。
#     想改的话在开发设置里加一项 implement_concurrency（1~8）。
IMPLEMENT_CONCURRENCY = 3


def _stack_text(project: DevProject) -> str:
    stack = [str(s).strip() for s in (project.tech_stack or []) if str(s).strip()]
    return "、".join(stack) if stack else "（用户未指定，按常规选择并在 notes 里说明）"


def _project_brief(project: DevProject) -> str:
    return "\n".join([
        "项目名称：%s" % (project.name or ""),
        "项目目标：%s" % (project.goal or "（未填写）"),
        "技术栈（不要改动）：%s" % _stack_text(project),
        "技术选型说明：%s" % (project.tech_notes or "（未填写）"),
    ])


def _knowledge_block(cites: list[dict]) -> str:
    """把引用拼成给模型看的参考资料段落。

    这里自己拼而不用 dev 模块的私有函数：
    流水线是独立的一层，依赖别人的私有符号会让两个模块绑死在一起。
    """
    if not cites:
        return "（本次没有检索到可引用的知识，请明确说明依据不足）"
    lines = []
    for i, c in enumerate(cites[:16], start=1):
        lines.append("[%d] %s（%s｜置信度 %.2f）\n%s"
                     % (i, c.get("title") or "", c.get("kind") or "",
                        float(c.get("confidence") or 0),
                        (c.get("snippet") or "")[:600]))
    return "\n".join(lines)


def _answers_block(stage: dict) -> str:
    answers = stage.get("answers") or {}
    if not answers:
        return ""
    data = stage.get("data") or {}
    questions = {str(q.get("id") or ""): q for q in (data.get("questions") or [])}
    lines = []
    for qid, val in answers.items():
        q = questions.get(str(qid)) or {}
        lines.append("- %s：%s" % (q.get("question") or qid,
                                  val if val else "（用户未给具体答案）"))
    if not lines:
        return ""
    return "\n".join(["用户的澄清回答："] + lines)


def build_stage_prompt(project: DevProject, stage: str, cites: list[dict],
                       pipeline: dict, extra: str = "") -> str:
    """拼出某个阶段的用户提示词。

    为什么要把上一阶段的产出带上：
        四个阶段是接力，不是四个独立任务 ——
        设计要基于需求规格，代码要基于设计。
        少了上一段，模型每次都在猜，猜出来的东西自然对不上。
    """
    parts = [_project_brief(project), "", "参考资料：", _knowledge_block(cites)]

    clarify = pipeline["stages"]["clarify"]
    specify = pipeline["stages"]["specify"]
    design = pipeline["stages"]["design"]

    if stage in ("specify", "design", "implement"):
        understanding = (clarify.get("data") or {}).get("understanding") or ""
        if understanding:
            parts += ["", "已确认的需求理解：", understanding]
        ans = _answers_block(clarify)
        if ans:
            parts += ["", ans]

    if stage in ("design", "implement"):
        spec = specify.get("data") or {}
        if spec:
            parts += ["", "需求规格（用户已审阅）：",
                      json.dumps(spec, ensure_ascii=False)[:4000]]

    if stage == "implement":
        d = design.get("data") or {}
        if d:
            parts += ["", "设计（用户已审阅）：",
                      json.dumps(d, ensure_ascii=False)[:4000]]

    if extra:
        parts += ["", "用户补充要求：", extra.strip()]

    return "\n".join(parts)


# ============ 模型调用（带重试与 JSON 抢救） ============

def _rescue_json(text: str) -> dict | None:
    """抢救被截断的 JSON。

    模型输出到 max_tokens 就会戛然而止，
    这时候 JSON 缺的不是「有效性」，而是「尾巴」——
    补齐括号、引号收尾就能救回来。
    直接报「生成失败」等于把用户的等待时间白扔了。
    """
    if not text:
        return None
    raw = text.strip()
    fence = chr(96) * 3
    m = re.search(re.escape(fence) + r"(?:json)?\s*(.*?)" + re.escape(fence), raw, re.S)
    if m:
        raw = m.group(1).strip()
    start = raw.find("{")
    if start < 0:
        return None
    raw = raw[start:]

    in_str = False
    escaped = False
    stack: list[str] = []
    end = -1
    for i, ch in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            if not stack:
                end = i
                break
    chunk = raw[:end + 1] if end > 0 else raw
    # 补齐没收尾的括号与引号
    if in_str:
        chunk += '"'
    chunk = chunk.rstrip()
    while stack:
        chunk += stack.pop()
    # 去掉尾逗号
    chunk = re.sub(r",\s*([}\]])", r"\1", chunk)
    for candidate in (chunk, raw):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _is_timeout(exc: Exception) -> bool:
    """判断这个异常是不是「等太久没等到」。

    为什么要自己认：httpx 的超时异常有好几种类型
    （ReadTimeout / WriteTimeout / PoolTimeout），
    但它们都不在标准库里，不 import 进来就会漏判。
    这里按类名与消息认，认错了最多少重试一次。
    """
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return True
    return "timeout" in str(exc).lower()


def _parse_or_rescue(text: str) -> dict | None:
    """先用 dev 模块的解析器，失败再抢救。

    dev.parse_json_block 是权威口径（那边正在加强），
    但它是「完整 JSON」的解析器 —— 截断的输出它救不回来。
    """
    data = dev_svc.parse_json_block(text)
    if isinstance(data, dict):
        return data
    return _rescue_json(text)


async def call_json(mode: str, system: str, user: str, cfg: dict, *,
                    what: str, max_tokens: int | None = None) -> tuple[dict, str]:
    """调模型并拿到一个 JSON 对象。

    这一层刻意**不自己实现**「重试 / 抢救 / 加额度」：
        那是 dev.call_model_json 的活儿（团队共用的口径）：
        它已经会做「被截断就抢救」「结构不对就把错处告诉模型让它重写」
        「额度被推理过程吃掉就自动加额度重来」。
        同一件事有两套脾气，最后没人说得清到底哪套在起作用。

    这里只负责两件流水线特有的事：
        1) 模型连回应都没有（读超时）时给用户一句人话，并把重试兜住；
        2) 把 dev 的错误翻译成流水线的错误（带上阶段名与处置建议）。

    返回 (数据, 模型原始输出)。
    """
    mx = int(max_tokens or (cfg.get("max_tokens") or 8192))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    for attempt in range(2):
        try:
            out = await dev_svc.call_model_json(mode, messages, cfg=cfg,
                                                max_tokens=mx, retries=1)
        except dev_svc.DevError as e:
            # 结构 / 解析类失败：dev 那边已经自己重试过了，如实报出去
            raise PipelineError(e.message, status=e.status,
                                missing=list(e.missing or []),
                                how_to_fix=list(e.how_to_fix or []),
                                detail=e.detail) from e
        except Exception as e:
            if not _is_timeout(e):
                raise
            # 模型连回应都没有（读超时）：
            # 一次超时就判死刑太冤 —— 重试一次通常就成了。
            if attempt == 0:
                mx = min(mx * 2, 32768)
                continue
            # 两次都超时：给一句人话，别把 httpx 的空异常甩给用户
            raise PipelineError(
                "%s：模型两次都没在时限内返回（每次 %d 秒以上）" % (what, int(mx)),
                status=504, missing=["model_response"],
                how_to_fix=[
                    "重跑该阶段（推理型模型偶尔会慢，重试通常就好了）",
                    "换一个更快的模型，或把这一阶段的产出规模调小",
                    "调大开发设置里的 max_tokens（额度不够时模型会一直在思考）",
                ],
                detail={"timeout": int(mx)}) from e
        data = out.get("data")
        if not isinstance(data, dict):
            # 共用层没救回来，再用自己的抢救器试一次：
            # 两套抢救逻辑的口径略有不同，多一手就多一分可能。
            data = _parse_or_rescue(out.get("text") or "")
        if not isinstance(data, dict):
            raise PipelineError(
                "%s：模型没有返回可解析的 JSON" % what,
                status=502, missing=["model_output"],
                how_to_fix=[
                    "重跑该阶段（输出可能被截断，可调大开发设置里的 max_tokens）",
                    "确认模型地址与模型名可用（开发设置 → 能力自检）",
                ],
                detail={"raw": (out.get("text") or "")[-800:]})
        return data, out.get("text") or ""
    raise PipelineError("%s：模型没有返回可解析的 JSON" % what,
                        status=502, missing=["model_output"],
                        how_to_fix=["重跑该阶段"], detail={})


async def call_json_with_timeout(mode: str, system: str, user: str,
                                cfg: dict, *, what: str,
                                max_tokens: int | None = None,
                                timeout: int | None = None) -> tuple:
    """带超时的模型调用。

    为什么要有超时：
        模型卡住（连着不回、也不报错）时，作业会永远停在 running，
        用户只能干等 —— 那不叫「进度可见」，叫「假装在忙」。
        超时之后如实报失败，并说清楚可以怎么办：
        重跑、调小产出规模、或者换个更快的模型。

    timeout：单次调用的时限（秒）。
        不传就用阶段时限（stage_timeout）。但「一次生成一个文件」这种
        细活儿有自己的时限（implement_file_timeout）——
        一个文件超时就跳过它，不该把整个阶段都拖死。
    """
    limit = int(timeout or cfg.get("stage_timeout") or 600)
    try:
        return await asyncio.wait_for(
            call_json(mode, system, user, cfg, what=what,
                      max_tokens=max_tokens),
            timeout=limit)
    except asyncio.TimeoutError:
        raise PipelineError(
            "%s：模型 %d 秒没有返回，已中止" % (what, limit),
            status=504, missing=["model_response"],
            how_to_fix=[
                "重跑该阶段（偶发卡死重试一次通常就好了）",
                "换一个更快的模型，或调小这一阶段的产出规模",
                "调大开发设置里的 stage_timeout（单位：秒）",
            ],
            detail={"timeout": limit})


# ============ 结构校验与归一 ============

def _as_text(value: Any) -> str:
    """把任意值变成一段文字。

    为什么需要它：模型经常把本该是字符串的字段（summary / architecture）
    给成对象或数组，代码按字符串取就会拿到 dict，
    渲染出来是 Python 字典的 repr —— 用户看到的是一坨括号。
    这里统一转成能读的文本，并让调用方知道「模型给的结构不对」。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                parts.append("%s：%s" % (k, json.dumps(v, ensure_ascii=False)))
            else:
                parts.append("%s：%s" % (k, v))
        return "；".join(parts)
    if isinstance(value, list):
        return "；".join(_as_text(v) for v in value if v is not None)
    return str(value)


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    return [value]


def _as_str_list(value: Any) -> list[str]:
    out = []
    for item in _as_list(value):
        text = _as_text(item).strip()
        if text:
            out.append(text)
    return out


def normalize_clarify(data: dict) -> tuple[dict, list[str]]:
    """归一 clarify 的输出，返回 (数据, 警告)。

    警告会写进阶段数据 —— 用户要能看见「模型这次给的结构不太对」，
    而不是系统悄悄把不对的地方修好了。
    """
    warnings: list[str] = []
    out: dict = {}
    understanding = data.get("understanding")
    if not isinstance(understanding, str):
        if understanding:
            warnings.append("understanding 不是字符串，已转成文本")
        understanding = _as_text(understanding)
    out["understanding"] = understanding
    out["assumptions"] = _as_str_list(data.get("assumptions"))

    questions = []
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list):
        if raw_questions:
            warnings.append("questions 不是数组，已归一成数组")
        raw_questions = _as_list(raw_questions)
    for i, q in enumerate(raw_questions, start=1):
        if not isinstance(q, dict):
            q = {"question": _as_text(q)}
        qid = str(q.get("id") or "").strip() or ("q%d" % i)
        question = _as_text(q.get("question")).strip()
        if not question:
            continue
        questions.append({
            "id": qid,
            "question": question,
            "why": _as_text(q.get("why")).strip(),
            "options": _as_str_list(q.get("options")),
            "allow_free": bool(q.get("allow_free", True)),
        })
    out["questions"] = questions
    if not out["understanding"] and not questions:
        warnings.append("模型没有给出需求理解也没有澄清问题")
    return out, warnings


def normalize_specify(data: dict) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    out: dict = {}
    stories = []
    raw_stories = data.get("stories")
    if not isinstance(raw_stories, list):
        if raw_stories:
            warnings.append("stories 不是数组，已归一成数组")
        raw_stories = _as_list(raw_stories)
    for i, s in enumerate(raw_stories, start=1):
        if not isinstance(s, dict):
            s = {"title": _as_text(s)}
        sid = str(s.get("id") or "").strip() or ("S%d" % i)
        title = _as_text(s.get("title")).strip()
        if not title:
            continue
        acc = s.get("acceptance")
        if not isinstance(acc, list):
            if acc:
                warnings.append("故事 %s 的 acceptance 不是数组，已归一成数组" % sid)
            acc = _as_list(acc)
        stories.append({
            "id": sid,
            "title": title,
            "as_a": _as_text(s.get("as_a")).strip(),
            "i_want": _as_text(s.get("i_want")).strip(),
            "so_that": _as_text(s.get("so_that")).strip(),
            "acceptance": [_as_text(a).strip() for a in acc if _as_text(a).strip()],
        })
    out["stories"] = stories
    out["nonfunctional"] = _as_str_list(data.get("nonfunctional"))

    data_model = []
    raw_dm = data.get("data_model")
    if not isinstance(raw_dm, list):
        if raw_dm:
            warnings.append("data_model 不是数组，已归一成数组")
        raw_dm = _as_list(raw_dm)
    for item in raw_dm:
        if not isinstance(item, dict):
            item = {"entity": _as_text(item), "fields": []}
        fields = item.get("fields")
        if isinstance(fields, list):
            norm_fields = []
            for f in fields:
                if isinstance(f, dict):
                    norm_fields.append(_as_text(f.get("name") or f.get("field")
                                                or json.dumps(f, ensure_ascii=False)))
                else:
                    norm_fields.append(_as_text(f))
            fields = [f for f in norm_fields if f]
        else:
            fields = _as_str_list(fields)
        entity = _as_text(item.get("entity")).strip()
        if not entity:
            continue
        data_model.append({"entity": entity, "fields": fields})
    out["data_model"] = data_model
    out["edge_cases"] = _as_str_list(data.get("edge_cases"))
    out["out_of_scope"] = _as_str_list(data.get("out_of_scope"))
    if not stories:
        warnings.append("模型没有给出任何用户故事")
    return out, warnings


def normalize_design(data: dict) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    out: dict = {}
    arch = data.get("architecture")
    if not isinstance(arch, str):
        if arch:
            warnings.append("architecture 不是字符串，已转成文本")
        arch = _as_text(arch)
    out["architecture"] = arch

    modules = []
    raw_modules = data.get("modules")
    if not isinstance(raw_modules, list):
        if raw_modules:
            warnings.append("modules 不是数组，已归一成数组")
        raw_modules = _as_list(raw_modules)
    for m in raw_modules:
        if not isinstance(m, dict):
            m = {"name": _as_text(m)}
        name = _as_text(m.get("name")).strip()
        if not name:
            continue
        modules.append({
            "name": name,
            "responsibility": _as_text(m.get("responsibility")).strip(),
            "depends_on": _as_str_list(m.get("depends_on")),
        })
    out["modules"] = modules

    tables = []
    raw_tables = data.get("data_tables")
    if not isinstance(raw_tables, list):
        if raw_tables:
            warnings.append("data_tables 不是数组，已归一成数组")
        raw_tables = _as_list(raw_tables)
    for t in raw_tables:
        if not isinstance(t, dict):
            t = {"name": _as_text(t), "columns": []}
        cols = []
        raw_cols = t.get("columns")
        if not isinstance(raw_cols, list):
            if raw_cols:
                warnings.append("表 %s 的 columns 不是数组，已归一成数组"
                                % _as_text(t.get("name")))
            raw_cols = _as_list(raw_cols)
        for c in raw_cols:
            if isinstance(c, dict):
                cols.append({"name": _as_text(c.get("name")).strip(),
                             "type": _as_text(c.get("type")).strip() or "TEXT"})
            else:
                cols.append({"name": _as_text(c).strip(), "type": "TEXT"})
        name = _as_text(t.get("name")).strip()
        if not name:
            continue
        tables.append({"name": name, "columns": cols})
    out["data_tables"] = tables

    apis = []
    raw_apis = data.get("apis")
    if not isinstance(raw_apis, list):
        if raw_apis:
            warnings.append("apis 不是数组，已归一成数组")
        raw_apis = _as_list(raw_apis)
    for a in raw_apis:
        if not isinstance(a, dict):
            a = {"path": _as_text(a)}
        method = _as_text(a.get("method")).strip().upper() or "GET"
        path = _as_text(a.get("path")).strip()
        if not path:
            continue
        apis.append({"method": method, "path": path,
                     "purpose": _as_text(a.get("purpose")).strip()})
    out["apis"] = apis
    out["risks"] = _as_str_list(data.get("risks"))
    if not out["architecture"]:
        warnings.append("模型没有给出架构说明")
    return out, warnings


def normalize_tasks(data: dict) -> tuple[list[dict], list[str]]:
    """把设计里的任务拆解归一成任务列表（depends_on 仍是下标）。

    任务最终要落 dev_task 表 —— 表里的 depends_on 存的是真实 task id，
    下标到 id 的翻译在写表时做。
    """
    warnings: list[str] = []
    raw = data.get("tasks")
    if not isinstance(raw, list):
        if raw:
            warnings.append("tasks 不是数组，已归一成数组")
        raw = _as_list(raw)
    tasks = []
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            t = {"title": _as_text(t)}
        title = _as_text(t.get("title")).strip()
        if not title:
            continue
        deps = []
        for d in _as_list(t.get("depends_on")):
            try:
                deps.append(int(d))
            except Exception:
                continue
        tasks.append({
            "title": title[:200],
            "description": _as_text(t.get("description")).strip(),
            "acceptance": _as_text(t.get("acceptance")).strip(),
            "depends_on": deps,
            "order": i,
        })
    if not tasks:
        warnings.append("模型没有给出任务拆解")
    return tasks, warnings
# ============ 产出物文件识别 ============

_LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".vue": "vue",
    ".go": "go", ".java": "java", ".kt": "kotlin", ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".swift": "swift", ".sql": "sql",
    ".sh": "shell", ".bash": "shell", ".ps1": "powershell",
    ".md": "markdown", ".txt": "text", ".rst": "text",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".env": "dotenv",
    ".html": "html", ".css": "css", ".scss": "scss",
    ".dockerfile": "dockerfile", ".lock": "text",
}


def _language_of(path: str) -> str:
    name = (path or "").lower()
    if name.endswith("dockerfile") or name.endswith("dockerfile.dev"):
        return "dockerfile"
    if name.startswith("makefile"):
        return "makefile"
    base = name.rsplit("/", 1)[-1]
    if "." not in base:
        return "text"
    ext = base[base.rfind("."):]
    return _LANG_BY_EXT.get(ext, "text")


def _artifact_type_of(path: str) -> str:
    """产出物类型：code / config / doc。

    为什么要分：前端按类型给不同的图标与操作
    （文档能预览、能入库，代码能跑安全体检）。
    """
    name = (path or "").lower()
    base = name.rsplit("/", 1)[-1]
    if base.endswith(".md") or base.endswith(".rst") or base.endswith(".txt"):
        return "doc"
    if base in ("dockerfile", "makefile") or base.endswith(".sh"):
        return "config"
    if base in ("requirements.txt", "package.json", "pyproject.toml",
                "poetry.lock", "package-lock.json", "yarn.lock",
                "go.mod", "go.sum", "cargo.toml", "pom.xml"):
        return "config"
    if base.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env")):
        return "config"
    return "code"


def _required_kinds(files: list) -> dict:
    """产出文件里齐不齐那五类必需文件。

    契约里写死了：缺 README / 依赖清单 / 入口 / 测试 / 启动脚本，
    就不算「可用的软件项目」—— 所以这里要能逐项判出来。
    """
    kinds = {"readme": False, "deps": False, "entry": False,
             "test": False, "start": False}
    for f in files:
        path = (f.get("path") or "").lower()
        base = path.rsplit("/", 1)[-1]
        if base in ("readme.md", "readme.rst", "readme.txt", "readme"):
            kinds["readme"] = True
        if base in ("requirements.txt", "package.json", "pyproject.toml",
                    "go.mod", "cargo.toml", "pom.xml"):
            kinds["deps"] = True
        if base in ("main.py", "app.py", "index.js", "index.ts", "server.py",
                    "main.go", "main.ts", "cli.py", "__main__.py"):
            kinds["entry"] = True
        if ("test" in base) and base.endswith((".py", ".js", ".ts", ".go")):
            kinds["test"] = True
        if base in ("dockerfile", "makefile", "start.sh", "run.sh",
                    "start.bat", "docker-compose.yml", "compose.yaml"):
            kinds["start"] = True
    return kinds


_STDLIB = {
    "abc", "argparse", "asyncio", "base64", "collections", "contextlib",
    "copy", "csv", "dataclasses", "datetime", "decimal", "difflib", "enum",
    "functools", "hashlib", "hmac", "http", "importlib", "inspect", "io",
    "itertools", "json", "logging", "math", "os", "pathlib", "pprint",
    "queue", "random", "re", "secrets", "shutil", "sqlite3", "string",
    "subprocess", "sys", "tempfile", "textwrap", "threading", "time",
    "traceback", "typing", "unittest", "uuid", "warnings", "xml", "zipfile",
}


def _scan_imports(files: list) -> list:
    """从生成的 Python 文件里扫第三方依赖。

    为什么要扫：模型常常不写 requirements.txt，
    但依赖清单是「能跑起来」的必要条件 ——
    宁可从代码里推出依赖清单，也不要让用户自己考古。
    """
    found = set()
    for f in files:
        if _language_of(f.get("path") or "") != "python":
            continue
        content = f.get("content") or ""
        pattern = r"^\s*(?:from\s+([A-Za-z0-9_]+)\s+import|import\s+([A-Za-z0-9_]+))"
        for m in re.finditer(pattern, content, re.M):
            mod = (m.group(1) or m.group(2) or "").split(".")[0]
            if mod and mod not in _STDLIB and mod not in ("app", "src"):
                found.add(mod)
    return sorted(found)


def _safe_rel_path(path: str) -> str:
    """把路径收拾成项目内相对路径（去掉绝对路径与上级目录）。"""
    p = str(path or "").strip().replace("\\", "/")
    while p.startswith("/"):
        p = p[1:]
    parts = [seg for seg in p.split("/") if seg and seg not in (".", "..")]
    return "/".join(parts)


def _synthesize_files(project: DevProject, pipeline: dict, files: list,
                       missing: list) -> list:
    """补齐模型没给全的必需文件。

    为什么允许补齐，而不是直接判失败：
        「生成的项目缺 README」对用户没有帮助 ——
        补一份骨架让项目能跑起来，用户能在骨架上继续改，
        比一句「生成失败，请重试」有用得多。
    但补出来的文件必须**说自己是补的**：
        骨架文件里会写明「这是流水线自动补齐的最小骨架」，
        不然用户会以为模型真的设计过这一部分。
    """
    out = []
    name = project.name or "项目"
    goal = project.goal or ""
    stack = _stack_text(project)
    fence = chr(96) * 3

    if "readme" in missing:
        file_list = "\n".join("- %s" % (f.get("path") or "") for f in files) or "-（暂无）"
        content = "\n".join([
            "# %s" % name,
            "",
            "> 这份 README 是流水线自动补齐的最小骨架（模型没有产出该文件），",
            "> 请按实际实现补全说明。",
            "",
            "## 项目简介",
            "",
            goal or "（项目目标未填写）",
            "",
            "## 技术栈",
            "",
            stack,
            "",
            "## 目录结构",
            "",
            fence,
            file_list,
            fence,
            "",
            "## 怎么跑",
            "",
            "1. 安装依赖：pip install -r requirements.txt（或按 package.json 安装）",
            "2. 启动：执行上面的入口文件，或执行 bash start.sh",
            "3. 测试：python -m pytest tests/",
            "",
            "## 已知限制",
            "",
            "- 本文件是自动补齐的骨架，细节以实际代码为准。",
            "",
        ])
        out.append({"path": "README.md",
                    "filename": "README.md", "language": "markdown",
                    "content": content, "artifact_type": "doc",
                    "source": "model", "synthesized": True})

    if "deps" in missing:
        deps = _scan_imports(files)
        content = ("\n".join(deps) + "\n" if deps else
                   "# 依赖清单由流水线自动补齐：当前代码未引入第三方依赖\n")
        out.append({"path": "requirements.txt",
                    "filename": "requirements.txt", "language": "text",
                    "content": content, "artifact_type": "config",
                    "source": "model", "synthesized": True})

    if "entry" in missing:
        langs = set(_language_of(f.get("path") or "") for f in files)
        if "python" in langs or not langs:
            content = "\n".join([
                '"""项目入口（流水线自动补齐的最小骨架）',
                "",
                "模型没有产出可运行入口，这里先给一个能跑起来的占位入口，",
                "请按实际实现替换。",
                '"""',
                "",
                "def main() -> None:",
                '    print("%s —— 入口待实现")' % name,
                "",
                "",
                'if __name__ == "__main__":',
                "    main()",
                "",
            ])
            out.append({"path": "main.py",
                        "filename": "main.py", "language": "python",
                        "content": content, "artifact_type": "code",
                        "source": "model", "synthesized": True})
        else:
            content = "\n".join([
                "// 项目入口（流水线自动补齐的最小骨架）",
                "// 模型没有产出可运行入口，这里先给一个能跑起来的占位入口，请按实际实现替换。",
                "",
                'console.log("%s —— 入口待实现");' % name,
                "",
            ])
            out.append({"path": "index.js",
                        "filename": "index.js", "language": "javascript",
                        "content": content, "artifact_type": "code",
                        "source": "model", "synthesized": True})

    if "test" in missing:
        content = "\n".join([
            '"""冒烟测试（流水线自动补齐的最小骨架）',
            "",
            "作用只有一个：证明这个项目「装得上、跑得起来」。",
            "真正的业务测试请另外补。",
            '"""',
            "import os",
            "import unittest",
            "",
            "",
            "class SmokeTest(unittest.TestCase):",
            "    def test_project_has_entry(self):",
            "        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
            '        entries = ["main.py", "app.py", "index.js", "server.py"]',
            "        found = [e for e in entries if os.path.exists(os.path.join(root, e))]",
            '        self.assertTrue(found, "项目里应该至少有一个入口文件")',
            "",
            "",
            'if __name__ == "__main__":',
            "    unittest.main()",
            "",
        ])
        out.append({"path": "tests/test_smoke.py",
                    "filename": "test_smoke.py", "language": "python",
                    "content": content, "artifact_type": "code",
                    "source": "model", "synthesized": True})

    if "start" in missing:
        content = "\n".join([
            "# 启动脚本（流水线自动补齐的最小骨架）",
            "# 模型没有产出启动脚本，这里给一份能用的：装依赖 -> 跑入口。",
            "set -e",
            'if [ -f requirements.txt ]; then pip install -r requirements.txt; fi',
            'if [ -f main.py ]; then python main.py; elif [ -f app.py ]; then python app.py; '
            'elif [ -f index.js ]; then node index.js; else echo "没有找到入口文件"; exit 1; fi',
            "",
        ])
        out.append({"path": "start.sh",
                    "filename": "start.sh", "language": "shell",
                    "content": content, "artifact_type": "config",
                    "source": "model", "synthesized": True})
    return out


# ============ 阶段实现 ============

async def _record_session(db: AsyncSession, project: DevProject, stage: str,
                          prompt: str, reply: str, model: str, mode: str,
                          cites: list) -> None:
    """把这次阶段调用记成会话与引用。

    为什么要有：流水线产出必须可追溯 ——
    「这段需求理解是哪次、哪个模型、参考了哪些知识生成的」，
    事后要能查得出来，不然用户没法判断该不该信它。
    """
    s = DevSession(
        project_id=project.id, kind="stage", prompt=(prompt or "")[:8000],
        context={"stage": stage}, reply=(reply or "")[:20000],
        model=model or "", mode=mode or "", status="done", notice="",
        created_at=_now())
    db.add(s)
    await db.commit()
    await db.refresh(s)
    for c in (cites or [])[:16]:
        db.add(DevCitation(
            session_id=s.id, artifact_id=None,
            kind=c.get("kind") or "gene", ref=c.get("ref") or "",
            title=c.get("title") or "", snippet=(c.get("snippet") or "")[:800],
            confidence=float(c.get("confidence") or 0), created_at=_now()))
    await db.commit()


class _Stepper:
    """作业进度推进器。

    为什么每步都写回数据库：
        一次模型调用可能几十秒，前端只能靠轮询知道「还活着」。
        不写回，进度条就会看起来卡住 —— 那正是这次要修的毛病。
    """

    def __init__(self, db: AsyncSession, job_id: int):
        self.db = db
        self.job_id = job_id
        self.processed = 0

    async def begin(self, text: str) -> None:
        await _update_job(self.db, self.job_id, current=text,
                          processed=self.processed)

    async def end(self) -> None:
        self.processed += 1
        await _update_job(self.db, self.job_id, processed=self.processed)


async def _update_job(db: AsyncSession, job_id: int, **fields) -> None:
    job = (await db.execute(
        select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
    if job is None:
        return
    for k, v in fields.items():
        setattr(job, k, v)
    await db.commit()


def _project_query(project: DevProject, extra: str = "") -> str:
    """检索用的查询串：项目名 + 目标 + 技术栈 + 补充要求。

    为什么补充要求也进检索：用户说「要跟现有订单系统对接」，
    这句话里的词往往正是知识库里那条经验的关键词。
    """
    parts = [project.name or "", project.goal or "", _stack_text(project),
             extra or ""]
    return " ".join(p for p in parts if p).strip()


async def _stage_clarify(db: AsyncSession, project: DevProject,
                         pipeline: dict, extra: str, step: _Stepper) -> dict:
    """阶段一：需求理解 —— 说清「我以为的需求是什么」，并提出要澄清的问题"""
    st = pipeline["stages"]["clarify"]
    st["status"] = "running"
    st["error"] = ""
    await save_pipeline(db, project, pipeline)

    await step.begin("检索相关知识")
    cites = await dev_svc.retrieve_knowledge(
        db, _project_query(project, extra), limit=8)
    await step.end()

    await step.begin("调用模型生成需求理解与澄清问题")
    prompt = build_stage_prompt(project, "clarify", cites, pipeline, extra)
    data, raw = await call_json_with_timeout(
        project.mode or dev_config.MODE_OFFLINE, CLARIFY_SYSTEM, prompt,
        dev_config.load_config(), what="需求理解阶段")
    await step.end()

    await step.begin("校验结构")
    norm, warnings = normalize_clarify(data)
    await step.end()

    await step.begin("保存阶段产出")
    st["data"] = norm
    st["at"] = _now_iso()
    st["error"] = ""
    if norm.get("questions"):
        # 有问题就还不能进下一段 —— 这是「需求理解」的意义所在
        st["status"] = "needs_input"
    else:
        st["status"] = "done"
    st["summary"] = stage_summary("clarify", st)
    pipeline["current_stage"] = first_unfinished(pipeline)
    await save_pipeline(db, project, pipeline)
    await _record_session(db, project, "clarify", prompt, raw,
                          "", project.mode or "", cites)
    await step.end()
    return {"questions": len(norm.get("questions") or []),
            "citations": len(cites), "warnings": warnings}


async def _stage_specify(db: AsyncSession, project: DevProject,
                         pipeline: dict, extra: str, step: _Stepper) -> dict:
    """阶段二：需求补全 —— 把需求写成可验收的规格"""
    st = pipeline["stages"]["specify"]
    st["status"] = "running"
    st["error"] = ""
    await save_pipeline(db, project, pipeline)

    await step.begin("检索相关知识")
    cites = await dev_svc.retrieve_knowledge(
        db, _project_query(project, extra), limit=8)
    await step.end()

    await step.begin("调用模型生成需求规格")
    prompt = build_stage_prompt(project, "specify", cites, pipeline, extra)
    data, raw = await call_json_with_timeout(
        project.mode or dev_config.MODE_OFFLINE, SPECIFY_SYSTEM, prompt,
        dev_config.load_config(), what="需求补全阶段")
    await step.end()

    await step.begin("校验结构")
    norm, warnings = normalize_specify(data)
    await step.end()

    await step.begin("保存阶段产出")
    st["data"] = norm
    st["at"] = _now_iso()
    st["status"] = "done"
    st["summary"] = stage_summary("specify", st)
    pipeline["current_stage"] = first_unfinished(pipeline)
    await save_pipeline(db, project, pipeline)
    await _record_session(db, project, "specify", prompt, raw,
                          "", project.mode or "", cites)
    await step.end()
    return {"stories": len(norm.get("stories") or []),
            "citations": len(cites), "warnings": warnings}


async def _stage_design(db: AsyncSession, project: DevProject,
                        pipeline: dict, extra: str, step: _Stepper) -> dict:
    """阶段三：需求转化 —— 架构、模块、表、接口，并把任务拆解写进任务表"""
    st = pipeline["stages"]["design"]
    st["status"] = "running"
    st["error"] = ""
    await save_pipeline(db, project, pipeline)

    await step.begin("检索相关知识")
    cites = await dev_svc.retrieve_knowledge(
        db, _project_query(project, extra), limit=8)
    await step.end()

    await step.begin("调用模型生成设计与任务拆解")
    prompt = build_stage_prompt(project, "design", cites, pipeline, extra)
    data, raw = await call_json_with_timeout(
        project.mode or dev_config.MODE_OFFLINE, DESIGN_SYSTEM, prompt,
        dev_config.load_config(), what="需求转化阶段")
    await step.end()

    await step.begin("校验结构")
    norm, warnings = normalize_design(data)
    tasks, task_warnings = normalize_tasks(data)
    warnings = warnings + task_warnings
    await step.end()

    await step.begin("写入任务表")
    task_ids = await _replace_pipeline_tasks(db, project, pipeline, tasks)
    await step.end()

    await step.begin("保存阶段产出")
    norm["task_ids"] = task_ids
    norm["warnings"] = warnings
    st["data"] = norm
    st["at"] = _now_iso()
    st["status"] = "done"
    st["summary"] = stage_summary("design", st)
    pipeline["current_stage"] = first_unfinished(pipeline)
    if project.status in ("draft", "planning"):
        project.status = "building"
    await save_pipeline(db, project, pipeline)
    await _record_session(db, project, "design", prompt, raw,
                          "", project.mode or "", cites)
    await step.end()
    return {"modules": len(norm.get("modules") or []),
            "tasks": len(task_ids), "citations": len(cites),
            "warnings": warnings}


async def _replace_pipeline_tasks(db: AsyncSession, project: DevProject,
                                   pipeline: dict, tasks: list) -> list:
    """把设计里的任务拆解写进 dev_task，依赖用真实 task id。

    只删「上一轮流水线写的」任务（id 记在阶段数据里），
    用户手工加的任务不动 —— 重跑设计不该把人家的活删了。
    """
    old_ids = ((pipeline["stages"]["design"].get("data") or {}).get("task_ids")
               or [])
    for tid in old_ids:
        try:
            old = await dev_svc.get_task(db, int(tid))
        except Exception:
            old = None
        if old is not None:
            try:
                await dev_svc.delete_task(db, old)
            except Exception as e:
                log.warning("删除旧任务失败 #%s：%s", tid, type(e).__name__)

    created = []
    id_by_index = {}
    for t in tasks:
        row = await dev_svc.create_task(db, project.id, {
            "title": t["title"],
            "description": t["description"],
            "acceptance": t["acceptance"],
            "status": "todo",
            "order": t["order"],
            "depends_on": [],
        })
        created.append(row)
        id_by_index[t["order"]] = row.id

    # 第二遍再填依赖：前序任务必须先有 id
    for t, row in zip(tasks, created):
        deps = []
        for d in t.get("depends_on") or []:
            dep_id = id_by_index.get(d)
            if dep_id and dep_id != row.id and dep_id not in deps:
                deps.append(dep_id)
        if deps:
            row.depends_on = deps
            row.updated_at = _now()
            await db.commit()
    return [row.id for row in created]


def _files_from_model(data: dict) -> list[dict]:
    """把模型给的 files 数组收成能落库的文件条目。

    为什么单独拎出来：分批问模型之后，每一批都要过这一遍，
    顺手把「路径不合法 / 内容为空」的挡在门外 ——
    落库的是真文件，不是一堆提示词里的占位符。
    """
    out = []
    raw_files = data.get("files")
    if not isinstance(raw_files, list):
        return out
    for f in raw_files:
        if not isinstance(f, dict):
            continue
        path = _safe_rel_path(f.get("path") or "")
        content = f.get("content") or ""
        if not path or not str(content).strip():
            continue
        out.append({
            "path": path,
            "filename": path.rsplit("/", 1)[-1],
            "content": str(content),
            "language": (f.get("language") or _language_of(path))[:32],
            "artifact_type": _artifact_type_of(path),
            "source": "model",
        })
    return out


async def _stage_implement(db: AsyncSession, project: DevProject,
                           pipeline: dict, extra: str, step: _Stepper) -> dict:
    """阶段四：项目生成 —— 一次一个文件、边生成边落盘

    为什么改成「一次一个文件」：
        之前的实现是一口气问模型要「一整套项目文件」（两批，每批 5 个）。
        推理型模型会把输出预算先花在思考上，正文写到一半就被截断
        （实测预算不够时 content 长度 0、finish_reason=length）——
        调大额度只是让它想得更久，用户等二十分钟拿一句「已中止」，
        体验上和坏掉没区别。
        改成一个文件一次调用之后：
          · 每次调用小而快，模型不容易被截断；
          · 每生成完一个立刻落库，中途失败只损失在飞的那一个；
          · 进度能说人话：「已生成 3/8 个文件：src/xxx.py」。

    文件清单从哪来：
        设计阶段拆出来的开发任务（dev_task 行）—— 任务就是文件，
        任务标题/说明/验收标准正好是「这个文件要写成什么样」的交代。
    """
    st = pipeline["stages"]["implement"]
    prev_status = st.get("status")
    st["status"] = "running"
    st["error"] = ""
    await save_pipeline(db, project, pipeline)

    await step.begin("组装上下文与文件清单")
    cites = await dev_svc.retrieve_knowledge(
        db, _project_query(project, extra), limit=6)
    prompt = build_stage_prompt(project, "implement", cites, pipeline, extra)
    tasks = await dev_svc.list_tasks(db, project.id)
    plan = _plan_items_from_tasks(tasks)
    # 上一轮留下的产出物：
    #   上一次是失败 → 续跑（已生成的文件留着，只补没生成的那几个）；
    #   上一次跑完了 → 重来（先清干净，别把两轮混在一起）。
    old_rows = await dev_svc.list_artifacts(db, project.id)
    resumed = prev_status == "failed" and bool(old_rows)
    done_task_ids = set()
    if resumed:
        done_task_ids = {r.get("task_id") for r in old_rows if r.get("task_id")}
    else:
        for r in old_rows:
            try:
                old = await dev_svc.get_artifact(db, int(r.get("id")))
            except Exception:
                old = None
            if old is None:
                continue
            try:
                await dev_svc.delete_artifact(db, old)
            except Exception as e:
                log.warning("删除旧产出物失败 #%s：%s", r.get("id"), type(e).__name__)
    await step.end()

    cfg = dev_config.load_config()
    mode = project.mode or dev_config.MODE_OFFLINE
    # 单文件的额度与时限都单独配：一次问得越小，模型越不容易把预算花在思考上。
    mx = int(cfg.get("implement_file_max_tokens") or 8192)
    tmo = int(cfg.get("implement_file_timeout") or 300)
    raw = ""
    notes = ""
    files: list = []
    artifact_ids: list = []
    generated = 0
    failed_count = 0
    failures: list = []
    total = len(plan)
    # 作业的总步数要跟着文件数走，否则进度条会走到 100% 以外。
    await _update_job(db, step.job_id,
                      total=len(STAGE_STEPS.get("implement") or []) + total)

    await step.begin("逐个生成文件")
    # 并发生成：模型调用同时跑，落库之后按计划顺序做。
    #
    # 为什么并发：
    #     实测一个文件要 3~9 分钟（推理型模型要想 + 写正文），
    #     8 个文件串行 = 25~70 分钟 —— 用户等一半就以为功能坏了。
    #     三路并发把总时长压到三分之一。
    #
    # 为什么落库不跟着一起并发：
    #     SQLite 同一时刻只允许一个写事务，并发写会互相踩；
    #     而且产出物的顺序跟计划一致，用户在界面上看着也顺。
    #     所以并发只加在「问模型」这一段（慢的那段），
    #     拿到内容之后按计划顺序一条条落库（快的那段）。
    #
    # 为什么并发度不是 8 路全开：
    #     模型服务有并发配额，超了会被限流，反而更慢甚至全挂；
    #     三路是「明显变快」与「不把模型端点打爆」之间的折中。
    conc = max(1, min(int(cfg.get("implement_concurrency") or IMPLEMENT_CONCURRENCY), 8))
    stage_limit = int(cfg.get("stage_timeout") or 600)
    from ..database import SessionLocal
    pending = [(i, item) for i, item in enumerate(plan, start=1)
               if item.get("task_id") not in done_task_ids]
    results: dict = {}
    done_count = 0
    ok_count = 0
    progress_lock = asyncio.Lock()

    async def _progress(text_of, ok: bool = False) -> None:
        """回写进度：完成一个算一个，不丢计数。

        为什么每个协程自己开连接写：
            AsyncSession 不是并发安全的，多个协程共用一个会话会互相踩。
            这里每个协程开一个短连接，只改作业那一行。
        为什么加锁：
            「计数 + 写回」必须是一个整体，否则两个协程交错写，
            后写的那个可能带着更小的数落库 —— 进度就会倒退、丢计数。
        """
        nonlocal done_count, ok_count
        async with progress_lock:
            done_count += 1
            if ok:
                ok_count += 1
                # 进度只有一份账：step.processed。
                # 另起一个计数器的话，阶段收尾时 step.end() 会拿一个
                # 比刚才小得多的数写回去 —— 进度条会从「已生成 6 个」倒回「2」，
                # 前端看着像越跑越慢（E2E 断言 processed 只增不减也会挂）。
                # 并发阶段主协程只在 gather 上等着，不会同时动它。
                # 只在「真的产出文件了」时 +1 —— 跟串行那版口径一致：
                # 没生成出来的文件不算完成的一步。
                step.processed += 1
            try:
                async with SessionLocal() as sdb:
                    await _update_job(sdb, step.job_id,
                                      processed=step.processed,
                                      current=text_of(done_count, ok_count))
            except Exception as e:
                log.warning("写进度失败：%s", type(e).__name__)

    queue = list(pending)

    async def _worker() -> None:
        """一个工人：从清单里领一个文件去问模型，领完接着领下一个。

        为什么是「领活」而不是「一人一个文件」：
            文件清单长短不一（有的任务模型慢、有的快），
            固定分配会让快的工人干等着 —— 谁先干完谁先领下一个，整体才压得平。
        为什么单个文件失败不重试：
            单文件时限已经按实测调宽（implement_file_timeout，实测一个文件 3~9 分钟），
            到这里基本是模型真的卡住了；再等一轮只是把「进度卡住」的时间翻倍。
            跳过的文件由「重跑只补剩下的」兜住 —— 那一轮只问缺的那几个。
        """
        while True:
            if not queue:
                return
            # 必需文件齐了就不必再问模型（模型有时一次给好几个文件）
            got = [f for r in results.values() for f in (r.get("files") or [])]
            if got and all(_required_kinds(got).values()):
                return
            idx, item = queue.pop(0)
            try:
                ask = IMPLEMENT_ONE_FILE % (item["title"], item["description"],
                                            item["acceptance"])
                data, raw_one = await call_json_with_timeout(
                    mode, IMPLEMENT_SYSTEM, prompt + ask, cfg,
                    what="生成文件「%s」" % item["title"],
                    max_tokens=mx, timeout=tmo)
                produced = _files_from_model(data)
                ok = bool(produced)
                results[idx] = {"ok": ok, "files": produced, "raw": raw_one,
                                "notes": _as_text(data.get("notes")),
                                "error": "" if ok else "模型没有返回文件内容"}
                await _progress(lambda d, o: "已生成 %d/%d 个文件：%s"
                                % (o, total, item["title"]), ok=ok)
            except Exception as e:
                # 这一整个文件就算没生成出来（模型挂了、超时了、返回看不懂了）：
                # 记下来、继续干下一个 —— 已经生成好的文件不受影响。
                results[idx] = {"ok": False, "error": _err_text(e), "raw": ""}
                await _progress(lambda d, o: "第 %d/%d 个文件没生成出来：%s"
                                % (idx, total, item["title"]))

    workers = [asyncio.create_task(_worker())
               for _ in range(min(conc, max(1, len(pending))))]
    timed_out = False
    try:
        await asyncio.wait_for(asyncio.gather(*workers, return_exceptions=True),
                               timeout=stage_limit)
    except asyncio.TimeoutError:
        # 整个阶段超时：在飞的那几个白等了，但已经拿到手的文件要留下 ——
        # 用户至少能导出一部分，下次重跑只补剩下的。
        timed_out = True
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    await step.end()

    # 落库：按计划的原顺序顺序执行（并发写 SQLite 会打架）。
    for idx, item in pending:
        res = results.get(idx)
        if not res:
            # 被掐掉的那一个（阶段超时）—— 不算失败，也不产出文件。
            continue
        if not res.get("ok"):
            failed_count += 1
            failures.append({"title": item["title"],
                             "error": res.get("error") or ""})
            log.warning("生成文件失败 %s：%s", item["title"], res.get("error"))
            continue
        raw += res.get("raw") or ""
        notes = notes or (res.get("notes") or "")
        for f in (res.get("files") or []):
            row = await dev_svc.create_artifact(db, project.id, {
                "filename": f["filename"],
                "path": f["path"],
                "content": f["content"],
                "language": f["language"],
                "artifact_type": f["artifact_type"],
                "source": "model",
                "warnings": f.get("warnings") or [],
            }, task_id=item.get("task_id"))
            f["artifact_id"] = row.id
            artifact_ids.append(row.id)
            files.append(f)
        generated += 1
    # 文件的进度在 _progress 里已经一个个加过了，
    # 这里不能再加一次（加两次作业进度会超过 total，前端进度条会顶到 100% 以外）。

    if timed_out:
        st["data"] = _implement_data(files, artifact_ids, [], blocked=None,
                                     failures=failures, notes=notes,
                                     version=int((st.get("data") or {}).get("version") or 0) + 1)
        st["summary"] = stage_summary("implement", st)
        await save_pipeline(db, project, pipeline)
        raise PipelineError(
            "项目生成阶段：整体超过 %d 秒还没跑完（已生成 %d/%d 个文件）"
            % (stage_limit, generated, total),
            status=504, missing=["implement_timeout"],
            how_to_fix=[
                "已生成 %d/%d 个文件，重跑只补剩下的（已生成的不会重做）"
                % (generated, total),
                "把开发设置里的 stage_timeout 调大一点",
                "或者调小 implement_concurrency（并发太高时模型会互相拖慢）",
            ],
            detail={"generated": generated, "total": total,
                    "failed": failures})



    if failed_count >= 2:
        # 单个文件失败不作废整段：已生成的文件留在产出物里（还能导出），
        # 阶段判失败，但要说清「已经拿到多少、怎么接着补」。
        #
        # 为什么是「一共挂 2 个」而不是「连着挂 2 个」：
        #     串行时「连着」是确定的 —— 第 3 个文件挂了就停手，后面的压根没问。
        #     并发之后所有文件都在飞，哪个文件挂取决于模型什么时候返回，
        #     「连着」不再有唯一答案（同一个模型、同一批文件，两次跑挂的
        #     可能不是同几个）。按总数判才说得清、也才稳定。
        #     对用户来说这反而更好：挂 2 个就重跑补上，
        #     拿到的是模型真写的文件，而不是自动合成的骨架。
        st["data"] = _implement_data(files, artifact_ids, [], blocked=None,
                                     failures=failures, notes=notes,
                                     version=int((st.get("data") or {}).get("version") or 0) + 1)
        st["summary"] = stage_summary("implement", st)
        await save_pipeline(db, project, pipeline)
        raise PipelineError(
            "项目生成阶段：有 %d 个文件没生成出来（已生成 %d/%d 个文件）"
            % (failed_count, generated, total),
            status=500, missing=["implement_files"],
            how_to_fix=[
                "已生成 %d/%d 个文件，重跑只补剩下的（已生成的不会重做）"
                % (generated, total),
                "没生成出来的文件：%s"
                % "、".join(str(f.get("title") or "") for f in failures[-3:]),
                "模型慢的话把开发设置里的 implement_file_timeout 调大一点",
                "也可以在开发工作台里手工补这几个文件",
            ],
            detail={"generated": generated, "total": total,
                    "failed": failures})

    await step.begin("补齐缺失的必需文件")
    kinds = _required_kinds(files)
    missing = [k for k, ok in kinds.items() if not ok]
    synthesized = []
    if missing:
        # 先让模型补（一个文件一次调用），补不上再合成骨架
        files.extend(await _repair_missing(project, pipeline, prompt, missing, cfg))
        kinds = _required_kinds(files)
        missing = [k for k, ok in kinds.items() if not ok]
        if missing:
            extra_files = _synthesize_files(project, pipeline, files, missing)
            for f in extra_files:
                synthesized.append(f["path"])
            files.extend(extra_files)
    await step.end()

    await step.begin("校验文件与安全")
    blocked = []
    kept = []
    for f in files:
        fname = f.get("filename") or (f.get("path") or "").rsplit("/", 1)[-1]
        warns = dev_svc.scan_code(f["content"], fname)
        if dev_svc.has_blocking(warns):
            blocked.append({"path": f["path"], "filename": fname,
                            "warnings": warns})
            # 已经有硬编码密钥的文件刚才是落过库的，这里要把它撤掉 ——
            # 产出物里不留带密钥的代码。
            aid = f.get("artifact_id")
            if aid:
                try:
                    old = await dev_svc.get_artifact(db, int(aid))
                    if old is not None:
                        await dev_svc.delete_artifact(db, old)
                except Exception as e:
                    log.warning("删除不安全产出物失败 #%s：%s", aid, type(e).__name__)
            continue
        f["warnings"] = warns
        kept.append(f)
    await step.end()

    await step.begin("保存产出物")
    # 模型生成的文件是边生成边落库的；
    # 「补齐」和「合成骨架」出来的那几个还没落库 —— 这里补上，
    # 少了它们，导出 ZIP 就会缺文件（少了 README，用户拿到手是个空壳）。
    kept_ids = []
    for f in kept:
        aid = f.get("artifact_id")
        if not aid:
            row = await dev_svc.create_artifact(db, project.id, {
                "filename": f.get("filename")
                or (f.get("path") or "").rsplit("/", 1)[-1],
                "path": f["path"],
                "content": f["content"],
                "language": f.get("language") or "",
                "artifact_type": f.get("artifact_type") or "code",
                "source": f.get("source") or "model",
                "warnings": f.get("warnings") or [],
            })
            aid = row.id
            f["artifact_id"] = aid
        kept_ids.append(aid)
    await step.end()
    st["data"] = _implement_data(files, kept_ids, synthesized, blocked,
                                 failures=failures, notes=notes,
                                 version=int((st.get("data") or {}).get("version") or 0) + 1)
    st["at"] = _now_iso()
    st["status"] = "done"
    st["summary"] = stage_summary("implement", st)
    pipeline["current_stage"] = first_unfinished(pipeline)
    if project.status in ("draft", "planning", "building"):
        project.status = "produced"
    await save_pipeline(db, project, pipeline)
    await _record_session(db, project, "implement", prompt, raw,
                          "", project.mode or "", cites)
    return {"files": len(kept), "synthesized": len(synthesized),
            "blocked": len(blocked), "citations": len(cites),
            "generated": generated, "failed": len(failures)}


def _implement_data(files: list, artifact_ids: list, synthesized: list,
                    blocked, *, failures: list, notes: str, version: int) -> dict:
    """项目生成阶段的产出数据（清单 + 产出物 id + 失败的文件）。"""
    return {
        "files": [{"path": f["path"], "filename": f["filename"],
                   "language": f["language"], "artifact_type": f["artifact_type"],
                   "size": len(f["content"].encode("utf-8", "replace"))}
                  for f in files],
        "artifact_ids": [i for i in artifact_ids if i],
        "synthesized": synthesized,
        "blocked": blocked or [],
        "failed_files": failures or [],
        "version": version,
        "notes": notes,
    }


def _plan_items_from_tasks(tasks: list) -> list:
    """把设计阶段拆出来的开发任务变成「要生成的文件清单」。

    为什么用任务而不是让模型自己列文件：
        任务就是文件（一个任务对应一个可交付的文件），
        任务标题、说明、验收标准正好是「这个文件要写成什么样」的交代 ——
        一次只交代一件事，模型不容易跑偏，也不容易写一半。
    """
    items = []
    for t in tasks or []:
        title = (t.get("title") or "").strip()
        if not title:
            continue
        items.append({
            "task_id": t.get("id"),
            "title": title,
            "description": (t.get("description") or "").strip(),
            "acceptance": (t.get("acceptance") or "").strip(),
        })
    return items


def _err_text(e: Exception) -> str:
    """把异常说成人话（错误体里要能看到到底卡在哪）。"""
    msg = getattr(e, "message", None) or str(e) or type(e).__name__
    return str(msg)[:200]



async def _repair_missing(project: DevProject, pipeline: dict, prompt: str,
                           missing: list, cfg: dict) -> list:
    """让模型补齐缺的那几类文件 —— 一类一次调用。

    为什么一类一次：
        跟主流程一个道理：一次只交代一件事，模型不容易写一半、
        不容易把预算花在思考上。缺几类就问几次，某一次失败不影响别的。

    为什么先补再合成：模型多半只是漏了几份，
    让它自己补出来的比流水线合成的更贴项目；
    合成是最后兜底。
    """
    kind_labels = {
        "readme": "README.md（怎么装、怎么跑、怎么测）",
        "deps": "依赖清单（requirements.txt 或 package.json）",
        "entry": "一个可运行的入口文件",
        "test": "至少一个测试文件",
        "start": "启动脚本或 Dockerfile",
    }
    kind_hints = {
        "readme": "写清楚：项目做什么、怎么装依赖、怎么启动、怎么跑测试。",
        "deps": "列出运行这个项目需要的第三方依赖，一行一个。",
        "entry": "一个能直接跑起来的入口文件。",
        "test": "至少一个能跑的测试文件（内容要真的能跑）。",
        "start": "一个启动脚本或 Dockerfile，能把项目跑起来。",
    }
    mx = int(cfg.get("implement_file_max_tokens") or 8192)
    tmo = int(cfg.get("implement_file_timeout") or 300)
    out = []
    for kind in missing:
        label = kind_labels.get(kind, kind)
        ask = IMPLEMENT_KIND_FILE % (label, kind_hints.get(kind, ""))
        try:
            data, _raw = await call_json_with_timeout(
                project.mode or dev_config.MODE_OFFLINE, IMPLEMENT_SYSTEM,
                prompt + ask, cfg, what="补齐%s" % label,
                max_tokens=mx, timeout=tmo)
        except Exception as e:
            log.warning("补齐%s失败：%s", label, type(e).__name__)
            continue
        for f in (data.get("files") or []):
            if not isinstance(f, dict):
                continue
            path = _safe_rel_path(f.get("path") or "")
            content = str(f.get("content") or "")
            if not path or not content.strip():
                continue
            out.append({
                "path": path,
                "filename": path.rsplit("/", 1)[-1],
                "content": content,
                "language": (f.get("language") or _language_of(path))[:32],
                "artifact_type": _artifact_type_of(path),
                "source": "model",
            })
    return out


_STAGE_RUNNERS = {
    "clarify": _stage_clarify,
    "specify": _stage_specify,
    "design": _stage_design,
    "implement": _stage_implement,
}


# ============ 后台作业 ============

async def run_stage_job(job_id: int, project_id: int, stage: str, *,
                        extra: str = "", force: bool = False) -> None:
    """后台跑一个流水线阶段，进度写回 dna_job。

    为什么作业的 total 是「该阶段的真实步骤数」：
        前端进度条按 processed/total 算百分比。
        total 写 1 或 0，前端就只能显示「进行中」或假的 50%。
    """
    from ..database import SessionLocal
    steps = STAGE_STEPS.get(stage) or ["执行阶段"]
    async with SessionLocal() as db:
        job = (await db.execute(
            select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
        if job is None:
            return
        job.status = "running"
        job.started_at = _now()
        job.total = len(steps)
        job.processed = 0
        job.current = steps[0]
        job.error = None
        await db.commit()

    try:
        async with SessionLocal() as db:
            project = await dev_svc.get_project(db, project_id)
            if project is None:
                await _update_job(db, job_id, status="failed",
                                  error="项目不存在", finished_at=_now())
                return
            pipeline = get_pipeline(project)
            # 闸门在这里再查一次：
            # 前端可能拿着旧状态点了「运行」，不能等跑起来才发现过不去
            check_gate(pipeline, stage, force=force)
            step = _Stepper(db, job_id)
            runner = _STAGE_RUNNERS[stage]
            summary = await runner(db, project, pipeline, extra, step)
            await _update_job(
                db, job_id, status="done", processed=step.processed, current="",
                finished_at=_now(),
                created=int(summary.get("files") or summary.get("tasks") or 0),
                detail=summary)
    except dev_svc.DevError as e:
        async with SessionLocal() as db:
            await _update_job(db, job_id, status="failed", error=e.message[:500],
                              finished_at=_now(),
                              detail={"missing": e.missing,
                                      "how_to_fix": e.how_to_fix,
                                      "extra": e.detail})
            # 阶段状态也要标失败，否则界面会一直转圈
            project = await dev_svc.get_project(db, project_id)
            if project is not None:
                pipeline = get_pipeline(project)
                st = pipeline["stages"].get(stage) or {}
                if st.get("status") == "running":
                    st["status"] = "failed"
                    st["error"] = e.message
                    st["summary"] = stage_summary(stage, st)
                    pipeline["current_stage"] = first_unfinished(pipeline)
                    await save_pipeline(db, project, pipeline)
    except Exception as e:
        log.exception("流水线阶段作业失败 job=%s stage=%s", job_id, stage)
        async with SessionLocal() as db:
            # 兜底分支也要说清「怎么修」：
            # 连接被掐断、连接池满了这类毛病走不到 DevError，
            # 如果这里只写一句 error，用户看到的就是天书 ——
            # 契约 §4.3 要求失败时错误与处置建议一起给出来。
            await _update_job(db, job_id, status="failed",
                              error=("%s: %s" % (type(e).__name__, e))[:500],
                              finished_at=_now(),
                              detail={"missing": ["model_connection"],
                                      "how_to_fix": [
                                          "重跑该阶段（偶发断连，重试一次通常就好了）",
                                          "确认模型端点可用（开发设置 → 能力自检）",
                                          "频繁断连的话检查网络/代理，或换个模型端点",
                                      ],
                                      "extra": {}})
            project = await dev_svc.get_project(db, project_id)
            if project is not None:
                pipeline = get_pipeline(project)
                st = pipeline["stages"].get(stage) or {}
                if st.get("status") == "running":
                    st["status"] = "failed"
                    st["error"] = ("%s: %s" % (type(e).__name__, e))[:500]
                    st["summary"] = stage_summary(stage, st)
                    pipeline["current_stage"] = first_unfinished(pipeline)
                    await save_pipeline(db, project, pipeline)


# ============ 提交答案 / 编辑产出 ============

async def answer_stage(db: AsyncSession, project: DevProject, stage: str, *,
                       answers: dict | None = None, notes: str = "",
                       data: dict | None = None) -> dict:
    """提交澄清答案，或修订某一阶段的产出。

    clarify 用 answers：所有问题都答了才放行到下一阶段。
    specify / design 用 notes（可选再带 data 覆盖字段）。
    """
    if stage not in STAGES:
        raise PipelineError("阶段只能是 %s" % " / ".join(STAGES),
                            status=400, missing=["stage"],
                            how_to_fix=["检查阶段名"])
    pipeline = get_pipeline(project)
    st = pipeline["stages"][stage]

    if stage == "clarify":
        if st.get("status") == "pending" and not (st.get("data") or {}).get("questions"):
            raise PipelineError(
                "「需求理解」还没跑过，先跑一次再回答",
                status=409, missing=["clarify"],
                how_to_fix=["先执行「需求理解」阶段，模型提问之后再回答"])
        merged = dict(st.get("answers") or {})
        merged.update(answers or {})
        st["answers"] = merged
        pending = unanswered_questions(st)
        if not pending:
            st["status"] = "done"
        elif st.get("status") in ("pending", "failed", "running"):
            st["status"] = "needs_input"
    else:
        if notes:
            st["notes"] = notes
        if isinstance(data, dict) and data:
            merged_data = dict(st.get("data") or {})
            merged_data.update(data)
            st["data"] = merged_data
        if st.get("data"):
            # 有产出就视为已审阅：specify/design 的闸门在这里打开
            st["status"] = "done"
        if notes:
            st["at"] = _now_iso()

    st["summary"] = stage_summary(stage, st)
    pipeline["current_stage"] = first_unfinished(pipeline)
    await save_pipeline(db, project, pipeline)
    return pipeline


# ============ 导出 ============

def _zip_dir_name(name: str) -> str:
    """ZIP 里的顶层目录名：去掉路径分隔符与空格。"""
    cleaned = re.sub(r"[\\/:\*\?\"\<\>\|]", "", name or "").strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    return (cleaned or "project")[:80]


async def export_project_zip(db: AsyncSession, project: DevProject):
    """打包成 ZIP：顶层一层项目目录，里面是全部产出物。

    没有产出物就返回 409 —— 给一个空 ZIP 没有意义，
    应该说清楚「先去跑项目生成」。
    """
    pipeline = get_pipeline(project)
    st = pipeline["stages"]["implement"]
    rows = (await db.execute(
        select(DevArtifact).where(DevArtifact.project_id == project.id)
        .order_by(DevArtifact.id))).scalars().all()
    if not rows:
        raise PipelineError(
            "这个项目还没有可导出的产出物，先跑「项目生成」阶段",
            status=409, missing=["implement"],
            how_to_fix=["依次跑完需求理解、需求补全、需求转化，然后执行项目生成"])
    data = st.get("data") or {}
    version = int(data.get("version") or 1)
    top = _zip_dir_name(project.name)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        has_readme = False
        # 同一个路径只写一份。
        # 为什么：模型给不同任务选文件名时经常撞车
        # （实测 backend/app/main.py 在一个项目里出现过 3 次），
        # ZIP 里就会有三个同名条目 —— 解压时只有最后一个算数，
        # 用户看着一坨重复文件会以为出错了。保留最后生成的那份。
        latest: dict = {}
        for a in rows:
            path = _safe_rel_path(a.path or a.filename or "file.txt")
            if not path:
                continue
            latest[path] = a
        if len(latest) != len([r for r in rows
                               if _safe_rel_path(r.path or r.filename or "file.txt")]):
            log.info("导出 %s：同名路径的文件只保留最新的一份", project.name)
        for path, a in latest.items():
            if path.lower().rsplit("/", 1)[-1].startswith("readme"):
                has_readme = True
            zf.writestr("%s/%s" % (top, path), a.content or "")
        if not has_readme:
            zf.writestr("%s/README.md" % top,
                        "# %s\n\n（导出时没有找到 README，请检查项目生成阶段产出）\n"
                        % (project.name or "项目"))
    filename = "%s-v%d.zip" % (top, version)
    return buf.getvalue(), filename
