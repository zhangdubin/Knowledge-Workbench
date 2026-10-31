"""笔记排版规范化（按《笔记 UI 排版规范》执行）

这个模块做的是**直接排版**，不是给建议 ——
和 Obsidian 里新建笔记自动套模板是一个意思：
输入一段散乱的正文，输出已经符合规范、可以直接读的笔记。

为什么不完全交给大模型：
  1. 规范里有大量**确定性规则**（H2 标题要带 emoji、表格表头要加粗、
     代码块要标语言、分割线前后要空行）—— 这些用代码做又快又准，
     模型反而容易漏。
  2. 没配 AI Key 时也得能用（本地规则模式）。
  3. 规范会演进；规则写成代码，改规范就是改一张表，不是改提示词。

所以这里是「规则打底 + 模型可选增强」：
  - `format_note()`  —— 纯规则，永远可用
  - 大模型只用来做**它比规则强的那件事**：判断哪段是摘要、给标题配语义合适的 emoji。

规范来源：《笔记 UI 排版规范》v1.7
"""
from __future__ import annotations

import re
from datetime import date

# ---------------------------------------------------------------------------
# 规范表
# ---------------------------------------------------------------------------

# §1 标题层级：H2 标题按章节类型配 emoji
SECTION_EMOJI: list[tuple[tuple[str, ...], str]] = [
    (("背景", "概述", "简介", "总览"), "🎯"),
    (("步骤", "操作", "流程", "教程"), "🔧"),
    (("配置", "参数", "设置"), "⚙️"),
    (("数据", "表格", "指标"), "📊"),
    (("警告", "注意", "风险", "避坑"), "⚠️"),
    (("成功", "完成", "结果"), "✅"),
    (("失败", "错误", "排查"), "❌"),
    (("待办", "todo", "TODO", "任务"), "📋"),
    (("安全", "权限"), "🔒"),
    (("时间线", "时间", "日期"), "⏱️"),
    (("变更", "更新", "日志"), "📝"),
    (("相关", "链接", "参考"), "🔗"),
    (("总结", "摘要", "小结"), "📌"),
]

# §3.1 Obsidian callout 类型
CALLOUT_TYPES = {
    "info": "信息", "tip": "技巧", "warning": "注意", "danger": "危险",
    "example": "示例", "question": "疑问", "success": "成功",
    "failure": "失败", "note": "笔记", "quote": "引用",
    "abstract": "摘要", "todo": "待办",
}

# §5.2 表格里的状态 → emoji
STATUS_EMOJI: list[tuple[str, str]] = [
    ("已完成", "✅"), ("完成", "✅"), ("进行中", "🚧"), ("待开始", "⏳"),
    ("待处理", "⏳"), ("已失败", "❌"), ("失败", "❌"), ("已废弃", "🚫"),
    ("废弃", "🚫"), ("慎用", "⚠️"), ("待确认", "❓"),
]

# §6.1 代码块语言：按内容猜一个（猜不到就不标，不瞎标）
# 代码块语言识别
#
# 「AI 对内容识别不到位、排版时没有识别到代码」——除了编辑器不认代码，
# 这里也只扫了前 5 行：长代码块的语言特征（比如第 20 行才出现的
# `def` / `SELECT`）根本扫不到，于是整块代码没有语言标识。
#
# 现在扫**全文**，并且语言线索更全。
_LANG_HINTS: list[tuple[str, str]] = [
    (r"^\s*(docker|docker-compose|dockerfile)\b", "bash"),
    (r"^\s*(\$|#!|npm|yarn|pnpm|pip\s|git\s|curl\s|wget\s|cd\s|ls\s|mkdir\s|chmod\s|apt\s|apt-get\s|yum\s|brew\s|export\s|source\s|systemctl\s|kubectl\s|helm\s|tar\s|ssh\s|scp\s|rsync\s)", "bash"),
    (r"^\s*(sudo|set\s+-[euxo]|if\s|then|else|fi|for\s|while\s|do|done|case\s|esac|function\s|return\s|echo\s)", "bash"),
    (r"^\s*#!/usr/bin/env\s+(python|node|ruby|perl|php)", "python"),
    (r"^\s*#!/bin/(ba)?sh", "bash"),
    (r'^\s*\{\s*$', "json"),
    (r'^\s*\{\s*"[^"]+"\s*:', "json"),
    (r'^\s*\[[\s\n]*\{\s*"', "json"),
    (r"^\s*<\?xml", "xml"),
    (r"^\s*<\w+[^>]*>\s*</\w+>", "html"),
    (r"^\s*<!DOCTYPE\s+html", "html"),
    (r"^\s*(from\s+\w+\s+import|import\s+\w+|def\s+\w+\s*\(|class\s+\w+|print\s*\(|if\s+__name__|self\.|async\s+def|@\w+\.\w+)", "python"),
    # 裸赋值（x = 1 / a.b = 2）—— Python 最常见的形态
    (r"^\s*[A-Za-z_][\w.]*\s*=\s*[^=>]", "python"),
    (r"^\s*(SELECT|select|INSERT|insert|UPDATE|update|DELETE|delete|FROM|from|WHERE|where|JOIN|join|GROUP\s+BY|ORDER\s+BY)\b", "sql"),
    (r"^\s*(CREATE\s+TABLE|ALTER\s+TABLE|PRAGMA|GRANT\s|REVOKE\s)", "sql"),
    (r"^\s*[\w.-]+\s*:\s*\S", "yaml"),
    (r"^\s*[-]{3}\s*$", "yaml"),
    (r"^\s*(package|import|export|const|let|var|function|=>|async\s+function)\s", "javascript"),
    (r"^\s*<(?:div|span|p|a|html|body|head)\b", "html"),
    (r"^\s*[.#]?\w+\s*\{\s*$", "css"),
    (r"^\s*[@\w.-]+\s*\([^)]*\)\s*\{", "css"),
    (r"^\s*(public|private|protected)\s+\w+", "java"),
    (r"^\s*(func|package)\s+\w+", "go"),
    (r"^\s*(use|fn|impl|struct|pub)\s", "rust"),
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_EMOJI_RE = re.compile(
    "^[\U0001F300-\U0001FAFF☀-➿⬀-⯿️"
    "\U0001F1E6-\U0001F1FF]+"
)
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*(\S*)")
_HR_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
_CALLOUT_RE = re.compile(r"^\s*\[!(\w+)\]([+-]?)\s*(.*)$")
_TASK_RE = re.compile(r"^\s*[-*]\s+\[([ xX~\-/])\]\s*(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:\-|]+\|[\s:\-|]*$")


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def emoji_for_heading(title: str) -> str:
    """给 H2 标题配一个语义合适的 emoji（§1）"""
    plain = _strip_emoji(title)
    for keys, emoji in SECTION_EMOJI:
        if any(k.lower() in plain.lower() for k in keys):
            return emoji
    return "📌"


def _looks_like_code(line: str) -> bool:
    for pat, _lang in _LANG_HINTS:
        if re.search(pat, line):
            return True
    return False


def _guess_lang(lines: list[str]) -> str:
    """猜代码块语言（§6.1）

    ⚠️ 要扫**全文**，不能只看开头几行：
    很多代码块的语言特征在中间或靠后（比如先写注释和配置，
    第 20 行才出现 def / SELECT）。只扫前 5 行的话，
    「AI 没识别到代码」就变成「代码块没有语言标识」。
    """
    body = [l for l in lines if l.strip()]
    if not body:
        return ""
    # 先看前 8 行（语言特征通常靠前，命中更快），
    # 没命中再扫全文 —— 避免整块很长的代码被逐行正则拖慢。
    for line in body[:8]:
        for pat, lang in _LANG_HINTS:
            if re.search(pat, line):
                return lang
    for line in body[8:]:
        for pat, lang in _LANG_HINTS:
            if re.search(pat, line):
                return lang
    return ""


def _format_table(rows: list[str]) -> list[str]:
    """表格美化：表头加粗、状态值配 emoji（§5.1 / §5.2）"""
    if len(rows) < 2:
        return rows
    header = rows[0].strip().strip("|").split("|")
    sep = rows[1]
    body = rows[2:]

    def cell(raw: str) -> str:
        return raw.strip()

    # 表头加粗
    new_header = "| " + " | ".join(f"**{cell(h)}**" for h in header) + " |"
    # 表头里的状态词也配 emoji
    def emoji_cell(v: str) -> str:
        # 只在整格正好是状态词时才加；含其它文字的不动
        for word, em in STATUS_EMOJI:
            if v == word:
                return f"{em} {v}"
        return v

    new_body = []
    for r in body:
        cells = r.strip().strip("|").split("|")
        # 注意：加 emoji 时要加在**单元格内部**，
        # 不能把「状态」换成「✅」再分成两列 —— 那表格的列数就乱了
        new_body.append("| " + " | ".join(emoji_cell(cell(c)) for c in cells) + " |")
    return [new_header, sep] + new_body


def _add_status_emoji_to_cells(line: str) -> str:
    """表格行里的「已完成」这类词加 emoji"""
    parts = line.split("|")
    out = []
    for p in parts:
        s = p.strip()
        for word, em in STATUS_EMOJI:
            if s == word:
                s = f"{em} {word}"
                break
        out.append(p.replace(p.strip(), s) if p.strip() else p)
    return "|".join(out)


def format_note(text: str, *, title: str = "", add_summary: bool = True) -> str:
    """把一段正文排成符合《笔记 UI 排版规范》的笔记。

    做的事情（都能在规范里对上号）：
      §1  H2/H3 标题补语义 emoji；保证全文只有一个 H1
      §3  引用块转成 Obsidian callout（`> [!info]` 这种）
      §5  表格表头加粗、状态值配 emoji
      §6  代码块补语言标识
      §8  分割线前后留空行；`---` 统一
      §8.3 任务列表统一成 GitHub 风格
      §3.2 顶部补一个 `[!abstract]` 摘要块
    """
    if not text or not text.strip():
        return text or ""

    src = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = src.split("\n")
    out: list[str] = []
    i = 0
    seen_h1 = False

    while i < len(lines):
        line = lines[i]

        # ---- 代码块：补语言标识（§6.1）----
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0] * 3
            lang = fence.group(2)
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                body.append(lines[i])
                i += 1
            i += 1  # 跳过收尾的 ```
            if not lang:
                lang = _guess_lang(body)
            out.append(f"```{lang}")
            out.extend(body)
            out.append("```")
            out.append("")
            continue

        # ---- 表格（§5）----
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1]:
            rows = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(lines[i])
                i += 1
            out.extend(_format_table(rows))
            out.append("")
            continue

        # ---- 引用块 → callout（§3）----
        if re.match(r"^\s*>\s?", line):
            buf: list[str] = []
            while i < len(lines) and re.match(r"^\s*>\s?", lines[i]):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            joined = "\n".join(buf).strip()
            callout = _CALLOUT_RE.match(joined.split("\n")[0] if joined else "")
            if callout:
                ctype = callout.group(1).lower()
                fold = callout.group(2)
                title = callout.group(3).strip()
                rest = "\n".join(joined.split("\n")[1:]).strip()
                head = f"> [!{ctype}]{fold}" + (f" {title}" if title else "")
                out.append(head)
                if rest:
                    for r in rest.split("\n"):
                        out.append(f"> {r}" if r.strip() else ">")
                out.append("")
                continue
            # 不是 callout 的普通引用 → 转成 note callout（§3.2 章节首句用 note/tip）
            out.append("> [!note]")
            for r in joined.split("\n"):
                out.append(f"> {r}" if r.strip() else ">")
            out.append("")
            continue

        # ---- 标题（§1）----
        h = _HEADING_RE.match(line)
        if h:
            level = len(h.group(1))
            title_txt = h.group(2).strip()
            if level == 1:
                # 全文只留一个 H1（§1：H1 = 笔记名）
                if seen_h1:
                    i += 1
                    continue
                seen_h1 = True
                out.append(f"# {title_txt}")
            elif level == 2:
                plain = _strip_emoji(title_txt)
                if not plain:
                    i += 1
                    continue
                # 已经有 emoji 就不重复加
                if title_txt.startswith(_EMOJI_RE.match(title_txt).group(0) if _EMOJI_RE.match(title_txt) else "\0"):
                    out.append(f"## {title_txt}")
                else:
                    out.append(f"## {emoji_for_heading(title_txt)} {title_txt}")
            elif level == 3:
                out.append(f"### {title_txt}")
            else:
                out.append(line.rstrip())
            out.append("")
            i += 1
            continue

        # ---- 分割线（§8.1）：前后空一行 ----
        if _HR_RE.match(line):
            if out and out[-1] != "":
                out.append("")
            out.append("---")
            out.append("")
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue

        # ---- 任务列表（§8.3）：统一 GitHub 风格 ----
        t = _TASK_RE.match(line)
        if t:
            mark, rest = t.group(1), t.group(2)
            sym = {"x": "x", "X": "x", " ": " ", "~": "-", "-": "-", "/": "?"}[mark]
            # 状态词加 emoji：「完成项」这种带后缀的也要认出来
            for word, em in STATUS_EMOJI:
                if rest.startswith(word):
                    rest = f"{em} {rest}"
                    break
            out.append(f"- [{sym}] {rest}")
            i += 1
            continue

        # ---- 裸标题 ----
        # 「背景」「部署」这种独占一行、后面不跟内容的短行，
        # 明显是标题（作者手写时忘了打 #）—— 提升成 H2 并配 emoji。
        # 判据：短（<= 12 字）、不含句号标点、下一行是空行或正文。
        stripped = line.strip()
        if (
            stripped
            and len(stripped) <= 12
            and not stripped.startswith(('#', '>', '|', '-', '*', '`', '='))
            and not stripped.endswith(('。', '，', '.', ',', '；', ';', '：', ':', '！', '!', '？', '?'))
            and not _looks_like_code(stripped)
        ):
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            nxt2 = lines[i + 2].strip() if i + 2 < len(lines) else ""
            # 后面是空行 → 标题后面跟的是一整节
            # 后面直接是正文 → 也是标题（作者手写标题后紧跟段落，最常见）
            # 后面是别的结构（标题/引用/表格/列表）→ 也是标题
            looks_like_heading = (
                nxt == ""
                or nxt.startswith(('#', '>', '|', '-', '*', '`'))
                or (nxt != "" and not nxt2.startswith(('#', '>', '|', '-', '*', '`')))
            )
            if looks_like_heading and stripped:
                out.append(f"## {emoji_for_heading(stripped)} {stripped}")
                out.append("")
                i += 1
                continue

        out.append(line.rstrip())
        i += 1

    # ---- 收拾尾部空行 ----
    while out and out[-1] == "":
        out.pop()
    result = "\n".join(out).strip() + "\n"

    # ---- 顶部摘要 callout（§3.2）----
    #
    # 摘要不能是首段的复制 —— 那等于白加一块，还占地方。
    # 规则版做不到「概括」，所以这里**不硬加**摘要：
    # 宁可没有（正文自己会读），也不要一段重复的废话。
    # 有大模型时由模型写真正的摘要（见 ai.beautify_layout）。
    if add_summary and result and not result.lstrip().startswith("> [!"):
        # 只在正文里**没有**任何一级标题时加一个占位摘要块，
        # 否则读者连这篇讲什么都看不出来。
        if not _HEADING_RE.match(result.lstrip().split("\n")[0]):
            first_para = _first_paragraph(result)
            if first_para:
                summary = first_para[:120] + ("…" if len(first_para) > 120 else "")
                result = f"> [!abstract] 摘要\n> {summary}\n\n" + result

    return result


def _first_paragraph(md: str) -> str:
    """取第一段正文（跳过 frontmatter、标题、callout）"""
    lines = md.split("\n")
    buf: list[str] = []
    started = False
    for ln in lines:
        s = ln.strip()
        if s == "---" and not started:
            # 可能 frontmatter
            continue
        if not s:
            if started:
                break
            continue
        if s.startswith("#") or s.startswith(">") or s.startswith("```"):
            if started:
                break
            continue
        # 列表项、任务项、分隔线都不是「摘要」——
        # 把它们吸进摘要块会得到一坨看不懂的东西
        if s.startswith(("- ", "* ", "+ ", "|", "1. ", "2. ", "3. ")) or _HR_RE.match(s):
            if started:
                break
            continue
        buf.append(s)
        started = True
    return " ".join(buf).strip()


def note_template(title: str, *, tags: list[str] | None = None,
                  source: str = "human", scope: str = "concept",
                  status: str = "draft", summary: str = "") -> str:
    """新建笔记的模板（§2 front-matter + §1 标题层级）

    和 Obsidian 里「从模板新建」是一回事 ——
    新笔记一建出来就是符合规范的形态，不用事后再排一遍。
    """
    today = date.today().isoformat()
    tag_list = tags or []
    # 没起标题时不要写「未命名笔记」当正文标题 ——
    # 那是占位文案，不该被当成真标题存进 front-matter。
    t = title.strip()
    body_title = t or "无标题"
    fm = [
        "---",
        f"title: {t}" if t else 'title: ""',
        f"tags: [{', '.join(tag_list)}]",
        f"created: {today}",
        f"source: {source}",
        f"updated: {today}",
        "version: 1.0",
        f"scope: {scope}",
        f"status: {status}",
        "---",
        "",
        f"# {body_title}",
        "",
    ]
    if summary:
        fm += [f"> [!abstract] 摘要", f"> {summary}", ""]
    return "\n".join(fm)
