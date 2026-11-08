#!/usr/bin/env python3
"""协同手册自检：手册说的和代码做的必须是同一件事

制度写在文档里容易烂 —— 文档说「16 项要素」，代码改成了 17 项；
文档说「四类骨架」，代码加了第五类；文档引用了一个早就改名的脚本。
这个脚本把手册里的**可验证断言**钉在代码上：

  1. 手册存在，且章节结构完整（§0–§15）
  2. 硬约束条数够（≥14 条）
  3. 手册里点名的验收脚本真实存在
  4. 要素体检项数 = 手册写的 16
  5. 笔记类型骨架 key 与手册一致（4 类）
  6. 手册里的版本号 = `app_version`
  7. `CHANGELOG.md` 里有对应版本的一节

用法：
    python3 scripts/verify-collab-handbook.py
退出码 0 = 全过；非 0 = 手册与实现脱节（先改文档或先改代码，别让它们各说各的）。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

MANUAL = os.path.join(ROOT, "docs", "知识库协同记录手册.md")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")

FAILED = 0
PASSED = 0


def check(name, cond, detail=""):
    global FAILED, PASSED
    if cond:
        PASSED += 1
        print(f"✅ {name}")
    else:
        FAILED += 1
        print(f"❌ {name}  {detail}")


def main() -> int:
    if not os.path.exists(MANUAL):
        print(f"❌ 手册不存在：{MANUAL}")
        return 1
    text = open(MANUAL, encoding="utf-8").read()

    # ---------- 1. 章节结构 ----------
    heads = re.findall(r"^## (\d+)\. ", text, re.M)
    check("手册含 §0–§15 全部章节",
          set(heads) >= {str(i) for i in range(16)},
          f"缺：{sorted({str(i) for i in range(16)} - set(heads), key=int)}")

    # ---------- 2. 硬约束条数 ----------
    hard = text.split("## 10. 硬约束", 1)
    hard_body = hard[1].split("**违规判定**", 1)[0] if len(hard) > 1 else ""
    n_rules = len(re.findall(r"^\d+\. \*\*", hard_body, re.M))
    check("硬约束 ≥ 14 条", n_rules >= 14, f"实际 {n_rules} 条")

    # ---------- 3. 点名的脚本都存在 ----------
    scripts = set(re.findall(r"scripts/[A-Za-z0-9._\-/]+\.(?:py|cjs|sh)", text))
    missing = [s for s in scripts if not os.path.exists(os.path.join(ROOT, s))]
    check("手册引用的脚本全部存在", not missing, f"缺：{missing}")
    check("手册点名了至少 4 个验收脚本", len(scripts) >= 4, f"实际 {len(scripts)} 个")

    # ---------- 4/5. 要素项数 / 骨架类型 ----------
    from app.services import note_format as nf  # noqa: E402
    from app.services import note_profile as prof  # noqa: E402

    n_elements = len(nf.element_audit("# x"))
    check("要素体检项数 = 16", n_elements == 16, f"实际 {n_elements}")
    check("手册写的是 16 项要素", "16 项" in text or "| 16 |" in text, "")

    keys = {p["key"] for p in prof.list_profiles()}
    expected = {"pentest-record", "troubleshoot", "tutorial", "concept"}
    check("骨架类型 = 手册写的 4 类", keys == expected, f"实际 {sorted(keys)}")
    for k in expected:
        check(f"手册提到骨架 `{k}`", k in text, "")

    # ---------- 6. 版本号一致 ----------
    from app.config import settings  # noqa: E402

    ver = settings.app_version
    check(f"手册里的版本号 = app_version（{ver}）", ver in text, f"手册里找不到 {ver}")

    # ---------- 7. CHANGELOG 有对应版本 ----------
    cl = open(CHANGELOG, encoding="utf-8").read() if os.path.exists(CHANGELOG) else ""
    check(f"CHANGELOG 有 {ver} 一节", f"## {ver} —" in cl, "")

    print()
    print(f"{PASSED} 项通过，{FAILED} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
