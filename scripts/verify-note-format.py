#!/usr/bin/env python3
"""笔记排版规范（note_format）的断言

规范来源：《笔记 UI 排版规范》v1.7
这些规则容易改坏，改了就要改这里 —— 所以每条都钉一个断言。
"""
import os
import re
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


def first_table(out):
    """取第一张表（变更日志也是表，断言只该看正文第一张）"""
    rows, started = [], False
    for ln in out.split("\n"):
        if ln.strip().startswith("|"):
            rows.append(ln)
            started = True
        elif started:
            break
    return rows


def has_h2(out, keyword):
    """H2 现在带章节编号（## 🎯 1. 背景），断言只认 emoji + 关键词"""
    return re.search(r"^## \S+ \d+\. " + re.escape(keyword) + r"$", out, re.M) is not None


# ---------- §1 标题层级 ----------
out = fmt("## 背景\n\n正文内容在这里")
check("H2 补语义 emoji", has_h2(out, "背景") and "🎯" in out, repr(out[:60]))

out = fmt("## 部署步骤\n\n正文")
check("H2 步骤类配 🔧", has_h2(out, "部署步骤") and "🔧" in out, repr(out[:60]))

out = fmt("## 数据表格\n\n正文")
check("H2 数据类配 📊", has_h2(out, "数据表格") and "📊" in out, repr(out[:60]))

out = fmt("## ⚠️ 注意事项\n\n正文")
check("已有 emoji 不重复加", out.count("⚠️") == 1, repr(out[:60]))

out = fmt("# 标题\n\n正文\n\n# 第二个标题")
check("全文只保留一个 H1", out.count("\n# ") + out.startswith("# ") == 1, repr(out[:80]))

# ---------- 裸标题提升 ----------
out = fmt("背景\n这个项目是给销售团队用的系统。\n\n部署\n用 Docker 启动。")
check("裸标题提升成 H2", has_h2(out, "背景") and has_h2(out, "部署"), repr(out[:200]))

out = fmt("这是一段普通正文，不应该被当成标题。")
_body = out.split("## 📝 变更日志")[0]
check("普通段落不被误判成标题", "## " not in _body, repr(out[:120]))

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
      len(first_table(out)) == 3 and all(l.count("|") == 3 for l in first_table(out)),
      repr(first_table(out)))

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
check("模板含 H1（允许带语义 emoji）",
      re.search(r"^# (?:\S+ )?测试笔记$", tpl, re.M) is not None, repr(tpl[:260]))
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


# ===========================================================================
# v2（规范 v1.8）新增能力 —— 每条都对应规范里的一条
# 这些规则是「新建笔记自动排版」的底座，改坏了要立刻知道
# ===========================================================================

# ---------- §2 front-matter ----------
out = fmt("正文一句。", title="测试标题")
check("给了标题就补 front-matter", out.startswith("---\ntitle: 测试标题"), repr(out[:60]))
check("front-matter 有 created/updated", "created: " in out and "updated: " in out, repr(out[:160]))
check("front-matter 有 scope/status/version",
      all(k in out for k in ("scope: ", "status: ", "version: ")), repr(out[:200]))
check("没给标题、也没原文 front-matter 时不硬加",
      not fmt("正文一句。").lstrip().startswith("---"), repr(fmt("正文一句。")[:40]))

_fm_src = """---
title: 老笔记
tags: [a]
created: 2026-01-02
custom_field: keep-me
---
正文。
"""
_out = fmt(_fm_src)
check("已有 front-matter 的自定义字段不丢", "custom_field: keep-me" in _out, repr(_out[:120]))
check("已有 created 不被覆盖", "created: 2026-01-02" in _out, repr(_out[:120]))

# related：字符串 / 无引号列表 → 统一成「列表 + 引号」
_out = fmt("---\ntitle: X\nrelated: [[A]] [[B]]\n---\n正文。")
check("related 规范成列表", "related:\n  - \"[[A]]\"\n  - \"[[B]]\"" in _out, repr(_out[:200]))
try:
    import yaml as _yaml
    _fm = _out.split("---")[1]
    _data = _yaml.safe_load(_fm)
    check("related 是合法 YAML 且值为 wikilink 字符串",
          _data.get("related") == ["[[A]]", "[[B]]"], repr(_data.get("related")))
except ImportError:  # pragma: no cover
    pass

# §2.2 Templater 表达式 → 实际日期
_out = fmt("---\ntitle: X\ndate: = date(today)\n---\n正文。")
check("Templater 表达式落成实际日期", "date: = date(today)" not in _out and "date: 20" in _out, repr(_out[:160]))

# ---------- §1 H1/H2 emoji ----------
check("H1 按标题语义配 emoji（登录成功 → ✅）", fmt("正文。", title="已成功登录 18001").count("# ✅") == 1,
      repr(fmt("正文。", title="已成功登录 18001")[:80]))
_out = fmt("---\ntitle: 云海渗透记录\nscope: pentest-record\n---\n正文。")
check("H1 按 scope 配 emoji（pentest → ⚔️）", "# ⚔️" in _out, repr(_out[:120]))

# ---------- §3.2 摘要 ----------
_one = fmt("已成功登录 18001 的 session", title="已成功登录 18001 的 session")
check("一句话笔记不生成摘要（重复标题是废话）", "[!abstract]" not in _one, repr(_one[:200]))
check("一句话笔记正文不重复标题", _one.count("已成功登录 18001 的 session") == 2, repr(_one))
_big = "第一段说清楚这件事。\n\n" + "\n\n".join(f"## 第{i}节\n内容{i}" for i in range(4))
_big_out = fmt(_big)
check("多节笔记生成摘要", "[!abstract] 摘要" in _big_out, repr(_big_out[:200]))
check("摘要带「覆盖：」小节清单", "覆盖：" in _big_out, repr(_big_out[:260]))

# ---------- §3.2 元信息卡 ----------
_meta_out = fmt("---\ntitle: 元信息卡测试\ntags: [x]\nscope: pentest-record\n---\n正文。")
check("元信息卡从 front-matter 派生",
      "[!info] 元信息" in _meta_out and "类型" in _meta_out, repr(_meta_out[:260]))
check("元信息卡紧凑（字段合并成两三行）",
      "**日期**: 📅 创建" in _meta_out
      and _meta_out.count("\n> - ") <= 6, repr(_meta_out[:300]))
check("元信息卡里的标签带 #", "**标签**: #x" in _meta_out, repr(_meta_out[:300]))

# ---------- §4 目录 ----------
_long = "\n\n".join(f"## 第{i}节\n正文{i}" for i in range(6))
_long_out = fmt(_long)
check("6 个 H2 自动生成目录", "## 📑 目录" in _long_out, repr(_long_out[:200]))
check("目录项带锚点", "](#" in _long_out, repr(_long_out[:400]))
check("目录链接文字带 §编号、去掉了 emoji",
      re.search(r"\[§1 第0节\]\(#1-第0节\)", _long_out) is not None, repr(_long_out[:400]))
check("短笔记不生成目录", "## 📑 目录" not in fmt("## 只有一节\n\n正文"), "")

# ---------- §5 表格 ----------
_out = fmt("| 项 | 值 |\n|---|---|\n| a | b |")
check("表头只加一次粗（不叠加）", _out.count("**项**") == 1, repr(_out[:120]))
check("表格行数不变", len(first_table(_out)) == 3, repr(first_table(_out)))

# ---------- §6.1 命令行围栏 ----------
_out = fmt("$ nmap -sV 1.2.3.4\n$ curl -s http://x/")
check("$ 提示符的命令行围栏成 bash", "```bash" in _out and "$ nmap" in _out, repr(_out[:160]))
_out = fmt("apt install nginx\npython3 -m venv /opt/venv")
check("连续两行裸命令也围栏", "```bash" in _out, repr(_out[:160]))
check("单行带 URL 的请求也围栏", "```bash" in fmt("curl -I http://127.0.0.1"), "")
check("单行普通裸命令仍不围栏（免得误伤正文）", "```bash" not in fmt("chmod 755 deploy.sh"), "")
check("HTTP 动词行围栏", "```bash" in fmt("POST /api/user/ip-whitelist {\"ip\":\"1.2.3.4\"}"), "")
check("带中文的行不当命令", "```bash" not in fmt("cat 一下这个文件\ncurl 也行"), "")

# ---------- §8.2 details ----------
_out = fmt("<details>\n<summary>展开</summary>\n\n```\nlog\n```\n\n</details>")
check("details 折叠块原样保留", "<details>" in _out and "</details>" in _out, repr(_out[:160]))
check("details 里的行不被当成裸标题", "## <summary>" not in _out and "## </details>" not in _out, repr(_out[:200]))

# ---------- §11 凭证遮盖 ----------
_out = fmt("数据库 密码: YunHai@2026")
check("密码值被遮盖", "secret-toggle" in _out and "YunHai@2026" in _out, repr(_out[:200]))
check("遮盖用 v1.4 的 secret-toggle/mask/value 三件套",
      "secret-mask" in _out and "secret-value" in _out, repr(_out[:220]))
check("遮罩固定成点号（不泄露口令长度）",
      'secret-mask\">••••••</span>' in _out, repr(_out[:220]))
check("纯中文的值不遮（「密码错误」不是凭证）",
      "secret-toggle" not in fmt("密码错误，重试一次"), repr(fmt("密码错误，重试一次")[:120]))
check("代码块里的密码不遮（遮了命令就跑不动）",
      "secret-toggle" not in fmt("```\nmysql -uroot -pZx9secret\n```"), "")
_out = fmt("| 主机 | 口令 |\n|---|---|\n| gw1 | Zx9!pw |")
check("口令整列遮盖", "Zx9!pw</span></span>" in _out and "secret-toggle" in _out, repr(_out[:260]))
_twice = fmt(_out)
check("遮盖是幂等的（不会套两层 span）", _twice.count("secret-toggle") == 1, f"{_twice.count('secret-toggle')}")

# ---------- 幂等：真实长度的笔记 ----------
_synth = "\n\n".join(
    f"## 第{i}节\n\n段落 {i}。密码: p{i}ss\n\n```\ncmd{i}\n```" for i in range(8)
)
_once = fmt(_synth, title="幂等测试")
_twice = fmt(_once, title="幂等测试")
check("排版严格幂等（再排一次一字不差）", _once == _twice,
      f"{len(_once)} vs {len(_twice)}")

# ---------- 报告 ----------
_text, _rep = note_format.format_note_with_report("正文一句。", title="标题")
check("报告能说出改了哪几处", isinstance(_rep, dict) and "frontmatter_added" in _rep, repr(_rep))
_same = fmt("正文一句。", title="标题")
_, _rep2 = note_format.format_note_with_report(_same, title="标题")
check("已经规范的笔记报告为空", _rep2 == {}, repr(_rep2))

# ---------- 规则清单 ----------
_rules = note_format.rule_catalog()
check("规则清单非空", len(_rules) >= 10, str(len(_rules)))
check("规则清单 id 不重复", len({r["id"] for r in _rules}) == len(_rules), "")
check("每条规则都标了规范章节", all(r["section"].startswith("§") for r in _rules), "")


# ===========================================================================
# 要素层（v1.9）—— 参考样板里那些「格式撑不起来」的东西
# ===========================================================================

# ---------- 敏感度判定 / 横幅 ----------
_sens_src = "数据库 密码: Zx9!pw\n目标 43.248.185.60:9994\n后台可匿名注册"
_out = fmt(_sens_src, title="后台注册")
check("有凭证 + 有真地址 → sensitivity: secret", "sensitivity: secret" in _out, _out[:200])
check("secret 笔记自动加最高机密横幅", "[!danger] 最高机密" in _out, _out[:400])
check("普通笔记不会被打上 secret", "sensitivity: secret" not in fmt("今天开会讨论了三件事。", title="会议"), "")
_out = fmt("客户合同金额 12 万，内部资料。", title="合同备注")
check("客户/金额类 → confidential", "sensitivity: confidential" in _out and "[!warning] 内部资料" in _out, _out[:300])

# ---------- 目标 / 元信息 ----------
_out = fmt("扫到 43.248.185.60:9994 与 gc.wki8.com:8087 两个入口。", title="资产")
check("元信息卡带「目标」行", "**目标**" in _out and "43.248.185.60" in _out, _out[:500])
check("端口只从 host:port 里取（不把 17:17 当端口）",
      "端口 `17`" not in fmt("2026-11-08 17:17 发生了一件事。", title="时间"), "")

# ---------- 章节编号 ----------
_out = fmt("## 背景\n\n正文。\n\n## 步骤\n\n1. 做\n\n### 准备\n\n先准备。", title="编号")
check("H2 自动编号", _out.count("## ") >= 2 and "## 🎯 1. 背景" in _out, _out[:300])
check("H3 跟着父章节编号", "### 2.1 准备" in _out, _out[:500])
_twice = fmt(_out, title="编号")
check("编号幂等（不会 1. 1. 背景）", _twice == _out, "")

# ---------- 语言标签 → 代码块 ----------
_out = fmt("xml\n<text x='70'>KA4B</text>\n实测命中。", title="验证码")
check("单独一行语言标签 → 代码块", "```xml" in _out, _out[:400])
check("语言标签后的中文句子不被吸进代码块", "实测命中。" in _out and "实测命中。</code>" not in _out, _out[:400])
_out = fmt("## 📌 xml\n\n<text x='70'>KA4B</text>", title="旧笔记")
check("被误提升成标题的 xml 会还原成代码块", "## 📌 xml" not in _out and "```xml" in _out, _out[:300])

# ---------- 风险条目 → callout ----------
_out = fmt("C2 严重 —— 图形验证码明文下发\n/api/auth/captcha 的 SVG 里直接写字符\n实测全自动。", title="风险")
check("风险条目变 danger callout", "> [!danger] C2 严重" in _out, _out[:300])
check("风险条目下的证据被收进 callout", "> /api/auth/captcha" in _out, _out[:300])
_out = fmt("C5 中 —— 卡密兑换无频控\n说明文字。", title="风险2")
check("中危用 warning", "> [!warning] C5 中" in _out, _out[:200])

# ---------- 修复建议 → 待办清单 ----------
_out = fmt("## 修复建议\n\n关掉 auth.register\n验证码改位图\n限制可信代理", title="修复")
check("修复章节里的条目变 - [ ]", _out.count("- [ ] ") >= 3, _out[:500])

# ---------- 相关 / 变更日志 ----------
_out = fmt("一些内容。\n\n" + "\n\n".join(f"## 第{i}节\n\n正文{i}" for i in range(6)),
           title="相关测试", related=["云海18001-ZFAKA全链路复现与数据导出记录-20261108"])
check("related 写进 front-matter 且带引号", '  - "[[云海18001' in _out, _out[:300])
check("正文尾部生成「相关」区", "## 🔗" in _out and "[[云海18001" in _out, _out[-500:])
_tw = fmt(_out, title="相关测试")
check("已有「相关」章节（带编号/emoji）不会再加一份",
      _tw.count("相关") == _out.count("相关"), f"{_out.count('相关')} -> {_tw.count('相关')}")
check("已有元信息卡会跟着 front-matter 更新（不再留旧的 11 行卡）",
      "**创建**" not in _tw and "**日期**" in _tw, _tw[:400])
check("长笔记生成变更日志表", "变更日志" in _out and "| **📅 日期**" in _out, _out[-400:])

# ---------- 标签清洗 ----------
_out = fmt("<text fill='#30456b'>KA4B</text>\n\n正文。", title="颜色码")
check("十六进制颜色码不会被当成标签", "#30456b" not in _out.split("---")[1] if _out.startswith("---") else True,
      _out[:300])

# ---------- AI 结构化块 ----------
_st = {
    "tldr": ["后台注册开放且免邮箱验证。", "图形验证码明文下发，注册全自动。"],
    "sensitivity": "secret",
    "tags": ["pentest", "api"],
    "risks": [{"id": "C2", "severity": "严重", "title": "验证码明文", "evidence": "SVG 里写字符"}],
    "targets": [{"name": "43.248.185.60", "port": "9994", "stack": "Spring Boot", "result": "可匿名注册"}],
    "timeline": [{"time": "2026-11-08 17:17", "event": "下单未支付"}],
    "sections": [],
}
_out = fmt("## 背景\n\n一些内容。", title="结构化", structure=_st)
check("AI 的 TL;DR 写进摘要卡", "> [!abstract] 摘要" in _out and "图形验证码明文下发" in _out, _out[:400])
check("AI 的目标表", "**🎯 资产**" in _out and "Spring Boot" in _out, _out[:900])
check("AI 的风险表", "**🆔 编号**" in _out and "🔴 严重" in _out, _out[:1200])
check("AI 的时间线", "**🕐 时间**" in _out and "下单未支付" in _out, _out[:1500])
check("结构块幂等（不会叠两份）", fmt(_out, title="结构化", structure=_st) == _out, "")

# ---------- 要素体检 ----------
_aud = note_format.element_audit(_out)
check("要素体检项数够（≥15）", len(_aud) >= 15, str(len(_aud)))
check("要素体检能报出结构要素齐全", all(a["present"] for a in _aud if a["id"] in
      ("frontmatter", "abstract", "meta_card", "numbered", "table", "h1")),
      str([a for a in _aud if not a["present"]]))
_aud2 = note_format.element_audit("随便一段话")
check("空笔记的要素体检大部分为缺", sum(1 for a in _aud2 if not a["present"]) >= 10,
      str(sum(1 for a in _aud2 if not a["present"])))

# ---------- 骨架模板 ----------
from app.services import note_profile as _prof  # noqa: E402
_sk = _prof.skeleton("pentest-record", title="云海18001 复现记录")
check("渗透骨架：最高机密横幅", "[!danger] 最高机密" in _sk, _sk[:300])
check("渗透骨架：章节带编号", "## ⛓️ 2. 攻击链" in _sk or "## ⛓️ 2. 攻击链" in _sk.replace(" / 复现步骤", ""), _sk[:1200])
check("渗透骨架：目标表 / 风险表占位", "**🎯 资产**" in _sk and "|:---|" in _sk, _sk[:1200])
check("渗透骨架：目录", "## 📑 目录" in _sk, _sk[:800])
check("渗透骨架：时间线 / 修复建议", "⏱️" in _sk and "🛠️" in _sk, _sk[-1200:])
check("骨架本身就是规范形态（再排一次不变）",
      note_format.format_note(_sk, title="云海18001 复现记录") == _sk, "")
_sk2 = _prof.skeleton("troubleshoot", title="网关 502")
check("排障骨架要素：现象 / 根因 / 修复 / 回归",
      all(k in _sk2 for k in ("💥 1. 现象", "🎯 4. 根因", "🔧 5. 修复", "✅ 6. 回归验证")), _sk2[:1200])


# ===========================================================================
# 从聊天界面整段复制（v1.8）—— 这是最脏、也最常见的输入
# 复制出来的 Markdown 会：丢围栏、表格变 TSV、标题带「一、」、夹着状态噪音
# ===========================================================================

_talk = """本轮最有价值的一条：整个 maccms 应用目录可读，以及由此确认了部署版本与 CVE 未打补丁。报告 → round4_deep_dive_findings.md
一、重大发现：application 目录可读
非 PHP 文件明文返回（无 PHP 执行）：
代码块
/application/admin/view/index/index.html    → 200, 13489B, 完整后台模板源码
/application/admin/view/collect/index.html  → 200, 5608B
后台模板共 14 个全部明文可读。

四、还没打通的（避免重复投入）
## 📌 7. 目标	卡点	已排除

宝塔 7.7.0	安全入口随机	44 词字典
MySQL 3306	root 口令	65 组直连

16:06
用量 38.2M tok
已完成
"""
_t = fmt(_talk, title="本轮最有价值的一条")

check("「代码块」标记 + 裸代码 → 围栏代码块", "```text" in _t and "/application/admin/view" in _t, _t[:600])
check("代码块标记本身不再出现在正文", "\n代码块\n" not in _t and "## 📌 代码块" not in _t, _t[:600])
check("「一、」中文序号变成章节标题", "## 🎯 1. " in _t or "## 📌 1. " in _t, _t[:800])
check("「四、」也认", "还没打通的" in _t and "## " in _t, _t[:900])
check("制表符表格 → 真表格", "| **目标** | **卡点** | **已排除** |" in _t, _t[:1200])
check("聊天状态噪音被丢掉", "16:06" not in _t and "38.2M tok" not in _t, _t[:1500])
check("超长首行当标题时 H1 会截断",
      re.search(r"^# \S+ 本轮最有价值的一条$", _t, re.M) is not None, _t[:200])
_full_title = "本轮最有价值的一条：整个 maccms 应用目录可读，以及由此确认了部署版本与 CVE 未打补丁。报告 → round4_deep_dive_findings.md"
_t2 = fmt(_talk, title=_full_title)
check("首段与标题重复时不再重复写一遍",
      _t2.count("本轮最有价值的一条：整个 maccms 应用目录可读") == 1, _t2[:800])
check("超长标题的 H1 截到一句话", "# ⚔️ 本轮最有价值的一条" in _t2, _t2[:300])

# 已经排坏的笔记：## 代码块 的标题 + 裸代码 → 还原
_broken = """## 📌 2. 代码块

/application/admin/view/index/index.html    → 200, 13489B
/application/admin/view/collect/index.html  → 200, 5608B

## 📌 3. module	状态

session	✅ 免登录
auth	免登录
"""
_b = fmt(_broken, title="已排坏的笔记")
check("已存在的「## 代码块」章节被还原成代码块",
      "## 📌" not in _b and "```text" in _b, _b[:500])
check("带制表符的标题被还原成表格",
      "| **module** | **状态** |" in _b and "| session |" in _b, _b[:600])

# 端口：文件行号不是端口
check("setting.php:54 不被当成端口 54",
      "`54`" not in fmt("报错在 /www/kod/config/setting.php:54 这一行。", title="报错"),
      fmt("报错在 /www/kod/config/setting.php:54 这一行。", title="报错")[:400])

# 幂等：这种脏输入排两次必须一致
check("脏输入排版幂等", fmt(_t, title="本轮最有价值的一条") == _t, "")

# 代码块里不该出现遮盖标记（会被渲染成源码）
_span = '<span class="secret-toggle" tabindex="0"><span class="secret-mask">••••••</span><span class="secret-value">Zx9!pw</span></span>'
_ci = fmt("## 📌 代码块\n\nmysql -uroot -pZx9!pw\n密码哈希为 " + _span + " 就是 md5(admin)")
check("代码块里的遮盖标记还原成明文",
      "secret-toggle" not in _ci and "Zx9!pw" in _ci, _ci[:600])


# ===========================================================================
# 段落密度 + 保存时维护（v1.9）
# ===========================================================================

# 一句话一段 → 合并；真段落不被合并
_chat = "先测试后台页面。\n\n后台是 web.php 需要登录。\n\n让我用 curl 测试一下。\n\n" + ("这是一段真正的长段落，讲了很久的来龙去脉，" * 8)
_c = fmt(_chat, title="聊天记录")
_lines = [l for l in _c.split("\n") if l.strip()]
check("一句话一段会被合并（不再是每句隔一屏）",
      "先测试后台页面。\n后台是" in _c and "后台是 web.php 需要登录。\n让我用" in _c, _c[:700])
check("长段落不会被硬合到一起",
      "这是一段真正的长段落" in _c, _c[:800])

# 空章节
_empty = "## 有内容的\n\n正文。\n\n## 空的\n\n## 也空的\n\n## 还有一个\n\n结尾。"
_e = fmt(_empty, title="空章节")
check("空章节被删掉", "空的" not in _e.replace("空章节", ""), _e[:500])
check("有内容的章节还在", "有内容的" in _e, _e[:500])

# 保存时维护：version / updated / 变更日志
_note = """---
title: 手工维护测试
tags: [a]
created: 2026-01-01
updated: 2026-01-01
source: human
version: 1.0
scope: concept
status: active
sensitivity: public
---

# 手工维护测试

> [!info] 元信息
> - **日期**: 📅 创建 2026-01-01
> - 来源 👤 人工 · 类型 💡 概念 · 状态 ✅ 生效 · 版本 1.0

正文第一版。
"""
_touched, _info = note_format.touch_note(
    _note.replace("正文第一版。", "正文第二版，多了几个字。"),
    old_content=_note, source="human", today="2026-11-08",
)
check("保存后 version 升一位（1.0 → 1.1）", "version: 1.1" in _touched, _touched[:200])
check("保存后 updated 变今天", "updated: 2026-11-08" in _touched, _touched[:200])
check("短笔记也会有变更日志（制度要求：每篇都能说清谁改的）",
      "## 📝 变更日志" in _touched, _touched[-300:])
check("元信息卡跟着刷新版本", "版本 1.1" in _touched, _touched[:600])


_same, _info2 = note_format.touch_note(_touched, old_content=_touched, today="2026-11-08")
check("正文没变时不动版本", "version: 1.1" in _same and _info2 == {}, str(_info2))

# 长笔记：没有变更日志时补一个
_long_note = _note + "\n" + "\n".join(f"行 {i}：一些内容" for i in range(20))
_t2, _ = note_format.touch_note(_long_note, old_content=_long_note.replace("正文第一版。", "旧"), today="2026-11-08")
check("长笔记保存后自动补变更日志章节", "## 📝 变更日志" in _t2, _t2[-300:])
check("变更日志追加了真实记录（写清改了什么，不是只写 +N 字符）",
      "人工编辑 · " in _t2 and "改" in _t2.splitlines()[-1]
      and ("行）" in _t2.splitlines()[-1] or "字符" in _t2.splitlines()[-1]), _t2[-300:])


# ---------- 结构自愈（旧快照保存不该把派生块吃掉）----------
_stale = """---
title: 旧快照
tags: [a]
created: 2026-01-01
updated: 2026-01-01
source: human
version: 1.0
scope: concept
status: active
sensitivity: public
related:
  - "[[另一篇]]"
---

# 📌 旧快照

""" + "\n".join(f"## 第{i}节\n\n内容 {i}。" for i in range(6))
_fixed, _added = note_format.ensure_derived(_stale, today="2026-11-08")
check("旧快照缺派生块时能自愈（目录/相关/变更日志）",
      "## 📑 目录" in _fixed and "## 🔗" in _fixed and "变更日志" in _fixed, f"{_added}")
check("自愈幂等（修好后不再变化）",
      note_format.ensure_derived(_fixed, today="2026-11-08")[1] == [], "")

_t3, _i3 = note_format.touch_note(
    _stale.replace("内容 0。", "内容 0（改）。"), old_content=_stale, today="2026-11-08")
check("保存旧快照：派生块回来了", "变更日志" in _t3 and "## 🔗" in _t3, _t3[-300:])
check("版本只按真实改动 +1（自愈补的字数不算）",
      _i3.get("delta") == 3, str(_i3))

# 短笔记不该被硬塞派生块
_short = _stale.split("---")[2] + "\n".join(f"## 第{i}节\n\n短。" for i in range(1))
_s2, _a2 = note_format.ensure_derived("---\ntitle: 短\ntags: []\ncreated: 2026-01-01\n---\n# 短\n\n一句话。")
check("短笔记不硬加目录（但会有变更日志）", "目录" not in str(_a2), str(_a2))


# ---------- 「改了什么」必须写清楚（不是 +N 字符）----------
_old = """## 一、背景

旧背景。

## 二、结论

旧结论。

## 三、步骤

第一步。
"""
_new = """## 一、背景

新背景，写清楚了为什么。

## 二、结论

旧结论。

## 四、时间线

- 10:00 开始

## 三、步骤

第一步。
第二步。
"""
_d = note_format.describe_change(_old, _new)
check("变更描述点出改动章节", "改「背景」" in _d, _d)
check("变更描述带原文片段", "新背景" in _d, _d)
check("变更描述带行级增减", "+1/" in _d or "−1" in _d, _d)
check("变更描述能识别新增章节", "新增「时间线」" in _d, _d)
check("没有章节的笔记也能说清改哪儿",
      "正文开头" in note_format.describe_change("甲", "甲乙"),
      note_format.describe_change("甲", "甲乙"))

print()
print(f"{PASSED} 项通过，{FAILED} 项失败")
sys.exit(1 if FAILED else 0)
