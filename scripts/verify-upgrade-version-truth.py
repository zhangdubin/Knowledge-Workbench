#!/usr/bin/env python3
"""一键升级的「版本对账」自检

要验的是这次修掉的那个毛病：
点完「一键升级」，界面说「升级完成，请刷新页面」，
刷新后版本号却一点没变 —— 而且**全程没有任何报错**。

两条防线都要在这里被证明有效：

  1. 后端（backend/app/services/upgrade.py）
     容器重启后，新进程要拿自己的版本号（settings.app_version）
     跟作业的目标版本对账。对不上 → 作业判**失败**，并给出能照着做的提示。
  2. 离线升级（同一文件）
     新镜像必须被打到编排文件**真正引用**的那个镜像名上，
     重启时必须带 --no-build（否则 compose 会拿旧源码重建一遍）。

怎么做到不依赖整套后端：
upgrade.py 会 import app.config（pydantic_settings）、app.services.audit
（starlette + sqlalchemy）…… 宿主机上未必装得齐，而我们要验的只是
「版本对账」与「镜像名解析」这两段纯逻辑。
所以这里把重依赖换成最小的假实现，**原样加载工作区里的 upgrade.py**，
再用假的编排文件与假的版本号把各种情形走一遍。

用法：
    python3 scripts/verify-upgrade-version-truth.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
UPGRADE_PY = BACKEND / "app" / "services" / "upgrade.py"


# ==================== 小工具 ====================

_failures: list[str] = []
_checks = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    """记一条检查结果（不抛异常 —— 一次跑完所有情形，结果一次汇总）"""
    global _checks
    _checks += 1
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        if detail:
            print(f"      {detail}")
        _failures.append(label)
    return bool(cond)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ==================== 加载被测模块 ====================

class _FakeSettings:
    """替身 app.config.settings —— 只提供 upgrade.py 真正用到的那几个字段"""

    def __init__(self, data_dir: str):
        self.app_version = "0.6.9"
        self.app_name = "知识管理工作台"
        self.data_dir = data_dir
        self.auth_enabled = True


def load_upgrade_module(data_dir: str):
    """原样加载工作区里的 backend/app/services/upgrade.py

    重依赖全部换成假实现：我们要验的是纯逻辑，
    不该因为宿主机上没装 starlette 就跑不起来。
    """
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = [str(BACKEND / "app")]
    services_pkg = types.ModuleType("app.services")
    services_pkg.__path__ = [str(BACKEND / "app" / "services")]
    app_pkg.services = services_pkg
    sys.modules["app"] = app_pkg
    sys.modules["app.services"] = services_pkg

    config_mod = types.ModuleType("app.config")
    config_mod.settings = _FakeSettings(data_dir)
    sys.modules["app.config"] = config_mod
    app_pkg.config = config_mod

    # 这三个模块 upgrade.py 只在运行时用到，导入期给个空壳即可
    for name in ("audit", "settings_store", "update"):
        mod = types.ModuleType(f"app.services.{name}")
        sys.modules[f"app.services.{name}"] = mod
        setattr(services_pkg, name, mod)

    # httpx：装不上就用假实现（upgrade.py 只在真正联网时才用它）
    try:
        import httpx  # noqa: F401
    except Exception:                       # pragma: no cover - 取决于宿主机环境
        httpx_stub = types.ModuleType("httpx")
        httpx_stub.AsyncClient = object      # type: ignore[attr-defined]
        sys.modules["httpx"] = httpx_stub

    spec = importlib.util.spec_from_file_location("app.services.upgrade", UPGRADE_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"加载不了 {UPGRADE_PY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["app.services.upgrade"] = module
    spec.loader.exec_module(module)
    return module, config_mod


def write_state(module, payload: dict) -> None:
    """往状态文件里写一个「上次升级留下的现场」"""
    module.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    module.STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def restarting_state(target: str, current: str = "0.6.8") -> dict:
    """一份「上个进程写到 restarting 就没了」的状态文件内容"""
    return {
        "job_id": "testjob0001",
        "status": "restarting",
        "stage": "restart",
        "stage_title": "重启服务",
        "target": target,
        "current": current,
        "mode": "git",
        "root": "/app/project",
        "compose_cmd": "docker compose",
        "steps": [],
        "log": "$ docker compose up -d\n正在重建容器，服务会短暂中断……",
        "log_lines": 2,
        "log_truncated": False,
        "error": "",
        "who": "tester",
        "started_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-01 00:00:01",
        "finished_at": "",
    }


# ==================== 用例 ====================

def test_restored_job_version_mismatch(module, config_mod) -> None:
    """核心用例：重启完了，但跑的还是旧版本 → 必须判失败，不能说成功"""
    section("后端：重启后的版本对账（不匹配 → 失败）")

    config_mod.settings.app_version = "0.6.8"
    module._current_job = None
    write_state(module, restarting_state(target="v0.6.9", current="0.6.8"))

    res = module.get_job()
    job = res.get("job") or {}

    check(job.get("status") == module.ST_FAILED,
          "版本对不上时作业判为 failed",
          f"实际 status={job.get('status')!r}")
    err = str(job.get("error") or "")
    check("0.6.8" in err and "0.6.9" in err,
          "失败原因里同时写清「现在跑的是哪版」和「目标是哪版」",
          f"error={err!r}")
    check("升级没有真正生效" in err,
          "失败原因明说「升级没有真正生效」",
          f"error={err!r}")
    check("docker compose logs backend" in err,
          "失败原因给出下一步该查什么",
          f"error={err!r}")
    check(err in str(job.get("log") or ""),
          "同一段话也写进了作业日志（弹窗日志框里要看得见）",
          f"log={job.get('log')!r}")

    # 再查一次：不能反复追加同一段话（日志会被刷爆）
    res2 = module.get_job()
    log2 = str((res2.get("job") or {}).get("log") or "")
    check(log2.count("升级没有真正生效") == 1,
          "重复查询不会把同一段话追加很多遍",
          f"出现了 {log2.count('升级没有真正生效')} 次")


def test_restored_job_version_match(module, config_mod) -> None:
    """匹配时才算成功，并且要说清「确认过是哪一版」"""
    section("后端：重启后的版本对账（匹配 → 成功）")

    config_mod.settings.app_version = "0.6.9"
    module._current_job = None
    write_state(module, restarting_state(target="v0.6.9", current="0.6.8"))

    job = module.get_job().get("job") or {}
    check(job.get("status") == module.ST_SUCCEEDED,
          "版本对得上时作业判为 succeeded",
          f"实际 status={job.get('status')!r}")
    check("已确认运行版本" in str(job.get("note") or ""),
          "成功时写明「已确认运行版本 v0.6.9」",
          f"note={job.get('note')!r}")
    check(not str(job.get("error") or ""),
          "成功时没有残留错误信息",
          f"error={job.get('error')!r}")


def test_version_prefix_tolerance(module, config_mod) -> None:
    """v 前缀不该影响判断：tag 写 v0.6.9、代码写 0.6.9，指的是同一版"""
    section("后端：版本号归一（v 前缀不算差异）")

    config_mod.settings.app_version = "v0.6.9"
    module._current_job = None
    write_state(module, restarting_state(target="0.6.9"))

    job = module.get_job().get("job") or {}
    check(job.get("status") == module.ST_SUCCEEDED,
          "运行 v0.6.9 / 目标 0.6.9 → 成功",
          f"实际 status={job.get('status')!r}")

    check(module._same_version("v0.6.9", "0.6.9"), "_same_version 忽略 v 前缀")
    check(module._same_version("0.6.9", "0.6.9"), "_same_version 相同版本判为相同")
    check(not module._same_version("0.6.9", "0.6.8"), "_same_version 不同版本判为不同")
    check(not module._same_version("", "0.6.9"),
          "拿不到版本号时判为「不同」（不知道 ≠ 一样）")
    check(not module._same_version("0.6.9", ""),
          "目标版本拿不到时判为「不同」")


def test_declared_version(module) -> None:
    """checkout 出来的代码里声明的版本，要能被读出来并与目标比对"""
    section("后端：checkout 之后的版本核对")

    cfg = (BACKEND / "app" / "config.py").read_text(encoding="utf-8")
    declared = module._declared_version(cfg)
    check(declared == "0.6.9",
          "能从 config.py 里读出 app_version",
          f"读出来的是 {declared!r}")
    check(module._same_version(declared, "v0.6.9"),
          "config.py 里的 0.6.9 与 tag v0.6.9 判为同一版")


def test_compose_image_refs(module) -> None:
    """新镜像必须打到编排文件真正引用的名字上"""
    section("后端：编排文件里的镜像引用")

    repo_compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    project = module._compose_project_name(repo_compose, "fallback")
    check(project == "kb-workbench",
          "能从编排文件里读出项目名 name:",
          f"读出来的是 {project!r}")

    refs = module._compose_service_images(repo_compose, project)
    check(refs.get("backend") == "kb-workbench-backend:latest",
          "backend 服务引用的镜像名解析正确",
          f"解析成 {refs.get('backend')!r}")
    check(refs.get("frontend") == "kb-workbench-frontend:latest",
          "frontend 服务引用的镜像名解析正确",
          f"解析成 {refs.get('frontend')!r}")

    # 离线包的编排文件（只有 image:，没有 build:）
    offline_compose = (REPO / "packaging" / "app" / "docker-compose.yml")
    if offline_compose.is_file():
        text = offline_compose.read_text(encoding="utf-8")
        p = module._compose_project_name(text, "fallback")
        refs2 = module._compose_service_images(text, p)
        check(refs2.get("backend") == "kb-workbench-backend:latest"
              and refs2.get("frontend") == "kb-workbench-frontend:latest",
              "离线包编排文件里的镜像名解析正确",
              f"解析成 {refs2!r}")

    # 老编排文件：有 build: 但没有 image: → compose 自己 build 出来的名字
    legacy = """
name: myproj
services:
  backend:
    build:
      context: ./backend
  frontend:
    build: ./frontend
"""
    legacy_refs = module._compose_service_images(legacy, "myproj")
    check(legacy_refs.get("backend") == "myproj-backend:latest",
          "没有 image: 时按 compose 的命名规则拼镜像名",
          f"拼成 {legacy_refs.get('backend')!r}")
    check(legacy_refs.get("frontend") == "myproj-frontend:latest",
          "没有 image: 时按 compose 的命名规则拼镜像名（前端）",
          f"拼成 {legacy_refs.get('frontend')!r}")

    # YAML 解析不了时的兜底：逐行扫
    broken = """
name: myproj
services:
  backend:
    image: kb-workbench-backend:latest
    build:
      context: ./backend
  frontend:
    image: kb-workbench-frontend:latest
"""
    scanned = module._compose_service_images(broken, "myproj")
    check(scanned.get("backend") == "kb-workbench-backend:latest"
          and scanned.get("frontend") == "kb-workbench-frontend:latest",
          "逐行扫描的兜底也能解析出镜像名",
          f"解析成 {scanned!r}")

    # 服务定义是空的（`backend:` 底下什么都没有）也不能漏掉这个服务
    empty = """
name: myproj
services:
  backend:
  frontend:
    image: kb-workbench-frontend:latest
"""
    empty_refs = module._compose_service_images(empty, "myproj")
    check(empty_refs.get("backend") == "myproj-backend:latest",
          "服务定义为空时也要给出镜像名（不能漏掉这个服务）",
          f"解析成 {empty_refs!r}")

    # 变量写法：${VAR:-默认值}
    varred = """
name: myproj
services:
  backend:
    image: ${KB_BACKEND_IMAGE:-kb-workbench-backend:latest}
"""
    var_refs = module._compose_service_images(varred, "myproj")
    check(var_refs.get("backend") == "kb-workbench-backend:latest",
          "image 里的 ${VAR:-默认值} 能解析出默认值",
          f"解析成 {var_refs!r}")


def test_checked_out_version_gate(module) -> None:
    """git 路径：checkout 出来的代码版本对不上 → 必须失败，不能继续"""
    section("后端：git 路径的 checkout 版本核对")

    import asyncio

    class _FakeJob:
        def __init__(self):
            self.lines: list[str] = []
            self.steps: dict[str, str] = {}

        def log(self, text: str) -> None:
            self.lines.append(text)

        def set_step(self, key: str, status: str) -> None:
            self.steps[key] = status

    def _make_tree(version: str) -> "Path":
        root = Path(tempfile.mkdtemp(prefix="kb-upgrade-tree-"))
        cfg = root / "backend" / "app" / "config.py"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            "from pydantic_settings import BaseSettings\n\n\n"
            "class Settings(BaseSettings):\n"
            f'    app_version: str = "{version}"\n',
            encoding="utf-8")
        return root

    # 情况一：tag 里的版本就是目标版本 → 放行
    job_ok = _FakeJob()
    asyncio.run(module._check_checked_out_version(
        job_ok, _make_tree("0.6.9"), "v0.6.9"))
    check(any("与目标一致" in ln for ln in job_ok.lines),
          "版本对得上时放行并记一笔",
          f"日志：{job_ok.lines!r}")

    # 情况二：tag 里的版本不是目标版本 → 必须报错停下
    job_bad = _FakeJob()
    raised = ""
    try:
        asyncio.run(module._check_checked_out_version(
            job_bad, _make_tree("0.6.8"), "v0.6.9"))
    except Exception as e:                      # noqa: BLE001 - 这里就是要抓它
        raised = str(e)
    check(bool(raised),
          "tag 里的版本不是目标版本时直接失败（不再 build/up）",
          f"没有抛异常，日志：{job_bad.lines!r}")
    check("0.6.8" in raised and "0.6.9" in raised,
          "失败原因里写清 tag 里声明的是哪一版",
          f"raised={raised!r}")
    check(job_bad.steps.get("checkout") == "failed",
          "checkout 步骤被标成失败（界面上能看出来卡在哪一步）",
          f"steps={job_bad.steps!r}")
    check(any("升级失败" not in ln and "❌" in ln for ln in job_bad.lines),
          "失败原因同时写进了作业日志",
          f"日志：{job_bad.lines!r}")


def test_restart_helper_no_build(module) -> None:
    """离线升级的重启必须带 --no-build"""
    section("后端：离线升级的重启参数")

    import inspect
    src = inspect.getsource(module._run_offline_job)
    check("--no-build" in src,
          "离线升级的重启带 --no-build（compose 不能拿旧源码重建）")
    check("_start_restart_helper" in src and "extra=" in src,
          "临时容器那条路也把 --no-build 传下去了")


# ==================== 入口 ====================

def main() -> int:
    if not UPGRADE_PY.is_file():
        print(f"找不到 {UPGRADE_PY}")
        return 2

    with tempfile.TemporaryDirectory(prefix="kb-upgrade-verify-") as tmp:
        module, config_mod = load_upgrade_module(tmp)
        test_restored_job_version_mismatch(module, config_mod)
        test_restored_job_version_match(module, config_mod)
        test_version_prefix_tolerance(module, config_mod)
        test_declared_version(module)
        test_compose_image_refs(module)
        test_checked_out_version_gate(module)
        test_restart_helper_no_build(module)

    print("\n" + "=" * 60)
    if _failures:
        print(f"❌ {len(_failures)}/{_checks} 项检查未通过：")
        for f in _failures:
            print(f"   - {f}")
        return 1
    print(f"✅ 全部 {_checks} 项检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
