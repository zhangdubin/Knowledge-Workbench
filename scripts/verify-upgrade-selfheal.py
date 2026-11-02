#!/usr/bin/env python3
"""一键升级的「权威核验 + 自愈」自检

要验的是三件事（这次修掉的毛病全围绕它们）：

  1. **服务端权威核验**：升级跑完到底是不是目标版本，由后端自己回答 ——
     它读得到自己容器的镜像 ID、读得到镜像里声明的版本，
     于是能说清「**是哪一层**没换成功」（源码 / 镜像 / 容器 / 缓存）。
  2. **自愈**：核验不通过时能自动「强制换镜像 + 重建容器」，
     重建之后重新核验必须通过。
  3. **缓存**：/api/health、版本核验接口、nginx 的 /api/ 都要明确不缓存 ——
     任何一层缓存都会让「版本没变」的错觉一直存在。

怎么做到不依赖整套后端：
upgrade.py 会 import app.config（pydantic_settings）、app.services.audit
（starlette + sqlalchemy）…… 宿主机上未必装得齐，而我们要验的只是
「版本核验」与「分层判定」这两段逻辑。
所以这里把重依赖换成最小的假实现，**原样加载工作区里的 upgrade.py**，
再用**假的 docker** 把各种现场摆出来走一遍。

「假的 docker」是真的在跑：它是一个放在临时目录里的可执行脚本，
处理 image inspect / run --rm grep / inspect / tag 四类命令，
状态存在一个 JSON 文件里 —— 于是「打完标签再核验」这种
需要前后状态的场景也能真跑一遍。

用法：
    python3 scripts/verify-upgrade-selfheal.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import stat
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
        self.app_version = "1.0.0"
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


# ==================== 假的 docker ====================

FAKE_DOCKER = '''#!/usr/bin/env python3
"""假的 docker —— 只实现核验流程真正用到的那几条命令

状态放在 FAKE_DOCKER_STATE 指向的 JSON 文件里：
  images   —— 标签 → {id, version}
  container—— 当前容器的 inspect 结果
"""
import json
import os
import sys

STATE = os.environ.get("FAKE_DOCKER_STATE", "")
args = sys.argv[1:]


def load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"images": {}, "container": {}}


def save(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)


def main():
    st = load()
    imgs = st.get("images", {})
    # 记下最后一次调用的参数：用来验「参数顺序对不对」
    st["last_args"] = list(args)
    save(st)
    if not args:
        return 1
    if args[0] == "image" and args[1] == "inspect":
        ref = args[-1]
        item = imgs.get(ref)
        if not item:
            print(f"Error: No such image: {ref}", file=sys.stderr)
            return 1
        print(item.get("id", ""))
        return 0
    if args[0] == "run":
        # docker run --rm --entrypoint <cmd> <镜像> [命令参数...]
        # 镜像名紧跟在 --entrypoint 的值后面（参数顺序很重要，见用例）
        ref = ""
        if "--entrypoint" in args:
            idx = args.index("--entrypoint")
            if idx + 2 < len(args):
                ref = args[idx + 2]
        if not ref:
            print("Error: no image given", file=sys.stderr)
            return 1
        item = imgs.get(ref)
        if not item:
            print(f"Error: No such image: {ref}", file=sys.stderr)
            return 1
        print(f'    app_version: str = "{item.get("version", "")}"')
        return 0
    if args[0] == "inspect":
        print(json.dumps(st.get("container", {}), ensure_ascii=False))
        return 0
    if args[0] == "tag":
        src, dst = args[-2], args[-1]
        if src not in imgs:
            print(f"Error: No such image: {src}", file=sys.stderr)
            return 1
        imgs[dst] = dict(imgs[src])
        save(st)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class FakeDocker:
    """在临时目录里装一个假的 docker，并管理它的状态"""

    def __init__(self, root: Path):
        self.dir = root / "bin"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.bin = self.dir / "docker"
        self.bin.write_text(FAKE_DOCKER, encoding="utf-8")
        self.bin.chmod(self.bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.state_path = root / "docker-state.json"
        self.state: dict = {"images": {}, "container": {}}
        self.save()

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False),
                                   encoding="utf-8")

    def image(self, ref: str, image_id: str, version: str) -> None:
        self.state["images"][ref] = {"id": image_id, "version": version}
        self.save()

    def container(self, image_id: str, image_ref: str, container_id: str) -> None:
        self.state["container"] = {
            "Id": container_id,
            "Image": image_id,
            "Config": {"Image": image_ref},
            "Mounts": [],
        }
        self.save()

    def activate(self, path_prefix: str) -> None:
        """把假 docker 放到 PATH 最前面"""
        os.environ["PATH"] = path_prefix + os.pathsep + os.environ.get("PATH", "")
        os.environ["FAKE_DOCKER_STATE"] = str(self.state_path)


def write_project(root: Path, version: str, compose: str | None = None) -> None:
    """造一个「部署目录」：有编排文件、有 backend/app/config.py"""
    (root / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (root / "backend" / "app" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        f'    app_version: str = "{version}"\n',
        encoding="utf-8")
    text = compose if compose is not None else (
        "name: kb-workbench\n"
        "services:\n"
        "  backend:\n"
        "    image: kb-workbench-backend:latest\n"
        "    build:\n"
        "      context: ./backend\n"
        "  frontend:\n"
        "    image: kb-workbench-frontend:latest\n"
    )
    (root / "docker-compose.yml").write_text(text, encoding="utf-8")


# ==================== 用例 ====================

def test_version_normalization(module) -> None:
    """版本号归一：v 前缀、数字段数都不该影响判断"""
    section("版本号归一")

    check(module._norm_version("v1.0.0") == "1.0.0", "去掉 v 前缀")
    check(module._norm_version(" 1.0.0 ") == "1.0.0", "去掉空白")
    check(module._norm_version("") == "", "空串就是空串")
    check(module._same_version("v1.0.0", "1.0.0"), "带 v 与不带 v 是同一版")
    check(not module._same_version("", "1.0.0"), "拿不到版本号判为「不同」")
    check(module._versioned_ref("kb-workbench-backend:latest", "v1.0.0")
          == "kb-workbench-backend:1.0.0",
          "版本化标签：kb-workbench-backend:latest → kb-workbench-backend:1.0.0")


def test_load_output_parsing(module) -> None:
    """docker load 的两种输出措辞都要认出来"""
    section("docker load 输出解析")

    old = "Loaded image: kb-workbench-backend:arm64\n"
    check(module._parse_loaded_images(old) == ["kb-workbench-backend:arm64"],
          "老措辞（Loaded image:）能认出来")

    new = "Loaded image ID: sha256:1234567890abcdef\n"
    check(module._parse_loaded_images(new) == ["sha256:1234567890abcdef"],
          "新措辞（Loaded image ID:）能认出来",
          f"实际：{module._parse_loaded_images(new)!r}")

    both = old + new
    check(len(module._parse_loaded_images(both)) == 2, "两种措辞混在一起也都能认出来")
    check(module._parse_loaded_images("") == [], "空输出不炸")


def test_verdict_layers(module) -> None:
    """分层判定：每种现场都要落到正确的层上"""
    section("分层判定（差在哪一层）")

    layer, _reason = module._verdict("1.0.0", "v1.0.0")
    check(layer == module.LAYER_OK, "版本一致 → ok", f"layer={layer}")

    layer, reason = module._verdict("0.13.0", "v1.0.0",
                                    image_declared="1.0.0")
    check(layer == module.LAYER_CONTAINER,
          "镜像里是目标版本、跑的是旧版本 → 容器没重建",
          f"layer={layer}")
    check("容器" in reason, "原因里说清是容器的问题", f"reason={reason!r}")

    layer, _reason = module._verdict("0.13.0", "v1.0.0",
                                     image_id_running="sha256:aaa",
                                     image_id_tag="sha256:bbb")
    check(layer == module.LAYER_CONTAINER,
          "标签指向的镜像与容器在跑的不是同一个 → 容器没重建",
          f"layer={layer}")

    layer, reason = module._verdict("0.13.0", "v1.0.0",
                                    image_declared="0.13.0",
                                    source_declared="0.13.0")
    check(layer == module.LAYER_SOURCE,
          "部署目录里的源码就不是目标版本 → 源码没换",
          f"layer={layer}")
    check("源码" in reason, "原因里说清是源码的问题", f"reason={reason!r}")

    layer, _reason = module._verdict("0.13.0", "v1.0.0",
                                     image_declared="0.13.0")
    check(layer == module.LAYER_IMAGE,
          "镜像里就是旧版本 → 镜像没换",
          f"layer={layer}")


def test_fix_commands(module) -> None:
    """每一层都要给出能直接执行的命令"""
    section("分层对应的处置命令")

    cmds = module._fix_commands(module.LAYER_CONTAINER, "/app/project", "v1.0.0", "kb-workbench-backend:latest")
    check(any("--force-recreate" in c for c in cmds),
          "容器没重建这一层给出 --force-recreate",
          f"cmds={cmds!r}")
    check(any("docker compose" in c for c in cmds),
          "命令是 docker compose 开头的（能直接粘）",
          f"cmds={cmds!r}")

    cmds = module._fix_commands(module.LAYER_IMAGE, "/app/project", "v1.0.0", "kb-workbench-backend:latest")
    check(any("build" in c for c in cmds),
          "镜像没换这一层要重新 build",
          f"cmds={cmds!r}")

    cmds = module._fix_commands(module.LAYER_SOURCE, "/app/project", "v1.0.0", "kb-workbench-backend:latest")
    check(any("git checkout" in c for c in cmds),
          "源码没换这一层要 git checkout",
          f"cmds={cmds!r}")

    cmds = module._fix_commands(module.LAYER_CACHE, "", "v1.0.0", "")
    check(any("Cache-Control" in c for c in cmds),
          "缓存这一层给出破缓存的命令",
          f"cmds={cmds!r}")


def test_container_names(module) -> None:
    """编排文件里写死的 container_name 要认得出来"""
    section("编排文件里的容器名")

    repo_compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    names = module._scan_compose_container_names(repo_compose)
    check(names.get("backend") == "kb-backend",
          "backend 服务的 container_name 解析正确",
          f"got={names.get('backend')!r}")
    check(names.get("frontend") == "kb-frontend",
          "frontend 服务的 container_name 解析正确",
          f"got={names.get('frontend')!r}")

    no_name = module._scan_compose_container_names(
        "services:\n  api:\n    image: x:latest\n")
    check(no_name.get("api") == "",
          "没写 container_name 时不瞎编",
          f"got={no_name.get('api')!r}")


def test_backend_ref(module) -> None:
    """编排文件里后端服务引用的镜像要认得出来"""
    section("编排文件里的后端镜像")

    refs = {"backend": "kb-workbench-backend:latest",
            "frontend": "kb-workbench-frontend:latest"}
    check(module._backend_ref(refs) == "kb-workbench-backend:latest",
          "认得出 backend 服务")

    refs = {"api": "my-api:latest", "worker": "my-worker:latest"}
    check(module._backend_ref(refs) == "my-api:latest",
          "服务名不叫 backend 时退回第一个（不认错就够）",
          f"got={module._backend_ref(refs)!r}")

    check(module._backend_ref({}) == "kb-workbench-backend:latest",
          "认不出来时退回约定名")


async def _verify_with_fake_docker(module, config_mod, fake: FakeDocker,
                                   root: Path, running_version: str,
                                   tag_version: str, container_image: str,
                                   source_version: str) -> dict:
    """摆一个现场，然后真跑一次核验"""
    config_mod.settings.app_version = running_version
    fake.image("kb-workbench-backend:latest", container_image, tag_version)
    fake.image("kb-workbench-backend:1.0.0", "sha256:newimage", "1.0.0")
    fake.container(container_image, "kb-workbench-backend:latest", "cid-back")
    write_project(root, source_version)
    module._verify_cache.clear()
    return await module.verify_running_version("v1.0.0", refresh=True)


def test_end_to_end_verify(module, config_mod, tmp: Path) -> None:
    """端到端：摆现场 → 真跑核验 → 自愈 → 再核验通过"""
    section("端到端核验 + 自愈（用假的 docker 真跑一遍）")

    fake = FakeDocker(tmp)
    fake.activate(str(fake.dir))
    os.environ["HOSTNAME"] = "cid-back"
    root = tmp / "project"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["KB_PROJECT_DIR"] = str(root)

    # ---- 现场一：镜像是对的，容器还在跑旧的 → 判「容器没重建」----
    res = asyncio.run(_verify_with_fake_docker(
        module, config_mod, fake, root,
        running_version="0.13.0", tag_version="1.0.0",
        container_image="sha256:oldimage", source_version="1.0.0"))
    check(res.get("ok") is False, "版本对不上时核验不通过")
    check(res.get("layer") == module.LAYER_CONTAINER,
          "判出「容器没重建」这一层",
          f"layer={res.get('layer')!r}")
    check(res.get("image_ref") == "kb-workbench-backend:latest",
          "结论里带上编排文件引用的镜像名",
          f"image_ref={res.get('image_ref')!r}")
    check(res.get("image_declared_version") == "1.0.0",
          "结论里带上镜像里声明的版本",
          f"got={res.get('image_declared_version')!r}")
    check(bool(res.get("commands")), "结论里带上该执行的命令")
    check(res.get("reason"), "结论里有能给人看的解释")

    # ---- 现场二：标签与镜像都还是旧的 → 判「镜像没换」----
    res = asyncio.run(_verify_with_fake_docker(
        module, config_mod, fake, root,
        running_version="0.13.0", tag_version="0.13.0",
        container_image="sha256:oldimage", source_version="0.13.0"))
    check(res.get("layer") == module.LAYER_SOURCE,
          "源码也不是目标版本时判「源码没换」（最具体的层优先）",
          f"layer={res.get('layer')!r}")

    # ---- 现场三：自愈之后重新核验，必须通过 ----
    #   自愈做的事：把目标版本的镜像打到编排引用的标签上 + 重建容器。
    fake.image("kb-workbench-backend:latest", "sha256:newimage", "1.0.0")
    fake.container("sha256:newimage", "kb-workbench-backend:latest", "cid-back")
    config_mod.settings.app_version = "1.0.0"
    module._verify_cache.clear()
    res = asyncio.run(module.verify_running_version("v1.0.0", refresh=True))
    check(res.get("ok") is True,
          "强制换镜像并重建容器之后，核验通过",
          f"res={res!r}")
    check(res.get("layer") == module.LAYER_OK, "层判定为 ok",
          f"layer={res.get('layer')!r}")

    # ---- 镜像声明版本：读得出来，且参数顺序正确 ----
    #
    # 曾经的写法是「docker run --rm --entrypoint grep -h "app_version: str" <镜像> <路径>」，
    # docker 会把 -h 当成自己的选项（打印帮助后退出 1）——
    # 于是永远「读不到」，而读不到又被当成「查不了 ≠ 版本不对」，
    # 所有镜像版本核对都被静默跳过：装着旧版本的镜像照样被拉起来。
    got = asyncio.run(module._image_declared_version("docker", "kb-workbench-backend:latest"))
    check(got == "1.0.0", "读得出镜像里声明的版本",
          f"got={got!r}")
    state = json.loads(fake.state_path.read_text(encoding="utf-8"))
    args = state.get("last_args") or []
    check("-h" in args and "kb-workbench-backend:latest" in args,
          "调用的是 docker run ... grep <镜像> -h ...",
          f"args={args!r}")
    if "-h" in args and "kb-workbench-backend:latest" in args:
        check(args.index("kb-workbench-backend:latest") < args.index("-h"),
              "镜像名必须排在 grep 的参数之前"
              "（否则 docker 把 -h 当成自己的选项，永远读不到版本）",
              f"args={args!r}")

    # ---- 现场四：跑的是目标版本，但页面拿到的是旧响应 → 缓存这一层 ----
    #   这一层由前端判定（它比得见自己拿到的是什么），后端只负责把
    #   「跑的是哪一版」如实报出来。
    res = asyncio.run(module.verify_running_version("v1.0.0", refresh=True))
    check(res.get("running") == "1.0.0",
          "后端如实报出自己此刻在跑的版本",
          f"running={res.get('running')!r}")


def test_cache_headers() -> None:
    """缓存头：后端接口与 nginx 都要明确不缓存"""
    section("缓存头")

    main_py = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    check("no-store" in main_py, "/api/health 响应带 no-store")

    nginx = (REPO / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    api_loc = nginx.split("location /api/")[1] if "location /api/" in nginx else ""
    check("no-store" in api_loc, "nginx 的 /api/ 位置带 no-store")
    check("X-Content-Type-Options" in api_loc,
          "nginx 的 /api/ 位置把安全头也补上了"
          "（add_header 在 location 里出现就不再继承 server 段）")

    sys_py = (BACKEND / "app" / "routers" / "system.py").read_text(encoding="utf-8")
    check("/update/verify" in sys_py, "后端有版本核验接口")


def test_frontend_contract() -> None:
    """前端：不再自己比两个字符串，改用后端的核验结论"""
    section("前端契约")

    update_js = (REPO / "frontend" / "src" / "utils" / "update.js").read_text(encoding="utf-8")
    check("verifyFailureText" in update_js, "有把核验结论渲染成一句话的函数")
    check("detectCacheLayer" in update_js, "有判断「拿到的是不是旧响应」的函数")
    check("VERIFY_LAYER" in update_js, "核验的层有统一枚举")

    settings = (REPO / "frontend" / "src" / "views" / "system" / "Settings.vue").read_text(
        encoding="utf-8")
    check("updateVerify" in settings, "界面调的是后端核验接口")
    check("upgrade.verify" in settings, "界面渲染的是后端给的结论")
    check("请检查 docker compose logs backend 与镜像标签是否换成功。" not in settings,
          "旧的那句「请检查 docker compose logs backend…」不再硬写在界面里")


# ==================== 入口 ====================

def main() -> int:
    if not UPGRADE_PY.is_file():
        print(f"找不到 {UPGRADE_PY}")
        return 2

    with tempfile.TemporaryDirectory(prefix="kb-upgrade-selfheal-") as tmp:
        tmpdir = Path(tmp)
        module, config_mod = load_upgrade_module(str(tmpdir))
        test_version_normalization(module)
        test_load_output_parsing(module)
        test_verdict_layers(module)
        test_fix_commands(module)
        test_backend_ref(module)
        test_container_names(module)
        test_end_to_end_verify(module, config_mod, tmpdir)
        test_cache_headers()
        test_frontend_contract()

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
