#!/usr/bin/env python3
"""v23 自测：应用中心「自然语言生成数据模型」

离线跑，不碰线上库：
  docker run --rm -i -v "$PWD/backend/app:/app/app:ro" \
    --entrypoint python kb-workbench-backend - < scripts/v23-verify-ai-apps.py

验三件事：
1. mock 模式（未配 LLM）下，一句中文描述能生成**结构合法**的草稿；
2. 草稿能被创建函数接受（真建到临时 SQLite 库里，检查模型/字段/关联）；
3. 兜底与清洗：脏输入（非法类型、多余键、指向不存在模型的引用）不会把库建炸，
   且内置模板的原有调用方式仍然可用（向后兼容）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# 允许在仓库里直接 python3 scripts/v23-verify-ai-apps.py 跑（依赖装在容器里时用不到）
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if os.path.isdir(_BACKEND):
    sys.path.insert(0, _BACKEND)

from sqlalchemy import select                                    # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base                                   # noqa: E402
from app import models as _models                               # noqa: E402,F401
from app.models import App, EntityType, FieldDefinition, RelationDef  # noqa: E402
from app.routers import apps as apps_router                     # noqa: E402
from app.services import app as app_svc                         # noqa: E402
from app.services import app_ai, app_template                   # noqa: E402

ALLOWED_TYPES = set(app_ai.ALLOWED_FIELD_TYPES)
FAILURES: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> bool:
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        FAILURES.append(label)
    return bool(cond)


def assert_spec_valid(spec: dict, label: str) -> None:
    """草稿结构合法性：这是前端要展示、创建函数要吃的唯一契约"""
    check(isinstance(spec.get("types"), list) and spec["types"], f"{label}：至少有一个数据模型")
    check(bool(spec.get("key")), f"{label}：应用 key 非空")
    check(bool(spec.get("name")), f"{label}：应用名非空")
    check(spec.get("icon") in app_ai.APP_ICONS, f"{label}：应用图标合法")

    type_keys = {t["key"] for t in spec["types"]}
    check(len(type_keys) == len(spec["types"]), f"{label}：模型 key 不重复")
    for t in spec["types"]:
        check(bool(t.get("name")), f"{label}：模型「{t.get('key')}」有名称")
        check(isinstance(t.get("fields"), list) and t["fields"],
              f"{label}：模型「{t['key']}」有字段")
        fkeys = [f["key"] for f in t["fields"]]
        check(len(set(fkeys)) == len(fkeys), f"{label}：模型「{t['key']}」字段 key 不重复")
        for f in t["fields"]:
            check(f["type"] in ALLOWED_TYPES,
                  f"{label}：字段「{f.get('name')}」类型「{f.get('type')}」在白名单内")
            check(isinstance(f.get("required"), bool), f"{label}：字段必填标记是布尔")
            check(isinstance(f.get("options"), dict), f"{label}：字段 options 是对象")
            if f["type"] in ("select", "multiselect"):
                check(isinstance(f["options"].get("choices"), list),
                      f"{label}：选择字段「{f.get('name')}」有 choices")
            if f["type"] == "reference":
                check(f["options"].get("target_ref") in type_keys,
                      f"{label}：引用字段「{f.get('name')}」指向真实存在的模型")

    for r in spec.get("relations", []):
        check(r.get("source") in type_keys and r.get("target") in type_keys,
              f"{label}：关联「{r.get('name')}」两端模型都存在")
        check(r.get("source") != r.get("target"), f"{label}：关联「{r.get('name')}」不自指")


async def main() -> int:
    print("=" * 68)
    print("v23 自测：自然语言 → 应用规格草稿 → 建库")
    print("=" * 68)

    # ---------- 0. 环境 ----------
    cfg = app_ai.cfg_svc.get_full_config()
    llm_on = bool(cfg.get("enabled") and cfg.get("api_key") and cfg.get("base_url"))
    print(f"[环境] AI 配置：enabled={cfg.get('enabled')} model={cfg.get('model') or '-'}"
          f" → {'真实大模型' if llm_on else 'mock/规则模式'}")
    print("[环境] 测试强制走 mock 模式（结果必须确定）\n")

    # 强制 mock：无论容器里配没配大模型，规则兜底的结果都得成立
    original_enabled = app_ai._llm_enabled
    app_ai._llm_enabled = lambda: False

    try:
        # ---------- 1. mock 模式生成草稿 ----------
        prompts = [
            ("客户管理", ["customer", "opportunity", "order"]),
            ("我要做一个合同审批系统", ["contract"]),
            ("项目管理，要能管任务和里程碑", ["project", "task"]),
            ("文献阅读笔记管理", ["paper"]),
            ("员工报销费用管理", ["expense"]),
            ("随便记点东西的地方", None),          # 不命中任何业务名词 → 通用骨架
        ]
        specs = {}
        print("[1] mock 模式生成草稿")
        for prompt, expect_keys in prompts:
            spec = await app_ai.generate_app_spec(prompt)
            specs[prompt] = spec
            names = "、".join(t["name"] for t in spec["types"])
            print(f"  · 「{prompt}」→ 应用「{spec['name']}」/ {spec['key']}"
                  f" / {len(spec['types'])} 模型（{names}）"
                  f" / {len(spec['relations'])} 关联")
            print(f"    提示：{spec['notice']}")
            assert_spec_valid(spec, prompt)
            check(spec["source"] == "rules", f"「{prompt}」：来源标记为 rules")
            check(bool(spec["notice"]), f"「{prompt}」：带有人话提示")
            if expect_keys:
                got = {t["key"] for t in spec["types"]}
                check(any(k in got for k in expect_keys),
                      f"「{prompt}」：命中预期业务模型 {expect_keys}")
            else:
                check(len(spec["types"]) >= 1, "「随便记点东西」：兜底也给了可用模型")
        print()

        # ---------- 2. 草稿能被创建函数接受 ----------
        print("[2] 草稿建库（临时 SQLite，不碰线上数据）")
        tmp_dir = tempfile.mkdtemp(prefix="v23-")
        db_path = os.path.join(tmp_dir, "v23.db")
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with Session() as db:
            spec = specs["我要做一个合同审批系统"]
            r = await app_template.create_app_from_spec(
                db, {"key": "v23_demo", "name": "合同审批", "order": 1}, spec)
            check(r["ok"] is True, "创建返回 ok")
            check(len(r["types"]) == len(spec["types"]), "建出来的模型数与草稿一致")
            check(len(r["relations"]) == len(spec["relations"]), "建出来的关联数与草稿一致")

            app_row = (await db.execute(select(App).where(App.key == "v23_demo"))).scalar_one()
            check(app_row.name == "合同审批", "应用名按传入值落库")

            ets = (await db.execute(
                select(EntityType).where(EntityType.app == "v23_demo"))).scalars().all()
            check(len(ets) == len(spec["types"]), "模型行数正确")
            check(all(et.key.startswith("v23_demo_") for et in ets),
                  "模型 key 带应用前缀（全局唯一）")

            fds = (await db.execute(select(FieldDefinition))).scalars().all()
            demo_fds = [f for f in fds if f.entity_type_id in {e.id for e in ets}]
            check(len(demo_fds) > 0, "字段行数大于 0")
            check(all(f.type in ALLOWED_TYPES for f in demo_fds), "落库的字段类型都在白名单内")

            refs = [f for f in demo_fds if f.type == "reference"]
            check(all((f.options or {}).get("target") for f in refs),
                  "引用字段的目标已翻译成带前缀的绝对 key")
            et_keys = {et.key for et in ets}
            check(all((f.options or {}).get("target") in et_keys for f in refs),
                  "引用字段指向的模型真实存在")

            rds = (await db.execute(select(RelationDef))).scalars().all()
            demo_rds = [r for r in rds if r.key.startswith("v23_demo_")]
            check(len(demo_rds) == len(spec["relations"]), "关联定义行数正确")

        # ---------- 3. 脏输入清洗 ----------
        print("\n[3] 脏输入清洗（AI 输出不可信）")
        dirty = {
            "key": "脏数据",
            "name": "脏数据应用",
            "icon": "不存在的图标",
            "types": [{
                "key": "模型", "name": "模型", "icon": "???",
                "fields": [
                    {"key": "标题", "name": "标题", "type": "string", "required": "是",
                     "多余键": "该被丢掉"},
                    {"key": "amount", "name": "金额", "type": "金额"},
                    {"key": "ref", "name": "关联", "type": "reference",
                     "options": {"target_ref": "根本不存在"}},
                    {"key": "st", "name": "状态", "type": "select"},
                ],
            }],
            "relations": [{"source": "模型", "target": "缺失模型"}],
        }
        cleaned = app_ai.normalize_spec(dirty)
        f0 = cleaned["types"][0]["fields"]
        check(cleaned["key"] == "ai_app" or cleaned["key"].isascii(),
              "脏 key 被换成合法标识")
        check(cleaned["icon"] == "Grid", "非法应用图标回退为 Grid")
        check(f0[0]["type"] == "text", "别名字符串类型归一为 text")
        check(f0[0]["required"] is True, "字符串必填标记归一为布尔")
        check("多余键" not in f0[0], "多余键被剔除")
        check(f0[1]["type"] == "number", "中文类型别名「金额」归一为 number")
        check(f0[2]["type"] == "text", "指向不存在模型的引用降级为 text")
        check(f0[3]["options"].get("choices") == [], "无选项的 select 补空 choices")
        check(len(cleaned["relations"]) == 0, "两端缺模型的关联被丢弃")

        # ---------- 4. 模板路径向后兼容 ----------
        print("\n[4] 内置模板路径向后兼容")
        async with Session() as db:
            r = await app_template.create_app_from_template(
                db, {"template": "project", "key": "v23_tpl", "name": "项目管理"})
            check(r["template"] == "project", "按模板创建仍返回 template 字段")
            check(len(r["types"]) == 4, "project 模板建出 4 个模型")
            ets = (await db.execute(
                select(EntityType).where(EntityType.app == "v23_tpl"))).scalars().all()
            check(len(ets) == 4, "project 模板落库 4 个模型")
            icons = {et.icon for et in ets}
            check("List" in icons or "Briefcase" in icons,
                  f"模板自带图标没被清洗掉（实际 {sorted(icons)}）")
            fds = [f for f in (await db.execute(select(FieldDefinition))).scalars().all()
                   if f.entity_type_id in {e.id for e in ets}]
            check(len(fds) > 20, "project 模板字段数正常")

            r2 = await app_template.create_app_from_template(
                db, {"template": "blank", "key": "v23_blank", "name": "空白应用"})
            check(r2["types"] == [], "空白模板不建模型")

            try:
                await app_template.create_app_from_template(
                    db, {"template": "不存在的模板", "key": "v23_x"})
                check(False, "未知模板应报错")
            except ValueError as e:
                check("未知模板" in str(e), f"未知模板报错信息是中文：{e}")

            try:
                await app_template.create_app_from_spec(
                    db, {"key": "v23_dup"}, {"types": [], "relations": []})
                await app_template.create_app_from_spec(
                    db, {"key": "v23_dup"}, {"types": [], "relations": []})
                check(False, "重复 key 应报错")
            except ValueError as e:
                check("已存在" in str(e), f"重复 key 报错信息是中文：{e}")

        # ---------- 5. 路由层 ----------
        print("\n[5] 路由：/api/apps/from-prompt")
        out = await apps_router.create_from_prompt({"prompt": "客户管理"})
        check("types" in out and "relations" in out, "接口返回草稿结构")
        check(out["source"] in ("llm", "rules"), "接口返回生成来源")
        try:
            await apps_router.create_from_prompt({"prompt": "   "})
            check(False, "空 prompt 应报 400")
        except Exception as e:
            check("请先描述" in str(getattr(e, "detail", e)), "空 prompt 报 400 且提示是中文")

        # ---------- 6. 写接口门禁 ----------
        print("\n[6] 写接口门禁（model_manage / ai）")

        def deps_of(method: str, path: str):
            for r in apps_router.router.routes:
                if getattr(r, "path", "") == path and method in (getattr(r, "methods", None) or []):
                    return r.dependencies or []
            return None

        for method, path in (("POST", "/api/apps/from-template"),
                             ("POST", "/api/apps/from-spec"),
                             ("POST", "/api/apps"),
                             ("PUT", "/api/apps/{app_id}"),
                             ("DELETE", "/api/apps/{app_id}")):
            deps = deps_of(method, path)
            check(bool(deps), f"{method} {path} 挂了功能位门禁")
        check(bool(deps_of("POST", "/api/apps/from-prompt")),
              "POST /api/apps/from-prompt 挂了 ai 门禁")

        # ---------- 7. update_app 白名单 ----------
        print("\n[7] update_app 白名单")
        async with Session() as db:
            app_row = (await db.execute(select(App).where(App.key == "v23_demo"))).scalar_one()
            before_key = app_row.key
            updated = await app_svc.update_app(
                db, app_row.id, {"name": "改名了", "key": "偷偷改的key", "id": 999})
            check(updated.name == "改名了", "允许改的字段生效")
            check(updated.key == before_key, "key 不可被修改（结构标识符）")
            check(updated.id == app_row.id, "id 不可被修改")
            await app_svc.update_app(db, app_row.id, {"name": "合同审批"})

        await engine.dispose()
        print()
    finally:
        app_ai._llm_enabled = original_enabled

    print("=" * 68)
    if FAILURES:
        print(f"结果：失败 {len(FAILURES)}/{CHECKS} 项")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"结果：全部通过（{CHECKS} 项检查）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
