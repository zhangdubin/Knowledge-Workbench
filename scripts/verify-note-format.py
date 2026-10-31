#!/usr/bin/env python3
"""笔记排版规范（note_format）的断言

规范来源：《笔记 UI 排版规范》v1.7
这些规则容易改坏，改了就要改这里 —— 所以每条都钉一个断言。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services import note_format  # noqa: E402

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


def fmt(text, **kw):
    return note_format.format_note(text, **kw)


# ---------- §1 标题层级 ----------
out = fmt("## 背景\n\n正文内容在这里")
check("H2 补语义 emoji", "## 🎯 背景" in out, repr(out[:60]))

out = fmt("## 部署步骤\n\n正文")
check("H2 步骤类配 🔧", "## 🔧 部署步骤" in out, repr(out[:60]))

out = fmt("## 数据表格\n\n正文")
check("H2 数据类配 📊", "## 📊 数据表格" in out, repr(out[:60]))

out = fmt("## ⚠️ 注意事项\n\n正文")
check("已有 emoji 不重复加", out.count("⚠️") == 1, repr(out[:60]))

out = fmt("# 标题\n\n正文\n\n# 第二个标题")
check("全文只保留一个 H1", out.count("\n# ") + out.startswith("# ") == 1, repr(out[:80]))

# ---------- 裸标题提升 ----------
out = fmt("背景\n这个项目是给销售团队用的系统。\n\n部署\n用 Docker 启动。")
check("裸标题提升成 H2", "## 🎯 背景" in out and "## 📌 部署" in out, repr(out[:120]))

out = fmt("这是一段普通正文，不应该被当成标题。")
check("普通段落不被误判成标题", "## " not in out, repr(out[:80]))

# ---------- §3 callout ----------
out = fmt("> [!warning] 危险\n> 升级前必须备份")
check("callout 保持原样", "> [!warning] 危险" in out, repr(out[:80]))

out = fmt("> 这是一句普通引用")
check("普通引用转成 note callout", "> [!note]" in out, repr(out[:80]))

# ---------- §5 表格 ----------
out = fmt("| 名称 | 值 |\n|---|---|\n| 端口 | 10022 |")
check("表头加粗", "| **名称** | **值** |" in out, repr(out[:120]))

out = fmt("| 名称 | 状态 |\n|---|---|\n| 部署 | 已完成 |")
check("状态值加 emoji 且列数不变", "✅ 已完成" in out and "| **名称** | **状态** |" in out, repr(out[:140]))
check("表格列数没被 emoji 弄乱",
      out.count("\n") >= 3 and all(l.count("|") == 3 for l in out.strip().split("\n") if l.startswith("|")),
      repr(out[:160]))

# ---------- §6 代码块 ----------
out = fmt("```\ndocker pull gogs/gogs\n```")
check("代码块补语言", "```bash" in out, repr(out[:80]))

out = fmt("```python\nprint(1)\n```")
check("已有语言不覆盖", "```python" in out, repr(out[:80]))

out = fmt("```\nSELECT * FROM t\n```")
check("sql 代码块识别", "```sql" in out, repr(out[:80]))

# ---------- §8.1 分割线 ----------
out = fmt("上段\n\n---\n\n下段")
check("分割线前后留空行", "\n\n---\n\n" in out, repr(out[:80]))

# ---------- §8.3 任务列表 ----------
out = fmt("- [x] 完成项\n- [ ] 待办项")
check("任务列表保留勾选状态", "- [x]" in out and "- [ ]" in out, repr(out[:80]))
check("任务项的状态词加 emoji", "✅" in out, repr(out[:80]))

out = fmt("- [~] 进行中项")
check("任务列表 ~ 映射成 -", "- [-]" in out, repr(out[:80]))
check("进行中配 🚧", "🚧" in out, repr(out[:80]))

# ---------- 模板 ----------
tpl = note_format.note_template("测试笔记", tags=["a", "b"], summary="一句话摘要")
check("模板含 front-matter", tpl.startswith("---\ntitle: 测试笔记"), repr(tpl[:60]))
check("模板含 tags", "tags: [a, b]" in tpl, repr(tpl[:200]))
check("模板含 created/updated", "created:" in tpl and "updated:" in tpl, repr(tpl[:240]))
check("模板含版本号与状态", "version: 1.0" in tpl and "status: draft" in tpl, repr(tpl[:260]))
check("模板含 H1", "# 测试笔记" in tpl, repr(tpl[:260]))
check("模板含 abstract 摘要", "> [!abstract] 摘要" in tpl, repr(tpl[:300]))
check("模板 summary 为空时不加摘要块",
      "> [!abstract]" not in note_format.note_template("空摘要"), "")

# ---------- 幂等 ----------
once = fmt(open(os.path.join(os.path.dirname(__file__), "..", "scripts", "..", "CHANGELOG.md"),
                encoding="utf-8").read()[:3000])
twice = fmt(once)
check("排版基本幂等（再排一次不会更乱）",
      once.count("## ") == twice.count("## "), f"{once.count('## ')} vs {twice.count('## ')}")

# ---------- 代码块语言识别（§6.1）----------
# 「AI 对内容识别不到位、排版时没有识别到代码」——
# 原来只扫前 5 行，语言特征在后面的代码块就认不出来了。
_code_cases = [
    (['docker compose up -d'], 'bash'),
    (['curl -s http://x/api/health', 'ls -la'], 'bash'),
    (['import os', 'def main():'], 'python'),
    (['SELECT id FROM t WHERE x=1'], 'sql'),
    (['{', '  "a": 1'], 'json'),
    (['name: test', 'items:'], 'yaml'),
    (['const a = 1'], 'javascript'),
    (['<!DOCTYPE html', '<div>hi</div>'], 'html'),
]
for _body, _want in _code_cases:
    _got = note_format._guess_lang(_body)
    check(f"代码块语言识别：{_want}", _got == _want, f"得到 {_got!r}")

# 关键回归：语言特征在很后面（前面 20 行都是注释）
_long_body = ['// 前面的注释'] * 20 + ['def handler():', '    pass']
_got = note_format._guess_lang(_long_body)
check('代码块语言识别：特征在第 21 行也认得出来', _got == 'python', f"得到 {_got!r}")

# 完整排版：代码块要有语言标识
_out = fmt('```\n' + 'x = 1\n' + '```')
check('排版后代码块带语言标识', '```python' in _out, repr(_out[:80]))

print()
print(f"{PASSED} 项通过，{FAILED} 项失败")
sys.exit(1 if FAILED else 0)
