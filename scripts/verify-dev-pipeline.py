#!/usr/bin/env python3
"""软件开发四阶段流水线（clarify / specify / design / implement）后端自检

为什么要有这个脚本：
    「跑不通」这件事本身没法交付。能交付的是**一串能跑的断言**：
    改了 max_tokens、改了提示词、改了闸门判定之后，
    这串断言能立刻告诉你是修好了还是改坏了。
    它只验后端逻辑：不依赖真实大模型，也不碰线上库。

离线跑，不碰线上库：
  docker run --rm -i -v "$PWD/backend/app:/app/app:ro" \
    --entrypoint python kb-workbench-backend - < scripts/verify-dev-pipeline.py

验十五件事：
  1. GET 流水线返回四阶段结构 + 闸门；
  2. 闸门没过就 409（先拒绝，不许「先跑再失败」）；
  3. 作业 total 是该阶段的真实步骤数，processed 每步写回（不再有假的 50%）；
  4. 澄清问题必须人回答，回答完才放行下一阶段；
  5. 需求规格、设计按契约的字段落库（字段名不许改）；
  6. 任务拆解落 dev_task，depends_on 是真实 task id；
  7. 项目生成产出真文件（README / 依赖清单 / 入口 / 测试 / 启动脚本）；
  8. 导出 ZIP 含顶层目录与 README.md；没有产出时 409；
  9. 提示词带 schema、不许改技术栈；模型输出被截断时能抢救。

模型用的是脚本里起的一个本地 mock（OpenAI 兼容），
所以整个自测不依赖外网、不消耗额度。
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOCKER_CMD = ('docker run --rm -i -v "$PWD/backend/app:/app/app:ro" '
              '--entrypoint python kb-workbench-backend - '
              '< scripts/verify-dev-pipeline.py')

if sys.version_info < (3, 10):
    raise SystemExit("需要 Python 3.10+。请在容器里跑：\n    %s" % DOCKER_CMD)

_HERE = globals().get("__file__") and os.path.dirname(os.path.abspath(__file__)) or ""
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend") if _HERE else ""
if _BACKEND and os.path.isdir(_BACKEND):
    sys.path.insert(0, _BACKEND)

_TMP = tempfile.mkdtemp(prefix="kb-dev-pipeline-verify-")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(_TMP, "kb.db")
os.environ["DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["FILE_STORE_DIR"] = os.path.join(_TMP, "files")
os.environ["KB_DEV_CONFIG"] = os.path.join(_TMP, "dev_config.json")
os.environ["AUTH_ENABLED"] = "false"
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["FILE_STORE_DIR"], exist_ok=True)

FAILURES = []
CHECKS = 0


def check(cond, label):
    global CHECKS
    CHECKS += 1
    if cond:
        print("  \u2713 %s" % label)
    else:
        print("  \u2717 %s" % label)
        FAILURES.append(label)
    return bool(cond)


# ============ 本地 mock 模型（OpenAI 兼容） ============

MOCK_CALLS = []
MOCK_MODE = {"fail": False}
# 项目生成阶段的调用计数：用来验「一个文件一次调用」。
MOCK_STATS = {"implement": 0, "implement_one": 0, "implement_repair": 0}

CLARIFY_OUT = {
    "understanding": "给客服用的工单系统：录入工单、跟踪状态、统计工作量",
    "assumptions": ["单租户内网使用", "不做审批流"],
    "questions": [
        {"id": "q1", "question": "工单从哪来？",
         "why": "决定要不要做导入与幂等",
         "options": ["人工录入", "外部系统推送"], "allow_free": True},
        {"id": "q2", "question": "谁统计工作量？",
         "why": "决定要不要做导出",
         "options": ["客服主管", "运营"], "allow_free": False},
    ],
}

SPECIFY_OUT = {
    "stories": [
        {"id": "S1", "title": "录入工单", "as_a": "客服",
         "i_want": "录入一条工单", "so_that": "能统计工作量",
         "acceptance": ["必填：标题、负责人", "保存后列表可见"]},
    ],
    "nonfunctional": ["性能：列表查询 P95 < 500ms"],
    "data_model": [{"entity": "Ticket", "fields": ["id", "title", "owner", "status"]}],
    "edge_cases": ["同名多条工单"],
    "out_of_scope": ["工单审批流"],
}

DESIGN_OUT = {
    "architecture": "FastAPI + SQLite：路由层 -> 服务层 -> 仓储层",
    "modules": [{"name": "tickets", "responsibility": "工单增删改查", "depends_on": []}],
    "data_tables": [{"name": "ticket",
                     "columns": [{"name": "id", "type": "INTEGER"},
                                 {"name": "title", "type": "TEXT"}]}],
    "apis": [{"method": "POST", "path": "/api/tickets", "purpose": "新建工单"}],
    "risks": ["导出百万行会占内存"],
    "tasks": [
        {"title": "搭骨架", "description": "建目录与配置",
         "acceptance": "能跑起来并打印一行 hello", "depends_on": []},
        {"title": "实现工单模型", "description": "建表与模型",
         "acceptance": "能存能取", "depends_on": [0]},
        {"title": "实现接口", "description": "写路由",
         "acceptance": "POST 能建工单", "depends_on": [1]},
        # 第四个任务是有意加的：
        #   「第 3 个文件失败时前 2 个还在」这个用例需要**连续两个**文件失败，
        #   而实现的口径是「连续 2 个失败才判阶段失败」——
        #   任务只有 3 个的话只会失败 1 个，测不到那条路径。
        {"title": "写使用说明", "description": "补文档",
         "acceptance": "README 写清怎么跑", "depends_on": [2]},
    ],
}

IMPLEMENT_OUT = {
    "files": [
        {"path": "backend/app/main.py", "language": "python",
         "content": "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n"
                    "@app.get('/api/health')\ndef health():\n    return {'ok': True}\n"},
        {"path": "backend/requirements.txt", "language": "text",
         "content": "fastapi\nuvicorn\n"},
        {"path": "README.md", "language": "markdown",
         "content": "# 工单系统\n\n怎么装、怎么跑、怎么测。\n"},
        {"path": "tests/test_api.py", "language": "python",
         "content": "def test_health():\n    assert True\n"},
        {"path": "Dockerfile", "language": "dockerfile",
         "content": "FROM python:3.12-slim\nCMD [\"python\", \"backend/app/main.py\"]\n"},
    ],
    "notes": "最小可运行骨架",
}


def _implement_reply(user_text):
    """项目生成阶段回一个文件。

    为什么只回一个文件：
        新的实现是「一个文件一次调用」（文件清单来自设计阶段拆出来的任务）。
        mock 要是每次都回一整套文件，测试就测不出「一次一个文件」这件事了。
        提示词里写了「要写的文件：<任务标题>」—— 就照它回一个同名文件。
        万一没解析出来（提示词改了），退回回一整套 —— 旧实现也能测。
    """
    title = ""
    for line in (user_text or "").splitlines():
        line = line.strip()
        if line.startswith("要写的文件："):
            title = line[len("要写的文件："):].strip()
            break
    if not title:
        return IMPLEMENT_OUT
    return {
        "files": [{"path": "%s.py" % title, "language": "python",
                   "content": "# %s\n\ndef main():\n    return '%s'\n"
                              % (title, title)}],
        "notes": "按任务「%s」生成" % title,
    }


class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length or 0)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {}
        MOCK_CALLS.append(payload)
        if MOCK_MODE.get("broken"):
            # 直接把连接掐掉：模拟「模型服务崩了 / 连接被中断」。
            # 这条路和「模型答得不好」是两回事 ——
            # 前者该给的是「网络/服务」的话术，后者是「内容不合格」的话术。
            self.close_connection = True
            try:
                self.connection.close()
            except Exception:
                pass
            return
        system = ""
        user = ""
        for m in payload.get("messages") or []:
            if m.get("role") == "system":
                system += str(m.get("content") or "")
            if m.get("role") == "user":
                user += str(m.get("content") or "")
        if MOCK_MODE.get("fail"):
            content = "这完全不是 JSON，只是一段闲聊。"
        elif "做需求理解" in system:
            content = json.dumps(CLARIFY_OUT, ensure_ascii=False)
        elif "可验收的规格" in system:
            content = json.dumps(SPECIFY_OUT, ensure_ascii=False)
        elif "资深软件架构师" in system:
            content = json.dumps(DESIGN_OUT, ensure_ascii=False)
        elif "真实可运行" in system:
            MOCK_STATS["implement"] += 1
            nth = MOCK_STATS["implement"]
            fail_from = int(MOCK_MODE.get("implement_fail_from") or 0)
            if fail_from and nth >= fail_from:
                # 模拟「第 N 个文件开始，模型调不通」：
                # 真实的模型服务出错时就是这样返回的。
                err = json.dumps({"error": {"message": "model overloaded"}},
                                 ensure_ascii=False).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return
            # 分开记两类调用：
            #   「要写的文件：」= 主流程一个文件一次调用；
            #   「只补一个文件」 = 补齐必需文件那几类。
            #   混在一起数就看不出「一个文件一次调用」了。
            if "要写的文件：" in user:
                MOCK_STATS["implement_one"] += 1
            else:
                MOCK_STATS["implement_repair"] += 1
            content = json.dumps(_implement_reply(user), ensure_ascii=False)
        else:
            content = json.dumps({"answer": "不知道"}, ensure_ascii=False)
        body = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_mock():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return "http://127.0.0.1:%d/v1/chat/completions" % srv.server_address[1], srv


def _shim_docindex_ttlcache():
    """测试期兼容垫片：docindex 重构中，embedding 还指着老地方。"""
    try:
        from app.services import docindex
    except Exception:
        return "skip"
    if hasattr(docindex, "TTLCache"):
        return "present"

    class _TTLCache:
        def __init__(self, max_size=128, ttl=60.0):
            self.max_size = max_size
            self.ttl = ttl
            self._d = {}

        def get(self, key, default=None):
            item = self._d.get(key)
            if item is None:
                return default
            value, expire_at = item
            if expire_at and expire_at < time.time():
                self._d.pop(key, None)
                return default
            return value

        def put(self, key, value):
            self._d[key] = (value, (time.time() + self.ttl) if self.ttl else 0)

        def clear(self):
            self._d.clear()

    docindex.TTLCache = _TTLCache
    return "shimmed"


# ============ 纯逻辑自检：不 import 整个应用 ============

def load_funcs(path, names):
    """只抽取要测的函数与常量，不 import 整个模块。

    为什么不直接 import：
        dev_pipeline 一 import 就把 config / 数据库 / ai_config 一堆依赖拉起来，
        自检脚本只想验三个纯逻辑（闸门状态机、阶段顺序、阶段完成判定），
        不该被那些副作用绊倒 —— 更不该要求机器上装齐全部依赖才能跑这段。
    手法照 scripts/verify-dev-model-calls.py：用 ast 把源码切出来单独 exec。
    """
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)

    class _PipelineError(Exception):
        """dev_pipeline.PipelineError 的最小替身。

        只为让被抽出来的纯函数能抛得出一个带状态码的错误 ——
        这里验的是「抛不抛、抛的时候带不带得上原因」，不是错误类本身。
        """

        def __init__(self, message, status=400, missing=None,
                     how_to_fix=None, detail=None):
            super().__init__(message)
            self.status = status
            self.missing = missing or []
            self.how_to_fix = how_to_fix or []
            self.detail = detail or {}

    ns = {"PipelineError": _PipelineError, "__name__": "dev_pipeline_stub"}
    got = set()
    consts = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        ns[target.id] = ast.literal_eval(node.value)
                        consts.add(target.id)
                    except (ValueError, SyntaxError):
                        pass
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            pre = "from __future__ import annotations" + chr(10)
            exec(compile(pre + ast.get_source_segment(src, node),
                         "<dev_pipeline>", "exec"), ns)
            got.add(node.name)
    return ns, got, consts


def find_dev_pipeline_source():
    """找出 dev_pipeline.py 的源码路径。

    这个脚本在两种地方跑：
      · 容器里（piped 进 stdin）：代码在 /app/app/services/；
      · 宿主机上：代码在仓库的 backend/app/services/。
    两种都得能找到，所以挨个试。
    """
    cands = []
    if _HERE:
        # _HERE 是 scripts 目录，仓库根在它上面一层
        repo_root = os.path.dirname(_HERE)
        cands.append(os.path.join(repo_root, "backend", "app", "services",
                                "dev_pipeline.py"))
    cands.append("/app/app/services/dev_pipeline.py")
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""


def pure_logic_checks(path):
    """闸门状态机 / 阶段顺序 / 阶段完成判定 —— 三件事各自钉死。

    这段是纯函数级的：不需要数据库、不需要模型、不需要网络。
    它比「跑一遍接口」更快更稳，适合每次改动后立刻跑一遍。
    """
    if not path or not os.path.isfile(path):
        print("  - 跳过纯逻辑自检（找不到 dev_pipeline.py 源码）")
        return
    ns, got, consts = load_funcs(path, {
        "empty_pipeline", "first_unfinished", "gates_of",
        "unanswered_questions", "check_gate"})
    check(got == {"empty_pipeline", "first_unfinished", "gates_of",
                 "unanswered_questions", "check_gate"},
          "纯逻辑函数都抽出来了（闸门/阶段顺序/阶段完成判定）")
    if not got:
        return

    stages = ns.get("STAGES")
    check(tuple(stages or ()) == ("clarify", "specify", "design", "implement"),
          "阶段顺序固定：需求理解 → 需求补全 → 需求转化 → 项目生成（%s）"
          % (stages,))

    steps = ns.get("STAGE_STEPS") or {}
    check(all(k in steps for k in (stages or ())),
          "四个阶段都有真实步骤表（作业 total 的来源）")
    check(all(len(steps.get(k) or []) > 0 for k in (stages or ())),
          "每个阶段至少一步（total 不会是 0 → 不会有假的 50%）")

    empty = ns["empty_pipeline"]()
    check(empty.get("current_stage") == "clarify",
          "空流水线的当前阶段是 clarify")
    check(all((empty["stages"][k].get("status") == "pending")
              for k in (stages or ())),
          "空流水线四个阶段都是 pending")

    first = ns["first_unfinished"]
    pl = ns["empty_pipeline"]()
    check(first(pl) == "clarify", "第一个没做完的阶段是 clarify")
    pl["stages"]["clarify"]["status"] = "done"
    check(first(pl) == "specify", "clarify 完成后轮到 specify")
    pl["stages"]["specify"]["status"] = "done"
    pl["stages"]["design"]["status"] = "done"
    pl["stages"]["implement"]["status"] = "done"
    check(first(pl) == "implement", "全做完了就停在最后一段")

    gates = ns["gates_of"]
    pl = ns["empty_pipeline"]()
    g = gates(pl)
    check(g == {"can_specify": False, "can_design": False,
                "can_implement": False},
          "闸门初始全关（%s）" % g)
    pl["stages"]["clarify"]["status"] = "done"
    g = gates(pl)
    check(g["can_specify"] is True and g["can_design"] is False
          and g["can_implement"] is False,
          "clarify 完成后只放开 specify（%s）" % g)

    gate = ns["check_gate"]
    pl = ns["empty_pipeline"]()
    try:
        gate(pl, "specify")
        check(False, "闸门该拦没拦（clarify 没做完却放行了 specify）")
    except ns["PipelineError"] as e:
        check(e.status == 409, "闸门拦下来是 409（状态冲突，不是 400）")
        check("clarify" in (e.missing or []),
              "409 说清缺哪一段（missing=%s）" % (e.missing,))
        check(bool(e.how_to_fix), "409 给了处置建议（%s）" % (e.how_to_fix,))
    try:
        gate(pl, "clarify")
        check(True, "第一段没有前置要求（clarify 直接可跑）")
    except ns["PipelineError"] as e:
        check(False, "clarify 不该被拦（%s）" % e)
    try:
        gate(pl, "不存在的阶段")
        check(False, "非法阶段名应被拒")
    except ns["PipelineError"] as e:
        check(e.status == 400, "非法阶段名是 400（%s）" % e.status)

    pl = ns["empty_pipeline"]()
    pl["stages"]["clarify"]["status"] = "done"
    try:
        gate(pl, "clarify")
        check(False, "已完成的阶段重跑应要求强制重跑")
    except ns["PipelineError"] as e:
        check(e.status == 409, "已完成再跑是 409（要开强制重跑）")
    try:
        gate(pl, "clarify", force=True)
        check(True, "强制重跑放行")
    except ns["PipelineError"] as e:
        check(False, "强制重跑不该被拦（%s）" % e)

    un = ns["unanswered_questions"]
    st = {"data": {"questions": [{"id": "q1", "question": "从哪来？"},
                                    {"id": "q2", "question": "谁统计？"}]},
          "answers": {}}
    check(len(un(st)) == 2, "两个问题都没答 → 两个都算未答")
    st["answers"]["q1"] = "人工录入"
    check(len(un(st)) == 1, "答了一题 → 剩一个未答")
    st["answers"]["q2"] = ""
    check(len(un(st)) == 0, "选了「都不需要」（空串）也算答了")

    implement_per_file_checks(path)


def implement_per_file_checks(path):
    """项目生成阶段是不是「一个文件一次调用」。

    为什么钉这一条：
        之前的实现是「一次问模型要一整套项目文件」（两批，每批 5 个文件）。
        推理型模型在那种调用里 1200 秒都回不来 —— 阶段必然失败，
        用户等半小时拿到一句「模型 1200 秒没有返回，已中止」。
        改成「文件清单从设计任务里取 → 一个文件一次调用 → 每个文件立刻落库」之后：
          · 每次调用小而快；
          · 单个文件失败不整段作废（已生成的文件还在）。
        这条断言就是防止以后又退回「一次要一整套」。

    怎么看出来的（不跑模型，只看源码结构）：
        · 模型调用（call_json…）必须出现在某个循环体里 —— 说明它按文件一个个问；
        · 不许再有「for ask in (IMPLEMENT_BATCH_CODE, IMPLEMENT_BATCH_SUPPORT)」
          这种「把几个大提示词轮流问一遍」的写法。
    """
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_stage_implement":
            fn = node
            break
    if fn is None:
        check(False, "找得到项目生成阶段的实现（_stage_implement）")
        return

    per_file = False
    for node in ast.walk(fn):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and "call_json" in sub.func.id):
                    per_file = True
    check(per_file,
          "项目生成的模型调用在循环里（不是一口气问完）")

    batch_loop = False
    for node in ast.walk(fn):
        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.iter, ast.Tuple):
            names = [e.id for e in node.iter.elts if isinstance(e, ast.Name)]
            if any(n.startswith("IMPLEMENT_BATCH") for n in names):
                batch_loop = True
    check(not batch_loop,
          "没有退回「for ask in (批量提示词, 批量提示词)」的老写法"
          "（改成按文件逐个生成之后自然变绿）")


def wait_job(client, job_id, timeout=60.0):
    """轮询作业直到结束，返回 (作业字典, 观察到的 processed 序列)"""
    seen = []
    deadline = time.time() + timeout
    job = {}
    while time.time() < deadline:
        r = client.get("/api/dev/jobs/%d" % job_id)
        if r.status_code != 200:
            return {"status": "http_%d" % r.status_code}, seen
        job = r.json()["job"]
        seen.append(job.get("processed"))
        if job.get("status") in ("done", "failed"):
            return job, seen
        time.sleep(0.15)
    return job, seen


def run_to_design(client, pid):
    """把一个项目跑到「需求转化」完成 —— 只有跑完设计才有任务，任务才是文件清单。

    单独拎出来是因为「单个文件失败」那个用例要一个**干净的新项目**：
    拿用过的项目重跑会走「续跑」分支（已生成的文件跳过），
    那样就测不到「第 3 个文件失败时前 2 个还在」了。
    """
    r = client.post("/api/dev/projects/%d/stages/clarify/run" % pid,
                    json={"extra": "内网使用"})
    wait_job(client, r.json()["job"]["id"])
    client.post("/api/dev/projects/%d/stages/clarify/answer" % pid,
                json={"answers": {"q1": "人工录入", "q2": "客服主管"}})
    r = client.post("/api/dev/projects/%d/stages/specify/run" % pid, json={})
    wait_job(client, r.json()["job"]["id"])
    r = client.post("/api/dev/projects/%d/stages/design/run" % pid, json={})
    job, _seen = wait_job(client, r.json()["job"]["id"])
    return job


def main() -> int:
    print("== 0. 纯逻辑自检（闸门状态机 / 阶段顺序 / 阶段完成判定） ==")
    pure_logic_checks(find_dev_pipeline_source())
    print("")

    try:
        from starlette.testclient import TestClient

        from app.main import app
        from app.services import dev_config, dev_pipeline
    except Exception as e:
        print("✗ 整链验证跑不了：%s" % e)
        print("  这一段需要完整依赖，请在容器里跑：\n    %s" % DOCKER_CMD)
        print("")
        print("✗ 验证未完成：整链验证没跑起来")
        return 1

    shim = _shim_docindex_ttlcache()
    if shim == "shimmed":
        print("（垫片：docindex 的 TTLCache 暂时缺失，已补一个最小实现让自测跑完）")

    mock_url, srv = start_mock()
    dev_config.save_config({
        "mode": "offline",
        "outbound_enabled": True,
        "local_model": {"base_url": mock_url, "model": "mock-model",
                        "api_key": ""},
    })
    print("== 0. 配置与体检 ==")
    cfg = dev_config.load_config()
    check(int(cfg.get("max_tokens") or 0) >= 8192,
          "dev 专用 max_tokens 默认 8192（实际 %s）" % cfg.get("max_tokens"))
    check(int(cfg.get("implement_max_tokens") or 0) >= 8192,
          "项目生成阶段单独给了额度（%s）" % cfg.get("implement_max_tokens"))

    with TestClient(app) as client:
        print("== 1. 建项目 ==")
        r = client.post("/api/dev/projects", json={
            "name": "工单系统", "goal": "客服录入工单并统计工作量",
            "tech_stack": ["Python", "FastAPI"], "mode": "offline"})
        check(r.status_code == 200, "POST /api/dev/projects 200")
        pid = r.json()["project"]["id"]

        print("== 2. 读流水线 ==")
        r = client.get("/api/dev/projects/%d/pipeline" % pid)
        check(r.status_code == 200, "GET /pipeline 200")
        body = r.json()
        keys = [s["key"] for s in body.get("stages") or []]
        check(keys == ["clarify", "specify", "design", "implement"],
              "四个阶段顺序固定：%s" % keys)
        check(body["pipeline"]["current_stage"] == "clarify",
              "current_stage 指向第一个没做完的阶段")
        check(body["gates"]["can_specify"] is False, "闸门初始全关")
        check(all(s["status"] == "pending" for s in body["stages"]),
              "四个阶段初始都是 pending")
        check(all("summary" in s for s in body["stages"]),
              "每个阶段带一句人话 summary")

        print("== 3. 闸门：没过就 409 ==")
        r = client.post("/api/dev/projects/%d/stages/specify/run" % pid, json={})
        check(r.status_code == 409, "specify 被闸门拦下（409，实际 %d）" % r.status_code)
        err = r.json()
        check(err.get("ok") is False, "错误体带 ok=false")
        check("clarify" in (err.get("missing") or []),
              "错误体说清缺哪一段：%s" % (err.get("missing") or []))
        check(bool(err.get("how_to_fix")), "错误体带 how_to_fix")
        check("detail" in err, "错误体带 detail")

        print("== 4. 跑需求理解（作业进度要真实） ==")
        r = client.post("/api/dev/projects/%d/stages/clarify/run" % pid,
                        json={"extra": "内网使用"})
        check(r.status_code == 200, "POST /stages/clarify/run 200")
        job = r.json()["job"]
        check(job.get("job_type") == "dev_stage", "job_type = dev_stage")
        check(job.get("total") == len(dev_pipeline.STAGE_STEPS["clarify"]),
              "total = 该阶段真实步骤数（%s）" % job.get("total"))
        job, seen = wait_job(client, job["id"])
        check(job.get("status") == "done",
              "需求理解跑完（%s / %s）" % (job.get("status"), job.get("error")))
        check(job.get("processed") == job.get("total"),
              "processed 走完（%s/%s）" % (job.get("processed"), job.get("total")))
        check(len(set(x for x in seen if x is not None)) > 1,
              "processed 是逐步递增的：%s" % seen)
        check(bool(job.get("current") is not None), "current 字段存在")

        print("== 5. 澄清问题必须人回答 ==")
        r = client.get("/api/dev/projects/%d/pipeline" % pid)
        pl = r.json()
        st = pl["pipeline"]["stages"]["clarify"]
        check(st["status"] == "needs_input",
              "有澄清问题时状态是 needs_input（%s）" % st["status"])
        check(len(st["data"]["questions"]) == 2, "澄清问题带候选项落库")
        check(all(q.get("why") for q in st["data"]["questions"]),
              "每个问题都带 why（为什么必须问）")
        check(pl["gates"]["can_specify"] is False, "没回答前下一段仍锁着")
        r = client.post("/api/dev/projects/%d/stages/clarify/answer" % pid,
                        json={"answers": {"q1": "人工录入"}})
        check(r.status_code == 200, "提交部分答案 200")
        pl = r.json()
        check(pl["pipeline"]["stages"]["clarify"]["status"] == "needs_input",
              "只答一题时仍是 needs_input")
        check(pl["gates"]["can_specify"] is False, "只答一题不放行")
        r = client.post("/api/dev/projects/%d/stages/clarify/answer" % pid,
                        json={"answers": {"q2": "客服主管"}})
        pl = r.json()
        check(pl["pipeline"]["stages"]["clarify"]["status"] == "done",
              "全部答完才放行")
        check(pl["gates"]["can_specify"] is True, "答完后 can_specify 为真")

        print("== 6. 需求补全 ==")
        r = client.post("/api/dev/projects/%d/stages/specify/run" % pid, json={})
        check(r.status_code == 200, "POST /stages/specify/run 200")
        job, seen = wait_job(client, r.json()["job"]["id"])
        check(job.get("status") == "done",
              "需求补全跑完（%s / %s）" % (job.get("status"), job.get("error")))
        check(job.get("processed") == job.get("total"),
              "需求补全结束时 processed == total（%s/%s）"
              % (job.get("processed"), job.get("total")))
        pl = client.get("/api/dev/projects/%d/pipeline" % pid).json()
        spec = pl["pipeline"]["stages"]["specify"]["data"]
        check(len(spec.get("stories") or []) == 1, "用户故事落库")
        check(isinstance(spec["stories"][0].get("acceptance"), list),
              "acceptance 是数组（契约字段名不许改）")
        check(bool(spec.get("data_model")), "数据模型落库")
        check(bool(spec.get("out_of_scope")), "明确不做的范围落库")

        print("== 7. 需求转化：任务落 dev_task ==")
        r = client.post("/api/dev/projects/%d/stages/design/run" % pid, json={})
        check(r.status_code == 200, "POST /stages/design/run 200")
        job, seen = wait_job(client, r.json()["job"]["id"])
        check(job.get("status") == "done",
              "需求转化跑完（%s / %s）" % (job.get("status"), job.get("error")))
        check(job.get("processed") == job.get("total"),
              "需求转化结束时 processed == total（%s/%s）"
              % (job.get("processed"), job.get("total")))
        pl = client.get("/api/dev/projects/%d/pipeline" % pid).json()
        design = pl["pipeline"]["stages"]["design"]["data"]
        check(isinstance(design.get("architecture"), str),
              "architecture 是字符串（不是对象）")
        check(bool(design.get("modules")) and bool(design.get("data_tables"))
              and bool(design.get("apis")), "模块/表/接口都在")
        check("tasks" not in design,
              "任务拆解不放 design.data（契约要求落 dev_task）")
        tasks = client.get("/api/dev/projects/%d" % pid).json()["tasks"]
        check(len(tasks) == 4, "任务拆解写进 dev_task（%d 条）" % len(tasks))
        if len(tasks) == 4:
            check(tasks[1]["depends_on"] == [tasks[0]["id"]],
                  "depends_on 是真实 task id（%s）" % tasks[1]["depends_on"])
            check(tasks[2]["depends_on"] == [tasks[1]["id"]],
                  "链式依赖正确（%s）" % tasks[2]["depends_on"])
            check(tasks[3]["depends_on"] == [tasks[2]["id"]],
                  "第四个任务也挂在第三个后面（%s）" % tasks[3]["depends_on"])

        print("== 8. 项目生成 ==")
        r = client.post("/api/dev/projects/%d/stages/implement/run" % pid, json={})
        check(r.status_code == 200, "POST /stages/implement/run 200")
        job, seen = wait_job(client, r.json()["job"]["id"])
        check(job.get("status") == "done",
              "项目生成跑完（%s / %s）" % (job.get("status"), job.get("error")))
        check(job.get("processed") == job.get("total"),
              "项目生成结束时 processed == total（%s/%s）"
              % (job.get("processed"), job.get("total")))
        arts = client.get("/api/dev/projects/%d" % pid).json()["artifacts"]
        names = [a["filename"] for a in arts]
        check("README.md" in names, "产出里有 README.md（%s）" % names)
        check("requirements.txt" in names, "产出里有依赖清单")
        check("main.py" in names, "产出里有可运行入口")
        check(any("test" in n for n in names), "产出里有测试文件")
        check("Dockerfile" in names, "产出里有启动脚本或 Dockerfile")
        check(all(a.get("source") == "model" for a in arts), "产出来源标成 model")
        bodies = []
        for a in arts:
            rd = client.get("/api/dev/artifacts/%d" % a["id"]).json()
            bodies.append(rd["artifact"].get("content") or "")
        check(all(bodies), "每个产出都有正文（清单接口不带正文，详情接口带）")
        check(all(a.get("language") for a in arts), "每个产出都标了语言")

        print("== 8b. 一个文件一次调用；单个文件失败不整段作废 ==")
        # 为什么单独钉这几条：
        #   旧实现是「一口气问模型要一整套文件」，推理型模型 1200 秒都回不来 ——
        #   「项目生成」阶段在真模型上必然失败（实测就是这么挂的）。
        #   改成「一个文件一次调用、每个文件立刻落库」之后，
        #   单个文件失败只损失在飞的那一个，已生成的文件还能导出。
        #   这几条断言就是防止以后又退回老写法，又防止「整段作废」。
        impl_calls = MOCK_STATS.get("implement", 0)
        one_calls = MOCK_STATS.get("implement_one", 0)
        model_arts = [a for a in arts if a.get("source") == "model"]
        check(one_calls == 4,
              "每个设计任务单独问一次模型（主流程调用 %d 次，设计任务 4 个）"
              % one_calls)
        check(impl_calls >= one_calls,
              "模型调用次数不少于文件数（调用 %d 次，其中按文件 %d 次）"
              % (impl_calls, one_calls))
        check(len(model_arts) >= 4,
              "模型产出的文件不少于任务数（%d 个）" % len(model_arts))

        # 用一个干净的新项目测「单个文件失败不整段作废」：
        #   拿用过的项目重跑会走「续跑」分支（已生成的文件跳过），
        #   那样就测不到「第 3 个文件失败时前 2 个还在」了。
        pid3 = client.post("/api/dev/projects", json={
            "name": "单文件失败测试", "goal": "验证单个文件失败不整段作废",
            "tech_stack": ["Python"], "mode": "offline"}).json()["project"]["id"]
        jobd = run_to_design(client, pid3)
        check(jobd.get("status") == "done",
              "新项目跑到设计阶段完成（%s）" % jobd.get("status"))

        # 让第 3 个文件开始失败：
        #   前 2 个文件必须还在产出物里（还能导出），
        #   而且话要说清「已经生成了几个、怎么接着补」。
        MOCK_MODE["implement_fail_from"] = 3
        MOCK_STATS["implement"] = 0
        r = client.post("/api/dev/projects/%d/stages/implement/run" % pid3, json={})
        job2, seen2 = wait_job(client, r.json()["job"]["id"], timeout=180)
        MOCK_MODE["implement_fail_from"] = 0
        arts2 = client.get("/api/dev/projects/%d" % pid3).json()["artifacts"]
        names2 = [a["filename"] for a in arts2]
        check(job2.get("status") == "failed",
              "连续 2 个文件失败时阶段判失败（%s / %s）"
              % (job2.get("status"), str(job2.get("error"))[:50]))
        check(len(arts2) >= 2,
              "第 3 个文件起失败时，前 2 个文件仍在产出物里（%s）" % names2)
        fix2 = " ".join(job2.get("how_to_fix") or [])
        check("已生成 2/4 个文件" in fix2,
              "话要说清已经生成了几个、怎么接着补：%s" % fix2[:120])
        check("已生成 2/4 个文件" in (job2.get("error") or ""),
              "错误信息里也写清已生成几个：%s" % str(job2.get("error"))[:80])
        # 已生成的文件要还能导出 —— 这正是「不整段作废」的意义
        r = client.get("/api/dev/projects/%d/export.zip" % pid3)
        check(r.status_code == 200,
              "阶段失败时已生成的文件仍可导出（HTTP %d）" % r.status_code)

        # 重跑只补剩下的：已生成的那两个不重做（产出物 id 不变）
        ids_before = {a["filename"]: a["id"] for a in arts2}
        r = client.post("/api/dev/projects/%d/stages/implement/run" % pid3,
                        json={"force": True})
        job3, seen3 = wait_job(client, r.json()["job"]["id"], timeout=180)
        arts3 = client.get("/api/dev/projects/%d" % pid3).json()["artifacts"]
        ids_after = {a["filename"]: a["id"] for a in arts3}
        kept = [f for f in ids_before
                if f in ids_after and ids_after[f] == ids_before[f]]
        check(job3.get("status") == "done",
              "重跑补齐后阶段成功（%s / %s）"
              % (job3.get("status"), str(job3.get("error"))[:50]))
        check(len(kept) >= 2,
              "重跑只补剩下的：已生成的 %d 个文件没重做（产出物 id 没变）" % len(kept))
        check(len(arts3) > len(arts2),
              "重跑后文件变多了（%d → %d）" % (len(arts2), len(arts3)))

        print("== 9. 导出 ZIP ==")
        r = client.get("/api/dev/projects/%d/export.zip" % pid)
        check(r.status_code == 200, "GET /export.zip 200")
        check("application/zip" in (r.headers.get("content-type") or ""),
              "Content-Type 是 application/zip")
        check("attachment" in (r.headers.get("content-disposition") or ""),
              "带 Content-Disposition attachment")
        import io as _io
        import zipfile as _zipfile
        zf = _zipfile.ZipFile(_io.BytesIO(r.content))
        entries = zf.namelist()
        check(any(e.endswith("/README.md") for e in entries),
              "ZIP 里有 README.md：%s" % entries[:6])
        tops = set(e.split("/")[0] for e in entries if "/" in e)
        check(len(tops) == 1, "ZIP 顶层只有一层目录：%s" % tops)
        check(any(e.endswith("backend/app/main.py") for e in entries),
              "ZIP 里含项目源码")

        print("== 10. 没有产出时导出 409 ==")
        r = client.post("/api/dev/projects", json={"name": "空项目",
                                                   "mode": "offline"})
        pid2 = r.json()["project"]["id"]
        r = client.get("/api/dev/projects/%d/export.zip" % pid2)
        check(r.status_code == 409, "导出空项目返回 409（实际 %d）" % r.status_code)
        check("implement" in (r.json().get("missing") or []),
              "409 说清缺哪一段：%s" % (r.json().get("missing") or []))

        print("== 11. 失败必须让用户看见 error + how_to_fix ==")
        MOCK_MODE["fail"] = True
        r = client.post("/api/dev/projects/%d/stages/clarify/run" % pid,
                        json={"force": True})
        job, seen = wait_job(client, r.json()["job"]["id"])
        check(job.get("status") == "failed", "模型胡扯时作业失败")
        check(bool(job.get("error")), "失败带 error：%s" % str(job.get("error"))[:40])
        check(bool(job.get("how_to_fix")), "失败带 how_to_fix")
        MOCK_MODE["fail"] = False

        print("== 11b. 连接被掐断时，也必须给得出怎么修 ==")
        # 为什么单独验这一条：
        #   「模型胡扯」走的是 DevError 分支，错误体里带着 missing/how_to_fix；
        #   但「连接被掐断 / 未知异常」走的是兜底分支 ——
        #   如果兜底分支只写了 error，用户看到的就是一句天书，
        #   契约 §4.3「失败必须让用户看见 error + how_to_fix」就破了。
        MOCK_MODE["broken"] = True
        r = client.post("/api/dev/projects/%d/stages/clarify/run" % pid,
                        json={"force": True})
        job, seen = wait_job(client, r.json()["job"]["id"])
        MOCK_MODE["broken"] = False
        check(job.get("status") == "failed",
              "连接被掐断时作业失败（而不是永远 running）")
        check(bool(job.get("error")),
              "失败带 error：%s" % str(job.get("error"))[:60])
        check(bool(job.get("how_to_fix")),
              "失败带 how_to_fix（契约 §4.3：失败必须让用户看见怎么修）")

        print("== 12. 提示词带 schema、不许改技术栈 ==")
        sys_text = ""
        user_text = ""
        for call in MOCK_CALLS:
            for m in call.get("messages") or []:
                if m.get("role") == "system":
                    sys_text += str(m.get("content") or "")
                if m.get("role") == "user":
                    user_text += str(m.get("content") or "")
        check("不要改动用户指定的技术栈" in sys_text, "提示词写了不许改技术栈")
        check("只输出一个 JSON 对象" in sys_text, "提示词写了只输出 JSON")
        check("必须是**字符串**" in sys_text or "必须是字符串" in sys_text,
              "提示词写了字符串/数组的字段约束")
        check("FastAPI" in user_text, "用户提示里带上了用户指定的技术栈")
        check("depends_on" in sys_text, "提示词写了任务的 depends_on 约束")

        print("== 13. 截断 JSON 能抢救 ==")
        fixed = dev_pipeline._rescue_json('{"understanding": "被截断了')
        check(isinstance(fixed, dict) and fixed.get("understanding") == "被截断了",
              "截断的 JSON 被补齐救回")
        bad = dev_pipeline._rescue_json("完全不是 JSON")
        check(bad is None, "不是 JSON 时如实返回 None")

        print("== 14. 结构归一：模型把字符串给成对象也能收 ==")
        norm, warns = dev_pipeline.normalize_clarify(
            {"understanding": {"a": 1}, "questions": []})
        check(isinstance(norm["understanding"], str),
              "understanding 是对象时被转成字符串")
        check(bool(warns), "并且记下警告：%s" % warns)

        print("== 15. 缺文件时合成骨架（诚实标注） ==")
        extra = dev_pipeline._synthesize_files(
            _FakeProject(), {}, [], ["readme", "deps", "entry", "test", "start"])
        paths = sorted(f["path"] for f in extra)
        check("README.md" in paths, "合成 README.md")
        check("requirements.txt" in paths, "合成依赖清单")
        check(any(p.endswith("test_smoke.py") for p in paths), "合成测试文件")
        check(any(p.endswith("start.sh") for p in paths), "合成启动脚本")
        readme = [f for f in extra if f["path"] == "README.md"][0]
        check("自动补齐" in readme["content"], "骨架文件里写明是自动补齐的")

    srv.shutdown()
    print("")
    print("共 %d 项检查，失败 %d 项" % (CHECKS, len(FAILURES)))
    for f in FAILURES:
        print("  - %s" % f)
    return 1 if FAILURES else 0


class _FakeProject:
    name = "演示项目"
    goal = "演示"
    tech_stack = ["Python"]
    tech_notes = ""


if __name__ == "__main__":
    raise SystemExit(main())
