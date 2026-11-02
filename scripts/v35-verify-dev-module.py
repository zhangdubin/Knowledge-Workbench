#!/usr/bin/env python3
"""v35 自测：软件开发模块（在线协同 / 离线闭环 / 闭环反哺）

离线跑，不碰线上库：
  docker run --rm -i -v "$PWD/backend/app:/app/app:ro" \
    --entrypoint python kb-workbench-backend - < scripts/v35-verify-dev-module.py

验八件事：
1. 离线模式下**一个外网请求都不发**（出网闸门真的拦得住）；
2. 没有模型端点时，接口如实返回「缺什么、怎么配」，不假成功；
3. 项目 → 方案 → 任务 → 产出物 → 会话 → 引用，整条链路真落库；
4. 生成的代码过安全体检：硬编码密钥被拦下，告警带回前端；
5. 产出物导入数据中心（文件库）；
6. 反哺知识库：产出沉淀成新基因，且**置信度与表达度真的涨了**；
7. 下一轮开发能直接检索到上一轮沉淀的经验（闭环闭环）；
8. HTTP 接口层（FastAPI TestClient）跑通，含缺配置时的错误结构。

模型用的是脚本里起的一个本地 mock（OpenAI 兼容），
所以整个自测不依赖外网、不消耗额度。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOCKER_CMD = 'docker run --rm -i -v "$PWD/backend/app:/app/app:ro" --entrypoint python kb-workbench-backend - < scripts/v35-verify-dev-module.py'

# 环境自检：脚本要跑在后端的运行环境里（Python 3.10+ / SQLAlchemy 2.x）。
#
# 为什么必须先自检：缺依赖时裸报错是
# "No module named 'async_sessionmaker'" 或 "unsupported operand type(s) for |"，
# 这种错跟脚本在验什么毫无关系，最容易把人带偏 —— 以为是功能挂了。
# 所以先把话说清楚：环境不对，请去容器里跑。
if sys.version_info < (3, 10):
    raise SystemExit(
        "需要 Python 3.10+（当前 %d.%d）。请在容器里跑：\n    %s"
        % (sys.version_info[0], sys.version_info[1], DOCKER_CMD))
try:
    import sqlalchemy  # noqa: F401
    from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: F401
except Exception as _e:
    raise SystemExit(
        "需要 SQLAlchemy 2.x（当前报错：%s）。请在容器里跑：\n    %s"
        % (_e, DOCKER_CMD))

# 允许在仓库里直接 python3 scripts/v35-verify-dev-module.py 跑（依赖装在容器里时用不到）
_HERE = globals().get("__file__") and os.path.dirname(os.path.abspath(__file__)) or ""
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend") if _HERE else ""
if _BACKEND and os.path.isdir(_BACKEND):
    sys.path.insert(0, _BACKEND)

# ---- 临时环境：库、文件、配置全部落在临时目录，绝不碰真实数据 ----
_TMP = tempfile.mkdtemp(prefix="kb-dev-verify-")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(_TMP, "kb.db")
os.environ["DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["FILE_STORE_DIR"] = os.path.join(_TMP, "files")
os.environ["KB_DEV_CONFIG"] = os.path.join(_TMP, "dev_config.json")
# 自测环境关掉登录：接口鉴权本身照旧，只是这里不用再走一遍登录流程
os.environ["AUTH_ENABLED"] = "false"
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["FILE_STORE_DIR"], exist_ok=True)

FAILURES: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> bool:
    global CHECKS
    CHECKS += 1
    if cond:
        print("  \u2713 %s" % label)
    else:
        print("  \u2717 %s" % label)
        FAILURES.append(label)
    return bool(cond)


# ============ 本地 mock 模型（OpenAI 兼容） ============

MOCK_CALLS: list[dict] = []
# 让 mock 掺一点「坏味道」：第二个任务返回一段硬编码密钥的代码
_BAD_CODE = {
    "files": [{
        "path": "src/config.py",
        "language": "python",
        "content": "API_KEY = \"sk-abcdef0123456789abcdef0123456789\"\n"
                   "def run():\n    os.system(\"rm -rf /\")\n",
    }],
    "notes": "掺了密钥与危险命令，用来验证安全体检",
}


class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 别把请求日志刷屏
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length or 0)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {}
        MOCK_CALLS.append(payload)
        system = ""
        user = ""
        for m in payload.get("messages") or []:
            if m.get("role") == "system":
                system += str(m.get("content") or "")
            if m.get("role") == "user":
                user += str(m.get("content") or "")
        if "方案" in system:
            content = json.dumps({
                "summary": "做一个对账小工具",
                "architecture": "读取账单 → 归一化 → 比对 → 出报告",
                "tech_stack": ["Python", "SQLite"],
                "risks": ["金额精度"],
                "tasks": [
                    {"title": "搭骨架",
                     "description": "建目录与配置",
                     "acceptance": "能跑起来并打印一行 hello",
                     "depends_on": []},
                    {"title": "实现比对逻辑",
                     "description": "按账号与金额比对两期账单",
                     "acceptance": "差异条目被打印出来",
                     "depends_on": [0]},
                ],
            }, ensure_ascii=False)
        elif "代码" in system or "文件内容" in system:
            content = json.dumps(_BAD_CODE, ensure_ascii=False)
        else:
            content = json.dumps({
                "answer": "依据基因 gene:1 的经验：先归一化再比对。",
                "used_refs": [1],
            }, ensure_ascii=False)
        body = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_mock() -> tuple[str, ThreadingHTTPServer]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return "http://127.0.0.1:%d/v1/chat/completions" % srv.server_address[1], srv


def _shim_docindex_ttlcache() -> str:
    """测试期兼容垫片。

    背景：docindex / embedding 正在重构（TTLCache 被从 docindex 挪走，
    而 embedding.py 的 import 还指着老地方），整个后端因此起不来。
    这里只在属性确实缺失时补一个最小实现，让自测能跑完 ——
    正式修复由那两个文件的主人做，不在本脚本里糊过去。
    """
    try:
        from app.services import docindex
    except Exception:
        return "skip"
    if hasattr(docindex, "TTLCache"):
        return "present"

    class _TTLCache:
        def __init__(self, max_size: int = 128, ttl: float = 60.0):
            self.max_size = max_size
            self.ttl = ttl
            self.size = 0
            self.hits = 0
            self.misses = 0
            self._d = {}

        def get(self, key, default=None):
            item = self._d.get(key)
            if item is None:
                self.misses += 1
                return default
            value, expire_at = item
            if expire_at and expire_at < time.time():
                self._d.pop(key, None)
                self.misses += 1
                return default
            self.hits += 1
            return value

        def put(self, key, value):
            expire_at = (time.time() + self.ttl) if self.ttl else 0
            if key not in self._d:
                self.size += 1
            self._d[key] = (value, expire_at)

        def clear(self):
            self._d.clear()
            self.size = 0

    docindex.TTLCache = _TTLCache
    return "shimmed"

def main() -> int:
    import asyncio

    from sqlalchemy import select

    from app.database import Base, SessionLocal, engine
    from app import models as _models  # noqa: F401
    from app.models import DnaGene
    from app.services import dev as svc
    from app.services import dev_config, dna_library

    shim = _shim_docindex_ttlcache()
    if shim == "shimmed":
        print("（垫片：docindex 的 TTLCache 暂时缺失，已补一个最小实现让自测跑完）")

    print("== 1. 离线模式的出网闸门 ==")
    cfg = dev_config.load_config()
    dev_config.save_config({
        "mode": "offline",
        "outbound_enabled": True,
        "local_model": {"base_url": "", "model": ""},
        "github": {"token": "", "repos": []},
    })
    try:
        dev_config.assert_outbound("offline", "GitHub 仓库检索")
        check(False, "离线模式下出网请求被拦下")
    except dev_config.OutboundBlocked as e:
        check(True, "离线模式下出网请求被拦下：%s" % str(e)[:40])
    try:
        dev_config.assert_outbound("online", "GitHub 仓库检索", cfg=dev_config.load_config())
        check(True, "在线模式允许出网")
    except dev_config.OutboundBlocked:
        check(False, "在线模式允许出网")

    print("== 1b. 密钥口径：掩码返回、掩码回传不覆盖、能显式清除 ==")
    dev_config.save_config({"github": {"token": "ghp_secret_token_1234"}})
    pub = dev_config.public_config()
    check(str(pub["github"]["token"]).startswith("***"), "令牌对外是掩码")
    check(pub["github"]["token_set"] is True, "令牌「已设置」状态可见")
    check(dev_config.get_secret("github.token") == "ghp_secret_token_1234",
          "真值仍在磁盘上（掩码只是对外视图）")
    # 前端只改仓库地址时会把掩码原样回传 —— 这时候不能把真令牌抹掉
    dev_config.save_config({
        "github": {"token": pub["github"]["token"],
                   "repos": [{"owner": "a", "repo": "b"}]}})
    check(dev_config.get_secret("github.token") == "ghp_secret_token_1234",
          "掩码回传视为「不修改」")
    # 真要清空时有专门的通道
    dev_config.save_config({"github": {"token": ""},
                             "clear_secrets": ["github.token"]})
    check(dev_config.get_secret("github.token") == "", "显式清除生效")

    print("== 2. 缺配置时如实报「缺什么、怎么配」 ==")
    try:
        svc.ensure_model_available("offline")
        check(False, "没有模型端点时生成被拦下")
    except svc.DevError as e:
        check(bool(e.missing), "缺配置时给出 missing 清单：%s" % e.missing)
        check(bool(e.how_to_fix), "缺配置时给出 how_to_fix 清单：%s" % (e.how_to_fix or [""])[0][:40])

    print("== 3. 端到端：项目 → 方案 → 任务 → 产出物 → 会话 → 引用 ==")
    url, srv = start_mock()
    dev_config.save_config({
        "mode": "offline",
        "local_model": {"base_url": url, "model": "mock-model"},
    })
    check(dev_config.load_config()["local_model"]["base_url"] == url, "本地模型端点已配置")

    async def run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with SessionLocal() as db:
            # GitHub 取材在离线模式下必须被闸门拦住（不只是配置层）
            from app.services import dev_github
            try:
                await dev_github.repo_overview(
                    dev_config.load_config(), "offline",
                    dev_config.normalize_repo("owner/repo"))
                check(False, "离线模式下 GitHub 取材被拦下")
            except dev_config.OutboundBlocked:
                check(True, "离线模式下 GitHub 取材被闸门拦下")
            except Exception as e:
                check(False, "离线模式下 GitHub 取材被拦下（异常类型不对：%s）"
                      % type(e).__name__)

            # 模拟「喂养的源码知识」：先往养料库里塞一条基因
            gene, is_new = await dna_library.upsert_gene(
                db, kind="experience", title="对账前必须先归一化金额",
                content="账单金额单位不一致时（分/元/厘），先按金额字段名归一到元再比对，"
                        "否则差异会被放大 100 倍。",
                tags=["对账"], source_kind="code", source_ref="code:verify01",
                source_title="billing/normalize.py", confidence=0.7)
            check(is_new, "喂养的源码知识已入库（基因 #%s）" % gene.id)
            gene_id = gene.id

            p = await svc.create_project(
                db, {"name": "对账小工具", "goal": "比对两期账单并输出差异",
                     "tech_stack": ["Python", "SQLite"], "mode": "offline"},
                principal="verify")
            check(p.id > 0, "项目已创建（#%s）" % p.id)

            res = await svc.generate_plan(db, p)
            check(len(res["tasks"]) == 2, "方案拆出 %d 个任务" % len(res["tasks"]))
            check(res["tasks"][1]["depends_on"] == [res["tasks"][0]["id"]],
                  "任务依赖被翻译成真实 id")
            check(bool(res["session"]["id"]), "会话已落库（#%s）" % res["session"]["id"])
            check(len(res["citations"]) >= 1, "引用了 %d 条知识" % len(res["citations"]))
            check(any(c.get("gene_id") == gene_id for c in res["citations"]),
                  "引用命中了喂养的基因")
            check(p.status == "planning", "项目状态推进到「规划中」")

            task = await svc.get_task(db, res["tasks"][0]["id"])
            out = await svc.generate_task_output(db, p, task)
            check(len(out["artifacts"]) == 0, "含硬编码密钥的文件被安全体检拦下（未落库）")
            check(len(out["blocked"]) == 1, "被拦下的文件已回报（%d 个）" % len(out["blocked"]))
            check(bool(out["warnings"]), "安全告警带回前端（%d 条）" % len(out["warnings"]))

            # 一份干净的文件：走 force 落库（模拟用户确认后保留）
            out2 = await svc.generate_task_output(db, p, task, force=True)
            check(len(out2["artifacts"]) == 1, "force 模式下产出物落库")

            arts = await svc.list_artifacts(db, p.id)
            check(len(arts) == 1, "产出物清单可读（%d 个）" % len(arts))
            a = await svc.get_artifact(db, arts[0]["id"])
            a.accepted = True
            await db.commit()

            cites = await svc.list_citations(db, p.id)
            check(len(cites) >= 1, "引用清单可读（%d 条）" % len(cites))
            sessions = await svc.list_sessions(db, p.id)
            check(len(sessions) >= 2, "会话清单可读（%d 条）" % len(sessions))

            print("== 4. 产出物导入数据中心 ==")
            doc = await svc.import_artifact_to_library(db, a, mode="offline")
            check(bool(doc.get("id")), "产出物已进文件库（文档 #%s）" % doc.get("id"))
            check(a.document_id == doc.get("id"), "产出物回写了文档 id")

            print("== 5. 反哺知识库（闭环的关键一步） ==")
            before = (await db.execute(
                select(DnaGene).where(DnaGene.id == gene_id))).scalars().first()
            conf_before = float(before.confidence or 0)
            usage_before = int(before.usage_count or 0)

            report = await svc.feedback_to_library(db, p, lessons="金额要先归一再比对")
            check(report["round"] == 1, "反哺轮次 = %s" % report["round"])
            check(report["genes_created"] >= 1,
                  "沉淀出 %d 条新基因" % report["genes_created"])
            check(bool(report["confidence_raised"]),
                  "置信度有提升：%s" % (report["confidence_raised"] or []))
            check(bool(report["expression_raised"]),
                  "表达度有提升：%s" % (report["expression_raised"] or []))

            after = (await db.execute(
                select(DnaGene).where(DnaGene.id == gene_id))).scalars().first()
            check(float(after.confidence or 0) > conf_before,
                  "基因置信度 %.2f → %.2f" % (conf_before, float(after.confidence or 0)))
            check(int(after.usage_count or 0) > usage_before,
                  "基因表达度 %d → %d" % (usage_before, int(after.usage_count or 0)))

            print("== 6. 下一轮开发能用上沉淀的经验 ==")
            found = await dna_library.search_genes(db, "对账 金额 归一化", limit=10)
            titles = [g["gene"].title for g in found]
            check(any("对账" in t or "归一" in t for t in titles),
                  "新沉淀的经验可被检索到：%s" % (titles[:2] or ["无"]))

            print("== 7. HTTP 接口层（FastAPI TestClient） ==")
            from starlette.testclient import TestClient
            from app.main import app
            with TestClient(app) as client:
                r = client.get("/api/dev/config")
                check(r.status_code == 200, "GET /api/dev/config 200")
                body = r.json()
                check("local_model" in body and "github" in body, "配置返回结构完整")
                check(body["github"]["token"] == "" or body["github"]["token"].startswith("***"),
                      "令牌以掩码返回")

                r = client.get("/api/dev/projects")
                check(r.status_code == 200, "GET /api/dev/projects 200")
                check(len(r.json()["projects"]) >= 1, "项目清单能读到刚建的项目")

                r = client.post("/api/dev/projects", json={"name": "接口建的项目"})
                check(r.status_code == 200, "POST /api/dev/projects 200")
                pid = r.json()["project"]["id"]

                r = client.get("/api/dev/projects/%d" % pid)
                check(r.status_code == 200, "GET /api/dev/projects/{id} 200")
                check("tasks" in r.json() and "citations" in r.json(), "详情含任务与引用")

                r = client.post("/api/dev/projects/%d/tasks" % pid,
                                json={"title": "手工加的任务", "acceptance": "能跑"})
                check(r.status_code == 200, "POST 任务 200")

                # 断掉模型配置 → 生成必须如实报缺什么，而不是假成功
                dev_config.save_config({"local_model": {"base_url": "", "model": ""}})
                r = client.post("/api/dev/projects/%d/plan" % pid)
                check(r.status_code == 400, "缺模型时生成接口返回 400")
                err = r.json()
                check(bool(err.get("missing")) and bool(err.get("how_to_fix")),
                      "错误体带 missing / how_to_fix：%s" % err.get("detail"))

                # 离线模式下探测 GitHub：必须是「按策略跳过」，不发请求
                r = client.post("/api/dev/github/probe", json={"repo": "owner/repo"})
                check(r.status_code == 200, "GitHub 探测接口 200")
                check(r.json().get("skipped") is True, "离线模式下 GitHub 探测被跳过")

                r = client.get("/api/dev/doctor")
                check(r.status_code == 200, "GET /api/dev/doctor 200")
                doc_body = r.json()
                check(bool(doc_body.get("capabilities")), "自检返回能力清单")
                check(doc_body.get("mode") == "offline", "自检显示当前是离线模式")

                # 页面权限位要补进内置角色（老库也得能进这个页面）
                from app.models import Role
                roles = (await db.execute(select(Role))).scalars().all()
                dev_roles = [r for r in roles if "dev" in ((r.perms or {}).get("pages") or [])]
                check(bool(dev_roles),
                      "内置角色的页面权限已补上 dev（%d/%d 个角色）"
                      % (len(dev_roles), len(roles)))

    asyncio.run(run())
    srv.shutdown()

    print("")
    if FAILURES:
        print("✗ %d 项未通过（共 %d 项）：" % (len(FAILURES), CHECKS))
        for f in FAILURES:
            print("   - %s" % f)
        return 1
    print("✓ 全部 %d 项通过" % CHECKS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
