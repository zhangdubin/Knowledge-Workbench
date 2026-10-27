#!/usr/bin/env python3
"""升级仓库 / 出站代理配置可视化 —— 后端自测（离线可跑）

验证六件事：

  1. 仓库标识的格式校验：合法 / 非法 / 带结尾斜杠 / 空；
  2. 界面上保存 update_repo 后，「检查更新」立刻读到的就是新值
     —— 不需要重启容器；
  3. 换了仓库之后不会命中旧仓库的缓存（缓存 key 必须带仓库）；
  4. 「未配置」与「配了但格式非法」能被区分开；
  5. 出站代理的校验，以及它确实被带进了出站请求；
  6. 一项校验不过则整体不落盘（不会出现半套配置）。

跑法（一次性容器挂当前源码，不碰线上容器）：

  cd /Volumes/Samsung/poc/知识库/kb-workbench
  docker run --rm \
    -v "$PWD/backend/app:/app/app:ro" \
    -v "$PWD/scripts:/scripts:ro" \
    --entrypoint python kb-workbench-backend /scripts/v23-verify-update-config.py

两个自我保护措施：

  - 脚本自己把 DATA_DIR 钉到临时目录 —— settings_store 的配置文件路径
    在导入时就算好了，指错了会写到真实的 data/bootstrap.json 上，
    把线上用户的配置冲掉；
  - 网络层用假客户端替换掉，全程不连 GitHub（离线可跑、结果稳定）。
"""
import asyncio
import os
import sys
import tempfile

# ---- 必须赶在 import app.* 之前把数据目录钉死 ----
_TMP_DIR = os.path.join(tempfile.gettempdir(), "kb-upgrade-config-test")
os.environ["DATA_DIR"] = _TMP_DIR
os.makedirs(_TMP_DIR, exist_ok=True)

# 脚本在 /scripts 下运行，app 包在 /app 下：把 /app 加进模块搜索路径
for _p in ("/app", os.getcwd()):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import httpx  # noqa: E402  （必须在钉好 DATA_DIR 之后）

from app.services import audit as audit_svc      # noqa: E402
from app.services import settings_store as ss     # noqa: E402
from app.services import update as upd            # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, extra: str = "") -> bool:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'✓' if ok else '✗'} {label}" + (f" — {extra}" if extra else ""))
    return ok


# ============================================================ 假网络层

# 两个仓库，各给一个版本号：alpha 比当前版本新，beta 比当前版本旧。
# 这样「有新版本」与「已是最新」两条分支都能被覆盖。
RELEASES = {
    "test-owner/alpha": {
        "tag_name": "v9.9.9", "name": "Alpha 9.9.9", "body": "alpha notes",
        "html_url": "https://example.invalid/alpha",
        "published_at": "2026-01-02T03:04:05Z",
    },
    "test-owner/beta": {
        "tag_name": "v0.0.1", "name": "Beta 0.0.1", "body": "beta notes",
        "html_url": "https://example.invalid/beta",
        "published_at": "2026-02-02T03:04:05Z",
    },
}
# empty 这个仓库存在但没发过 Release → GitHub 对「没有 Release」也返回 404
EXISTING_REPOS = {"test-owner/alpha", "test-owner/beta", "test-owner/empty"}


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}",
                                        request=None, response=None)


class FakeClient:
    """顶替 httpx.AsyncClient：记录请求过的 URL 与客户端参数"""

    calls: list[tuple[str, dict]] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, *args, **kwargs):
        FakeClient.calls.append((url, dict(self.kwargs)))
        repo = url.split("/repos/", 1)[-1].split("/releases")[0]
        if url.endswith("/releases/latest"):
            if repo in RELEASES:
                return FakeResponse(200, RELEASES[repo])
            return FakeResponse(404)
        # 仓库信息接口：用来区分「仓库不存在」与「仓库没发过 Release」
        if repo in EXISTING_REPOS:
            return FakeResponse(200, {"full_name": repo})
        return FakeResponse(404)


# ============================================================ 用例


async def case_format() -> None:
    print("\n[1/6] 仓库标识的格式校验")
    ok, val, err, _ = ss.validate("update_repo", "your-org/kb-workbench")
    check("合法仓库通过校验", ok and val == "your-org/kb-workbench", f"归一化结果 {val!r}")

    ok, val, err, _ = ss.validate("update_repo", "your-org/kb-workbench/")
    check("结尾斜杠被容错并归一化", ok and val == "your-org/kb-workbench", f"归一化结果 {val!r}")

    ok, val, err, _ = ss.validate("update_repo", "  https://github.com/your-org/kb-workbench  ")
    check("GitHub 网址写法被归一化", ok and val == "your-org/kb-workbench", f"归一化结果 {val!r}")

    ok, val, err, _ = ss.validate("update_repo", "")
    check("空值合法（表示不配置）", ok and val == "", f"归一化结果 {val!r}")

    for bad in ("kb-workbench", "a/b/c", "/name", "owner/", "own er/name"):
        ok, val, err, _ = ss.validate("update_repo", bad)
        check(f"非法值被拒绝：{bad!r}", (not ok) and bool(err), err)


async def case_effective() -> None:
    print("\n[2/6] 保存后立即生效（不重启容器）")
    res = await ss.set_many({"update_repo": "test-owner/alpha"}, who="verify")
    check("保存成功", bool(res.get("ok")), str(res.get("error") or ""))

    value, source = ss.effective("update_repo")
    check("生效值来自「系统设置」这一层", value == "test-owner/alpha" and source == "file",
          f"{value!r} / {source}")

    info = await upd.check_update()
    check("检查更新读到的就是刚保存的仓库", info.get("repo") == "test-owner/alpha",
          f"repo={info.get('repo')!r}")
    check("拿到了该仓库的版本号", info.get("latest") == "v9.9.9", f"latest={info.get('latest')!r}")
    check("状态是「有新版本」", info.get("status") == "update_available",
          f"status={info.get('status')!r}")
    check("有更新时 has_update 为真", info.get("has_update") is True)

    # 结尾斜杠在保存时就被归一化掉了，落盘的是干净的值
    await ss.set_many({"update_repo": "test-owner/beta/"}, who="verify")
    value, _ = ss.effective("update_repo")
    check("落盘的是归一化后的值（不含结尾斜杠）", value == "test-owner/beta", f"{value!r}")


async def case_cache() -> None:
    print("\n[3/6] 缓存不会串仓库")
    # 清一下缓存：上一个用例查过同一个仓库，不清的话第一个断言
    # 「首次检查真的发了请求」会因命中缓存而不成立
    upd._cache.clear()
    await ss.set_many({"update_repo": "test-owner/alpha"}, who="verify")
    FakeClient.calls.clear()
    info = await upd.check_update()
    check("首次检查真的发了请求", len(FakeClient.calls) == 1, f"请求数 {len(FakeClient.calls)}")
    check("结果是 alpha 的版本", info.get("latest") == "v9.9.9", f"latest={info.get('latest')!r}")

    info2 = await upd.check_update()
    check("同一仓库再查命中缓存（没再发请求）", len(FakeClient.calls) == 1,
          f"请求数 {len(FakeClient.calls)}")
    check("命中缓存的结果与之前一致", info2.get("latest") == "v9.9.9")

    # 换仓库 —— 这一步是本用例的重点：旧仓库的缓存不能被新仓库复用
    await ss.set_many({"update_repo": "test-owner/beta"}, who="verify")
    info3 = await upd.check_update()
    check("换仓库后重新发请求（未命中旧仓库的缓存）", len(FakeClient.calls) == 2,
          f"请求数 {len(FakeClient.calls)}")
    check("结果来自新仓库", info3.get("repo") == "test-owner/beta"
          and info3.get("latest") == "v0.0.1", f"{info3.get('repo')!r} / {info3.get('latest')!r}")
    check("版本比当前版本旧时状态是「已是最新」", info3.get("status") == "up_to_date",
          f"status={info3.get('status')!r}")
    check("已是最新时 has_update 为假", info3.get("has_update") is False)


async def case_not_configured() -> None:
    print("\n[4/6] 未配置 / 非法配置 / 仓库不存在 能分开")
    await ss.reset("update_repo", who="verify")
    os.environ.pop("UPDATE_REPO", None)
    os.environ.pop("KB_UPDATE_REPO", None)

    # 上一行把环境变量清掉了还不够：effective() 的最后一级兜底是
    # pydantic 的 settings 对象，而它是 **import 时** 就从环境里把
    # KB_UPDATE_REPO 读进去的 —— 之后再 pop os.environ 对它无效。
    # 所以这里要把这层默认值也一并按住，否则在「.env 里配了仓库」的
    # 机器上永远测不出「未配置」这个分支（环境变量兜底是正常功能，不能动）。
    saved_repo = ss.settings.update_repo
    ss.settings.update_repo = ""
    try:
        info = await upd.check_update()
        check("未配置时 configured 为假", info.get("configured") is False)
        check("未配置时状态是 not_configured", info.get("status") == "not_configured",
              f"status={info.get('status')!r}")
        check("未配置时告诉用户去哪配", "升级与更新" in (info.get("error") or ""),
              (info.get("error") or "")[:60])
        check("未配置时没有原始异常抛出", "Traceback" not in (info.get("error") or ""))
    finally:
        ss.settings.update_repo = saved_repo

    # 非法值只可能来自 .env / 环境变量 —— 它绕过了界面上的校验
    os.environ["UPDATE_REPO"] = "not-a-valid-repo"
    info = await upd.check_update()
    check("配了但格式非法时状态是 invalid_config", info.get("status") == "invalid_config",
          f"status={info.get('status')!r}")
    check("非法配置与未配置能区分开", info.get("status") != "not_configured")
    check("非法配置的错误说明是人话", "owner/name" in (info.get("error") or ""),
          (info.get("error") or "")[:60])
    os.environ.pop("UPDATE_REPO", None)

    # 环境变量这一层仍然有效（老用户用 .env 配过的不能被打断）
    os.environ["UPDATE_REPO"] = "test-owner/beta"
    value, source = ss.effective("update_repo")
    check("环境变量这一层被认出来", value == "test-owner/beta" and source == "env",
          f"{value!r} / {source}")
    os.environ.pop("UPDATE_REPO", None)

    # 仓库不存在 vs 仓库没发过 Release：GitHub 一律返回 404，得靠补查分开
    await ss.set_many({"update_repo": "test-owner/empty"}, who="verify")
    info = await upd.check_update()
    check("仓库存在但没有 Release 时状态是 no_release", info.get("status") == "no_release",
          f"status={info.get('status')!r}")

    await ss.set_many({"update_repo": "test-owner/ghost"}, who="verify")
    info = await upd.check_update()
    check("仓库不存在时状态是 repo_not_found", info.get("status") == "repo_not_found",
          f"status={info.get('status')!r}")


async def case_proxy() -> None:
    print("\n[5/6] 出站代理")
    ok, val, err, _ = ss.validate("update_proxy", "http://10.0.0.5:1080")
    check("合法代理通过校验", ok and val == "http://10.0.0.5:1080", f"{val!r}")
    ok, val, err, _ = ss.validate("update_proxy", "")
    check("空代理合法（直连）", ok and val == "", f"{val!r}")
    for bad in ("10.0.0.5:1080", "ftp://h:1", "http://", "http://h/x", "http://h:abc"):
        ok, val, err, _ = ss.validate("update_proxy", bad)
        check(f"非法代理被拒绝：{bad!r}", (not ok) and bool(err), err)

    res = await ss.set_many({"update_repo": "test-owner/alpha",
                              "update_proxy": "http://10.0.0.5:1080"}, who="verify")
    check("仓库 + 代理一起保存成功", bool(res.get("ok")), str(res.get("error") or ""))

    FakeClient.calls.clear()
    await upd.check_update(refresh=True)
    proxies = [kw.get("proxy") for _, kw in FakeClient.calls]
    check("代理被带进了出站请求", bool(proxies) and all(p == "http://10.0.0.5:1080" for p in proxies),
          str(proxies))

    await ss.set_many({"update_proxy": ""}, who="verify")
    FakeClient.calls.clear()
    await upd.check_update(refresh=True)
    proxies = [kw.get("proxy") for _, kw in FakeClient.calls]
    check("代理清空后回到直连", bool(proxies) and all(p is None for p in proxies), str(proxies))


async def case_atomic() -> None:
    print("\n[6/6] 一项不合法则整体不落盘")
    await ss.set_many({"update_repo": "test-owner/alpha"}, who="verify")
    before, _ = ss.effective("update_repo")

    res = await ss.set_many({"update_repo": "test-owner/beta",
                              "update_proxy": "这不是一个合法的代理地址"}, who="verify")
    check("有一项不合法则整体拒绝", res.get("ok") is False, str(res.get("error") or ""))

    after, _ = ss.effective("update_repo")
    check("仓库的值没有被半途改掉", before == after, f"{before!r} -> {after!r}")
    proxy, _ = ss.effective("update_proxy")
    check("代理也没被写进去", not proxy, f"{proxy!r}")


async def main() -> int:
    # 把 httpx 的客户端换成假的：全程不连 GitHub，结果稳定且离线可跑
    httpx.AsyncClient = FakeClient

    # 审计写入要连数据库，这里换成不依赖库的假实现：
    # 本脚本只关心配置行为，不该去建库、建表
    async def fake_log_event(username, action, **kwargs):
        return None

    audit_svc.log_event = fake_log_event

    # 缓存从干净状态开始，避免上一个用例的残留影响判断
    upd._cache.clear()

    print("=" * 62)
    print("升级仓库 / 出站代理配置 —— 后端自测")
    print(f"数据目录（临时）：{_TMP_DIR}")
    print(f"配置文件：{ss.BOOTSTRAP_FILE}")
    print("=" * 62)

    await case_format()
    await case_effective()
    await case_cache()
    await case_not_configured()
    await case_proxy()
    await case_atomic()

    print("\n" + "=" * 62)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print(f"  ✗ {f}")
    print("=" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
