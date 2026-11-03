#!/usr/bin/env python3
"""项目生成阶段「一次一个文件、边生成边落盘」的自检

为什么要有这个脚本：
    「一个文件一次调用、每个文件立刻落库、中途失败不作废已生成的」——
    这几条光看代码不算数，得跑一遍才算数。

离线跑，不碰线上库：
    docker run --rm -i -v "$PWD/backend/app:/app/app:ro" \
      --entrypoint python kb-workbench-backend - < scripts/verify-dev-implement-files.py

验四件事：
    1. 每个文件是一次独立调用（按 mock 模型收到的请求数断言）；
    2. 中途有文件失败时，前面生成的文件仍在产出物里、阶段判 failed、
       how_to_fix 说清「已生成 n/N 个文件」；
    3. 作业进度 processed 递增到 N（文件数）；
    4. 导出 ZIP 里有已生成的那些文件。

模型用的是脚本里起的一个本地 mock（OpenAI 兼容），
每次只吐一个文件 —— 所以整个自测不依赖外网、不消耗额度。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOCKER_CMD = ('docker run --rm -i -v "$PWD/backend/app:/app/app:ro" '
              '--entrypoint python kb-workbench-backend - '
              '< scripts/verify-dev-implement-files.py')

if sys.version_info < (3, 10):
    raise SystemExit("需要 Python 3.10+。请在容器里跑：\n    %s" % DOCKER_CMD)

_HERE = globals().get("__file__") and os.path.dirname(os.path.abspath(__file__)) or ""
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend") if _HERE else ""
if _BACKEND and os.path.isdir(_BACKEND):
    sys.path.insert(0, _BACKEND)

_TMP = tempfile.mkdtemp(prefix="kb-dev-implement-verify-")
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

# 设计阶段拆出来的任务 —— 每个任务对应一个要生成的文件。
TASK_FILES = {
    "项目入口": ("backend/app/main.py", "python",
                 "from fastapi import FastAPI\n\napp = FastAPI()\n"),
    "依赖清单": ("backend/requirements.txt", "text", "fastapi\nuvicorn\n"),
    "使用说明": ("README.md", "markdown", "# 工单系统\n\n怎么装、怎么跑、怎么测。\n"),
    "冒烟测试": ("tests/test_smoke.py", "python",
                 "def test_ok():\n    assert True\n"),
    "启动脚本": ("start.sh", "shell", "#!/bin/sh\necho ok\n"),
}

CLARIFY_OUT = {
    "understanding": "给客服用的工单系统：录入工单、跟踪状态",
    "assumptions": ["单租户内网使用"],
    "questions": [
        {"id": "q1", "question": "工单从哪来？", "why": "决定要不要做导入",
         "options": ["人工录入", "外部系统推送"], "allow_free": True},
    ],
}

SPECIFY_OUT = {
    "stories": [
        {"id": "S1", "title": "录入工单", "as_a": "客服",
         "i_want": "录入一条工单", "so_that": "能跟踪状态",
         "acceptance": ["必填：标题", "保存后列表可见"]},
    ],
    "nonfunctional": ["性能：列表查询 P95 < 500ms"],
    "data_model": [{"entity": "Ticket", "fields": ["id", "title", "status"]}],
    "edge_cases": ["同名多条工单"],
    "out_of_scope": ["工单审批流"],
}

DESIGN_OUT = {
    "architecture": "FastAPI + SQLite：路由层 -> 服务层",
    "modules": [{"name": "tickets", "responsibility": "工单增删改查",
                 "depends_on": []}],
    "data_tables": [{"name": "ticket",
                     "columns": [{"name": "id", "type": "INTEGER"},
                                 {"name": "title", "type": "TEXT"}]}],
    "apis": [{"method": "POST", "path": "/api/tickets", "purpose": "新建工单"}],
    "risks": ["导出百万行会占内存"],
    "tasks": [
        {"title": title, "description": "产出 %s" % path,
         "acceptance": "文件存在且内容完整", "depends_on": []}
        for title, (path, _lang, _body) in TASK_FILES.items()
    ],
}

MOCK = {
    "calls": [],        # 每次实现阶段的请求（用户提示词）
    "titles": [],       # 每次实现阶段请求的文件名（按顺序）
    "fail_titles": set(),  # 这些文件一律回 500（模拟模型失败）
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
        system = ""
        user = ""
        for m in payload.get("messages") or []:
            if m.get("role") == "system":
                system += str(m.get("content") or "")
            if m.get("role") == "user":
                user += str(m.get("content") or "")

        if "真实可运行" in system:
            # 项目生成阶段：一次只吐一个文件
            MOCK["calls"].append(user)
            title = ""
            m = re.search(r"要写的文件：(.+)", user)
            if m:
                title = m.group(1).strip()
            MOCK["titles"].append(title)
            if title in MOCK["fail_titles"]:
                body = json.dumps({"error": {"message": "mock: 模型崩了"}},
                                  ensure_ascii=False).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            path, lang, text = TASK_FILES.get(
                title, ("src/%s.py" % re.sub(r"\W+", "_", title or "file"),
                        "python", "# %s\n" % (title or "file")))
            content = json.dumps({"files": [{"path": path, "language": lang,
                                             "content": text}]},
                                 ensure_ascii=False)
        elif "做需求理解" in system:
            content = json.dumps(CLARIFY_OUT, ensure_ascii=False)
        elif "可验收的规格" in system:
            content = json.dumps(SPECIFY_OUT, ensure_ascii=False)
        elif "资深软件架构师" in system:
            content = json.dumps(DESIGN_OUT, ensure_ascii=False)
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


def wait_job(client, job_id, timeout=180.0):
    seen = []
    deadline = time.time() + timeout
    job = {}
    while time.time() < deadline:
        r = client.get("/api/dev/jobs/%d" % job_id)
        if r.status_code == 200:
            job = r.json().get("job") or {}
            p = job.get("processed")
            if not seen or seen[-1] != p:
                seen.append(p)
        if job.get("status") in ("done", "failed", "skipped"):
            return job, seen
        time.sleep(0.01)
    return job, seen


def run_chain(client, name):
    """把前三个阶段跑完（澄清要人回答），返回项目 id。"""
    r = client.post("/api/dev/projects", json={
        "name": name, "goal": "客服录入工单并跟踪状态",
        "tech_stack": ["Python", "FastAPI"], "mode": "offline"})
    pid = r.json()["project"]["id"]
    r = client.post("/api/dev/projects/%d/stages/clarify/run" % pid,
                    json={"extra": "内网使用"})
    wait_job(client, r.json()["job"]["id"])
    # 澄清阶段会停在 needs_input —— 得人回答完才放行下一段
    r = client.get("/api/dev/projects/%d/pipeline" % pid)
    st = r.json()["pipeline"]["stages"]["clarify"]
    if st.get("status") == "needs_input":
        questions = (st.get("data") or {}).get("questions") or []
        answers = {q["id"]: (q.get("options") or ["是"])[0] for q in questions}
        r = client.post("/api/dev/projects/%d/stages/clarify/answer" % pid,
                        json={"answers": answers})
        check(r.status_code == 200, "澄清问题回答提交成功")
    for stage in ("specify", "design"):
        r = client.post("/api/dev/projects/%d/stages/%s/run" % (pid, stage),
                        json={})
        wait_job(client, r.json()["job"]["id"])
    return pid


def main() -> int:
    try:
        from starlette.testclient import TestClient

        from app.main import app
        from app.services import dev_config
    except Exception as e:
        print("✗ 自检跑不起来：%s" % e)
        print("  这一段需要完整依赖，请在容器里跑：\n    %s" % DOCKER_CMD)
        return 1

    mock_url, srv = start_mock()
    dev_config.save_config({
        "mode": "offline",
        "outbound_enabled": True,
        "local_model": {"base_url": mock_url, "model": "mock-model",
                        "api_key": ""},
    })
    cfg = dev_config.load_config()
    print("== 0. 配置 ==")
    check(int(cfg.get("implement_file_max_tokens") or 0) <= 8192,
          "单文件额度不超过 8192（实际 %s）" % cfg.get("implement_file_max_tokens"))
    check(int(cfg.get("implement_file_timeout") or 0) <= 300,
          "单文件时限不超过 300 秒（实际 %s）" % cfg.get("implement_file_timeout"))

    with TestClient(app) as client:
        print("== 1. 跑完前三个阶段 ==")
        pid = run_chain(client, "逐文件生成")
        pl = client.get("/api/dev/projects/%d/pipeline" % pid).json()
        tasks = client.get("/api/dev/projects/%d" % pid).json()["tasks"]
        n = len(tasks)
        check(n == len(TASK_FILES),
              "设计阶段拆出 %d 个任务（每个任务一个文件）" % n)

        print("== 2. 项目生成：一个文件一次调用 ==")
        MOCK["calls"] = []
        MOCK["titles"] = []
        MOCK["fail_titles"] = set()
        r = client.post("/api/dev/projects/%d/stages/implement/run" % pid, json={})
        check(r.status_code == 200, "POST /stages/implement/run 200")
        job, seen = wait_job(client, r.json()["job"]["id"])
        check(job.get("status") == "done",
              "项目生成跑完（%s / %s）" % (job.get("status"), job.get("error")))
        check(len(MOCK["calls"]) == n,
              "每个文件一次独立调用（模型收到 %d 次，任务 %d 个）"
              % (len(MOCK["calls"]), n))
        check(all("这一次只写这一个文件" in c for c in MOCK["calls"]),
              "每次都只交代一个文件（提示词里写明「只写这一个文件」）")
        check(len(set(MOCK["titles"])) == len(MOCK["titles"]),
              "每次问的文件不重样：%s" % MOCK["titles"])

        arts = client.get("/api/dev/projects/%d" % pid).json()["artifacts"]
        paths = [a["path"] for a in arts]
        check(len(arts) == n, "产出物数量等于任务数（%d / %d）" % (len(arts), n))
        check(all(a.get("source") == "model" for a in arts), "产出来源标成 model")
        want = sorted(p for p, _l, _b in TASK_FILES.values())
        check(sorted(paths) == want,
              "产出的文件就是清单里的那些：%s" % sorted(paths))

        print("== 3. 进度：processed 递增到 N ==")
        check(int(job.get("processed") or 0) >= n,
              "processed 递增到了文件数（%s >= %d）" % (job.get("processed"), n))
        check(int(job.get("processed") or 0) == int(job.get("total") or 0),
              "processed 走完了 total（%s/%s）"
              % (job.get("processed"), job.get("total")))
        check(len(set(s for s in seen if s is not None)) > 1,
              "processed 是逐步递增的：%s" % seen)
        pl = client.get("/api/dev/projects/%d/pipeline" % pid).json()
        st = pl["pipeline"]["stages"]["implement"]
        check(st.get("status") == "done", "阶段状态是 done（%s）" % st.get("status"))
        check(len((st.get("data") or {}).get("files") or []) == n,
              "阶段数据里列了 %d 个文件" % n)

        print("== 4. 导出 ZIP 里有已生成的文件 ==")
        r = client.get("/api/dev/projects/%d/export.zip" % pid)
        check(r.status_code == 200, "GET /export.zip 200")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        entries = zf.namelist()
        for p in want:
            check(any(e.endswith("/" + p) for e in entries),
                  "ZIP 里有 %s" % p)

        print("== 5. 中途失败：已生成的文件要保住 ==")
        pid2 = run_chain(client, "中途失败")
        tasks2 = client.get("/api/dev/projects/%d" % pid2).json()["tasks"]
        fail_titles = {tasks2[2]["title"], tasks2[3]["title"]}
        MOCK["calls"] = []
        MOCK["titles"] = []
        MOCK["fail_titles"] = set(fail_titles)
        r = client.post("/api/dev/projects/%d/stages/implement/run" % pid2,
                        json={})
        job2, _seen2 = wait_job(client, r.json()["job"]["id"])
        check(job2.get("status") == "failed",
              "连续 2 个文件失败时作业失败（%s / %s）"
              % (job2.get("status"), str(job2.get("error"))[:60]))
        arts2 = client.get("/api/dev/projects/%d" % pid2).json()["artifacts"]
        paths2 = [a["path"] for a in arts2]
        check(len(arts2) == 2,
              "失败前生成的 2 个文件仍在产出物里（%s）" % paths2)
        check(paths2 == [TASK_FILES[tasks2[0]["title"]][0],
                         TASK_FILES[tasks2[1]["title"]][0]],
              "留下的是最先生成的那两个：%s" % paths2)
        how = " ".join(job2.get("how_to_fix") or [])
        check("已生成 2/%d 个文件" % len(tasks2) in how,
              "how_to_fix 说清已生成多少：%s" % how[:120])
        check("重跑只补剩下的" in how,
              "how_to_fix 说清重跑只补剩下的：%s" % how[:120])
        pl2 = client.get("/api/dev/projects/%d/pipeline" % pid2).json()
        st2 = pl2["pipeline"]["stages"]["implement"]
        check(st2.get("status") == "failed",
              "阶段状态标成 failed（%s）" % st2.get("status"))
        failed_files = (st2.get("data") or {}).get("failed_files") or []
        check(len(failed_files) == 2,
              "阶段数据里记下了 2 个失败的文件：%s"
              % [f.get("title") for f in failed_files])
        r = client.get("/api/dev/projects/%d/export.zip" % pid2)
        check(r.status_code == 200,
              "阶段失败但已有产出物时，导出照样能用（HTTP %d）" % r.status_code)
        if r.status_code == 200:
            entries2 = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
            check(any(e.endswith("/" + paths2[0]) for e in entries2),
                  "ZIP 里有失败前生成的文件")

    srv.shutdown()
    print("")
    print("共 %d 项检查，失败 %d 项" % (CHECKS, len(FAILURES)))
    for f in FAILURES:
        print("  - %s" % f)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
