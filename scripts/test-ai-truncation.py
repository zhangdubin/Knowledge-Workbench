#!/usr/bin/env python3
"""AI 回答「被截断」问题的回归测试

为什么要有这个文件：
用户反馈「AI 助理对话后回复的内容会被截断，没有回复全」。
根因是多处的，而每一处都可能单独回归 ——
所以把「什么情况下必须报 truncated、什么情况下必须加大 max_tokens 重试」
钉成断言，以后改 AI 调用代码时一跑就知道有没有把修复改坏。

跑法（不需要 pytest，也不需要数据库）：
    cd kb-workbench && python3 scripts/test-ai-truncation.py

在容器里跑（容器里才有 fastapi/sqlalchemy 这些依赖）：
    docker run --rm -v "$PWD:/repo" --entrypoint python kb-workbench-backend \
      /repo/scripts/test-ai-truncation.py
    docker exec -w /app kb-backend python /repo/scripts/test-ai-truncation.py

用 pytest 也能收集（如果环境里有 pytest）：
    pytest scripts/test-ai-truncation.py -v
"""
import asyncio
import json
import sys
import unittest
from pathlib import Path

DOCKER_CMD = 'docker run --rm -v "$PWD:/repo" --entrypoint python kb-workbench-backend /repo/scripts/test-ai-truncation.py'

# 环境自检：脚本要跑在后端的运行环境里（Python 3.10+ / SQLAlchemy 2.x）。
#
# 为什么必须先自检：缺依赖时裸报错是
# "unsupported operand type(s) for |"（3.9 不认 PEP 604 的类型写法）
# 或 "No module named 'app'"，跟脚本在验什么毫无关系，最容易把人带偏。
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

# 把「app 包所在的目录」加进 sys.path。
#
# 为什么不是一个固定路径：同一个脚本有好几种跑法 ——
# 仓库根目录下跑（ROOT/backend）、容器里把仓库挂到 /repo（/repo/backend）、
# 容器里代码装在 /app（/app 本身就是 app 包的父目录）。
# 写死一种，另外两种就报 ModuleNotFoundError: No module named 'app'，
# 而这种错跟测试本身毫无关系，最容易把人带偏。
def _add_app_path() -> None:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "backend",   # 仓库根目录布局
        here.parent.parent,               # 仓库被整体挂进来时
        Path("/app"),                      # 容器里代码装在 /app
        Path("/repo/backend"),             # 容器里仓库挂在 /repo
    ]
    for c in candidates:
        if (c / "app" / "services").is_dir():
            sys.path.insert(0, str(c))
            return
    raise SystemExit(
        "找不到 app 包：请在仓库根目录下跑，"
        "或用 docker run -v \"$PWD:/repo\" ... /repo/scripts/test-ai-truncation.py")


_add_app_path()

from app.services import ai as ai_svc              # noqa: E402
from app.services import ai_config as cfg_svc     # noqa: E402
from app.services import agent as agent_svc       # noqa: E402


# ============ 假的 HTTP 客户端 ============

class FakeResponse:
    """假的 httpx 响应"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)


class FakeAsyncClient:
    """替换 httpx.AsyncClient：按脚本回放响应，并记录每次请求的 max_tokens

    记录请求体是这里的关键 ——
    「有没有加大 max_tokens 重试」只能从请求体上看出来。
    """

    queue = []          # 预设响应
    requests = []       # 实际发出的请求体

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, **kwargs):
        # 必须拷贝一份：真实代码会原地改 payload 的 max_tokens，
        # 记同一个对象的话几次请求看起来就都是最后一次的值。
        FakeAsyncClient.requests.append(dict(json or {}))
        if not FakeAsyncClient.queue:
            raise AssertionError("FakeAsyncClient 没有可回放的响应了")
        return FakeAsyncClient.queue.pop(0)


def install_fake_http(monkey, responses):
    monkey.setattr(ai_svc.httpx, "AsyncClient", FakeAsyncClient)
    monkey.setattr(agent_svc.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.queue = [FakeResponse(r) for r in responses]
    FakeAsyncClient.requests = []


def fake_config(**over):
    """一份测试用配置（不读磁盘、不联网）"""
    cfg = {
        "enabled": True,
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1/chat/completions",
        "model": "test-model",
        "temperature": 0.3,
        "max_tokens": 4096,
        "auto_retry_on_truncation": True,
        "max_tokens_ceiling": 32768,
        "agent_write": True,
    }
    cfg.update(over)
    return cfg


class Monkey:
    """极简 monkeypatch：setattr 之后可以统一还原"""

    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        old = getattr(obj, name)
        self._undo.append((obj, name, old))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo = []


def completion(content="", finish_reason="stop"):
    """构造一个 OpenAI 兼容的响应体"""
    return {
        "model": "test-model",
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": content},
                     "finish_reason": finish_reason}],
        "usage": {"total_tokens": 10},
    }


# ============ 用例 ============

class TestTruncation(unittest.TestCase):

    def setUp(self):
        self.m = Monkey()

    def tearDown(self):
        self.m.undo()
        FakeAsyncClient.queue = []
        FakeAsyncClient.requests = []

    # ---------- 配置层 ----------

    def test_default_max_tokens_is_4096(self):
        """默认长度上限必须是 4096 —— 1024 太小，模型写两句就被切断"""
        self.assertEqual(cfg_svc.DEFAULT_CONFIG["max_tokens"], 4096)

    def test_legacy_1024_is_migrated(self):
        """磁盘上留着老默认 1024 时要抬到 4096（否则修复对老用户不生效）"""
        raw = {"max_tokens": 1024}
        self.assertEqual(cfg_svc.effective_max_tokens(raw), 4096)
        # 用户显式改过（迁移标记在）就不再动
        raw2 = {"max_tokens": 1024, "max_tokens_migrated": True}
        self.assertEqual(cfg_svc.effective_max_tokens(raw2), 1024)

    def test_get_max_tokens_clamps(self):
        """用户乱填的值要夹回合法区间"""
        self.assertEqual(cfg_svc.get_max_tokens({"max_tokens": 0}), cfg_svc.MIN_MAX_TOKENS)
        self.assertEqual(cfg_svc.get_max_tokens({"max_tokens": -5}), cfg_svc.MIN_MAX_TOKENS)
        self.assertEqual(cfg_svc.get_max_tokens({"max_tokens": 10 ** 9}),
                         cfg_svc.HARD_MAX_TOKENS)
        self.assertEqual(cfg_svc.get_max_tokens({"max_tokens": "2048"}), 2048)

    def test_ceiling_never_below_current(self):
        """天花板不能低于当前上限（用户调小了就是不想让回答太长）"""
        ceil = cfg_svc.get_max_tokens_ceiling({"max_tokens": 8192,
                                                "max_tokens_ceiling": 4096})
        self.assertEqual(ceil, 8192)

    # ---------- finish_reason → truncated ----------

    def test_length_finish_detected(self):
        """各家厂商的「被长度切断」写法都要认出来"""
        for fr in ("length", "Length", "max_tokens", "max_output_tokens", "truncated"):
            self.assertTrue(ai_svc.is_length_finish(fr), fr)
        for fr in ("stop", "tool_calls", "content_filter", None, ""):
            self.assertFalse(ai_svc.is_length_finish(fr), fr)

    def test_truncated_flag_returned(self):
        """finish_reason=length → truncated=True（前端据此提示 + 给续写入口）"""
        self.m.setattr(cfg_svc, "get_full_config",
                       lambda cfg=None: fake_config(max_tokens=4096,
                                                    max_tokens_ceiling=4096))
        install_fake_http(self.m, [completion("写到一半就被砍断了", "length")])
        meta = asyncio.run(ai_svc.chat_real_meta(
            [{"role": "user", "content": "写个长点的东西"}]))
        self.assertTrue(meta["truncated"], meta)
        self.assertEqual(meta["finish_reason"], "length")
        self.assertIn("砍断", meta["content"])

    def test_not_truncated_when_stop(self):
        """正常写完不该报截断"""
        self.m.setattr(cfg_svc, "get_full_config", lambda cfg=None: fake_config())
        install_fake_http(self.m, [completion("完整答案", "stop")])
        meta = asyncio.run(ai_svc.chat_real_meta([{"role": "user", "content": "你好"}]))
        self.assertFalse(meta["truncated"])
        self.assertEqual(meta["finish_reason"], "stop")

    # ---------- 通用「加大 max_tokens 重试」 ----------

    def test_length_triggers_bigger_retry(self):
        """被长度切断 → 自动加大 max_tokens 重试（不是只针对空回答）"""
        self.m.setattr(cfg_svc, "get_full_config", lambda cfg=None: fake_config())
        install_fake_http(self.m, [
            completion("半截", "length"),
            completion("完整答案", "stop"),
        ])
        meta = asyncio.run(ai_svc.chat_real_meta([{"role": "user", "content": "写长点"}]))
        self.assertTrue(meta["retried"])
        self.assertFalse(meta["truncated"])
        self.assertEqual(meta["content"], "完整答案")
        self.assertEqual(len(FakeAsyncClient.requests), 2)
        self.assertEqual(FakeAsyncClient.requests[0]["max_tokens"], 4096)
        self.assertEqual(FakeAsyncClient.requests[1]["max_tokens"], 8192)

    def test_empty_content_triggers_bigger_retry(self):
        """空回答（token 全花在思考块上）→ 同样加大 max_tokens 重试"""
        self.m.setattr(cfg_svc, "get_full_config", lambda cfg=None: fake_config())
        install_fake_http(self.m, [
            completion("<think>想了很久</think>", "length"),
            completion("终于说人话了", "stop"),
        ])
        meta = asyncio.run(ai_svc.chat_real_meta([{"role": "user", "content": "在吗"}]))
        self.assertEqual(len(FakeAsyncClient.requests), 2)
        self.assertGreater(FakeAsyncClient.requests[1]["max_tokens"],
                           FakeAsyncClient.requests[0]["max_tokens"])
        self.assertEqual(meta["content"], "终于说人话了")

    def test_retry_respects_ceiling(self):
        """加到天花板还是被切断 → 老实报 truncated，不再无限加大"""
        self.m.setattr(cfg_svc, "get_full_config",
                       lambda cfg=None: fake_config(max_tokens=4096,
                                                    max_tokens_ceiling=4096))
        install_fake_http(self.m, [completion("还是半截", "length")])
        meta = asyncio.run(ai_svc.chat_real_meta([{"role": "user", "content": "写长点"}]))
        self.assertTrue(meta["truncated"])
        self.assertEqual(len(FakeAsyncClient.requests), 1)

    def test_unclosed_reasoning_is_reported(self):
        """思考块没闭合（多半是被长度切断）→ 要能看出来"""
        _clean, info = ai_svc.scrub_reasoning_ex("<think>我先想想")
        self.assertTrue(info["unclosed"])
        self.assertTrue(info["dropped"])
        clean, info2 = ai_svc.scrub_reasoning_ex("<think>思考</think>正文")
        self.assertEqual(clean, "正文")
        self.assertFalse(info2["unclosed"])

    # ---------- Agent 层 ----------

    def test_agent_chat_once_reports_truncation(self):
        """Agent 单次调用也要报截断（以前完全不看 finish_reason）"""
        self.m.setattr(cfg_svc, "get_full_config",
                       lambda cfg=None: fake_config(max_tokens=4096,
                                                    max_tokens_ceiling=4096))
        install_fake_http(self.m, [completion("半截回答", "length")])
        resp = asyncio.run(agent_svc._chat_once([{"role": "user", "content": "查一下"}]))
        self.assertTrue(resp["truncated"])
        self.assertEqual(resp["finish_reason"], "length")

    def test_agent_retries_with_bigger_budget(self):
        """Agent 被截断时也要加大 max_tokens 重试"""
        self.m.setattr(cfg_svc, "get_full_config", lambda cfg=None: fake_config())
        install_fake_http(self.m, [
            completion("半截回答", "length"),
            completion("完整回答", "stop"),
        ])
        resp = asyncio.run(agent_svc._chat_once([{"role": "user", "content": "查一下"}]))
        self.assertTrue(resp["retried"])
        self.assertFalse(resp["truncated"])
        self.assertEqual(resp["content"], "完整回答")
        self.assertGreater(FakeAsyncClient.requests[1]["max_tokens"],
                           FakeAsyncClient.requests[0]["max_tokens"])

    def test_tool_result_truncation_is_marked(self):
        """工具结果太长 → 明确标记被截断 + 给出总长度（不能静默 slice）"""
        big = {"rows": ["x" * 100 for _ in range(400)]}
        entry = agent_svc.tool_trace_entry("search_records", {"keyword": "报销"}, big)
        self.assertTrue(entry["result_truncated"])
        self.assertGreater(entry["result_chars"], agent_svc.TOOL_RESULT_DISPLAY_MAX)
        self.assertIn("note", entry["result"])

        small = agent_svc.tool_trace_entry("list_models", {}, {"models": [1, 2]})
        self.assertFalse(small["result_truncated"])
        self.assertEqual(small["result"], {"models": [1, 2]})

    def test_tool_result_for_model_is_capped(self):
        """回灌给模型的工具结果也要限长，并明确说明被截断"""
        big = {"rows": ["y" * 100 for _ in range(400)]}
        capped = agent_svc.tool_result_for_model(big)
        self.assertIn("note", capped)
        self.assertLessEqual(len(capped["preview"]), agent_svc.TOOL_RESULT_MODEL_MAX)

    def test_history_keeps_tail(self):
        """历史不能简单 [:4000]：上一轮回答的「尾巴」是续写的断点，不能丢"""
        long_answer = "开头" + ("中间" * 8000) + "结尾断点"
        pairs = agent_svc.build_history([
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": long_answer},
        ])
        self.assertEqual(len(pairs), 2)
        kept = pairs[1][1]
        self.assertIn("开头", kept)
        self.assertIn("结尾断点", kept)
        self.assertLess(len(kept), len(long_answer))

    def test_continuation_tail_keeps_end(self):
        """续写回灌的已有内容要保留尾巴"""
        tail = ai_svc.continuation_tail("x" * 5000 + "断点在这里")
        self.assertTrue(tail.endswith("断点在这里"))
        self.assertLess(len(tail), 5000 + 100)

    def test_run_agent_supports_continuation(self):
        """续写：把已有内容回灌 + 明确要求「不要重复」，并返回截断标记"""
        seen = {}

        async def fake_chat_once(messages, **kwargs):
            seen["messages"] = messages
            return {"content": "续写的内容", "tool_calls": [], "finish_reason": "stop",
                    "truncated": False, "retried": False, "max_tokens": 4096}

        self.m.setattr(agent_svc, "_chat_once", fake_chat_once)
        self.m.setattr(cfg_svc, "get_full_config", lambda cfg=None: fake_config())
        out = asyncio.run(agent_svc.run_agent(
            None, "原始问题", None, [], continuation="已经写出来的半截答案"))
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["answer"], "续写的内容")
        self.assertFalse(out["truncated"])
        self.assertIn("truncated", out)
        msgs = seen["messages"]
        self.assertTrue(any(m.get("role") == "assistant" and
                            "已经写出来的半截答案" in (m.get("content") or "")
                            for m in msgs))
        self.assertTrue(any(m.get("role") == "user" and
                            "继续写作" in (m.get("content") or "")
                            for m in msgs))

    def test_run_agent_empty_answer_is_explained(self):
        """模型一个字都没给时，要说清楚原因，而不是给一个空白气泡"""
        async def fake_chat_once(messages, **kwargs):
            return {"content": "", "tool_calls": [], "finish_reason": "length",
                    "truncated": True, "retried": False, "max_tokens": 4096}

        self.m.setattr(agent_svc, "_chat_once", fake_chat_once)
        self.m.setattr(cfg_svc, "get_full_config", lambda cfg=None: fake_config())
        out = asyncio.run(agent_svc.run_agent(None, "问题", None, []))
        self.assertTrue(out["truncated"])
        self.assertIn("长度上限", out["answer"])


class TestRouterContract(unittest.TestCase):
    """接口契约：前端要拿得到 truncated / finish_reason / continuation"""

    def test_request_models(self):
        from app.routers import ai as ai_router
        cfg = ai_router.ConfigIn()
        self.assertEqual(cfg.max_tokens, 4096)
        self.assertTrue(cfg.auto_retry_on_truncation)
        self.assertEqual(cfg.max_tokens_ceiling, 32768)
        self.assertEqual(ai_router.AgentIn(question="q").continuation, "")
        self.assertEqual(ai_router.AskIn(question="q").continuation, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
