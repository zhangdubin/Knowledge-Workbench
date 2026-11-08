"""笔记排版规范化（按《笔记 UI 排版规范》执行）

这个模块做的是**直接排版**，不是给建议 ——
和 Obsidian 里新建笔记自动套模板是一个意思：
输入一段散乱的正文，输出已经符合规范、可以直接读的笔记。

为什么不完全交给大模型：
  1. 规范里有大量**确定性规则**（H2 标题要带 emoji、表格表头要加粗、
     代码块要标语言、分割线前后要空行、凭证要遮盖）—— 这些用代码做又快又准，
     模型反而容易漏。
  2. 没配 AI Key 时也得能用（本地规则模式）。这一点是硬要求：
     「排版」是笔记的基础能力，不该被 AI 授权挡住。
  3. 规范会演进；规则写成代码，改规范就是改一张表，不是改提示词。

所以这里是「规则打底 + 模型可选增强」：
  - `format_note()`  —— 纯规则，永远可用
  - 大模型只用来做**它比规则强的那件事**：写摘要、判断章节语义。

v2（规范 v1.8）补齐的能力，逐条对得上规范：
  §1    H1/H2 语义 emoji；全文只留一个 H1
  §2    front-matter 合并与补齐；related 统一成「列表 + 引号」；
        Templater 表达式（`= date(today)`）落成实际日期
  §3    引用块 → Obsidian callout；顶部摘要块；顶部元信息卡
  §4    长笔记自动生成目录（>50 行 或 H2 ≥ 5）
  §5    表格表头加粗、状态配 emoji
  §6    代码块补语言标识；连续命令行自动围栏成 bash
  §8    分割线前后留空行；任务列表统一 GitHub 风格
  §11   敏感信息（密码/口令/token/私钥…）自动包成 secret-toggle 遮盖

幂等是硬约束：排过一次的笔记再排一次，结果一字不差。
否则「保存时自动排版」会变成「每保存一次就多一坨东西」。
"""
from __future__ import annotations

import re
from datetime import date

SPEC_VERSION = "1.8"

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

# §1 笔记标题（H1）的 emoji：按「这篇是什么」挑，不是按章节类型挑。
# 命中靠前的先赢 —— 渗透记录里也有「成功」，但它的身份是渗透记录。
TITLE_EMOJI: list[tuple[tuple[str, ...], str]] = [
    (("渗透", "漏洞", "攻击", "getshell", "提权", "weblogic", "rce", "安全",
      "cve", "maccms", "后台", "未授权", "webshell"), "⚔️"),
    (("复盘", "总结", "总览", "概览", "方案", "设计", "架构"), "🧭"),
    (("排障", "故障", "异常", "报错", "修复", "定位"), "🧯"),
    (("部署", "上线", "发布", "安装", "迁移"), "🚀"),
    (("教程", "指南", "手册", "怎么", "如何"), "📖"),
    (("失败", "中断", "回滚", "废弃"), "❌"),
    (("登录", "成功", "完成", "通过", "验证"), "✅"),
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

# §2 front-matter 字段顺序（其余自定义键排后面，别丢）
FM_ORDER = [
    "title", "tags", "created", "updated", "source", "version",
    "scope", "status", "sensitivity", "related",
]

# §11 敏感信息：出现这些词，后面的值就按凭证处理
_CRED_KEY_RE = re.compile(
    r"(密码|口令|密钥|私钥|凭据|凭证|令牌|哈希|散列|"
    r"\b(?:pass|password|passwd|pwd|token|secret|api[_-]?key|apikey|"
    r"access[_-]?key|private[_-]?key|secret[_-]?key|cookie|session[_-]?id)\b)",
    re.I,
)

# 行内「键 + 分隔 + 值」：密码: xxx / password=xxx / 口令 是 xxx
_INLINE_CRED_RE = re.compile(
    r"(?P<key>密码|口令|密钥|私钥|凭据|凭证|令牌|哈希|散列|"
    r"\b(?:pass|password|passwd|pwd|token|secret|api[_-]?key|apikey|"
    r"access[_-]?key|private[_-]?key|secret[_-]?key|cookie|session[_-]?id)\b)"
    r"(?P<sep>\s*(?::|：|=|＝|是|为)\s*)"
    r"(?P<val>[^\s|,，;；`]+)"
)

# 已经是遮盖标记的行 → 不再重复处理（幂等的关键之一）
_SECRET_MARK = "secret-toggle"


def _secret_span(value: str) -> str:
    """§11 v1.4 遮盖写法（Obsidian 与知识库前端都认这一种）

    遮罩固定用点号，不用明文 —— 明文放进 mask 里，
    鼠标一扫之前它其实已经在 DOM 里、宽度也会泄露口令长度。
    """
    return (
        '<span class="secret-toggle" tabindex="0">'
        '<span class="secret-mask">••••••</span>'
        f'<span class="secret-value">{value}</span>'
        "</span>"
    )


# §6.1 代码块语言：按内容猜一个（猜不到就不标，不瞎标）
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

# 连续几行是命令 → 围栏成 bash（§6.1 的延伸：命令行也是代码）
_HTTP_LINE_RE = re.compile(
    r"^\s*(?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+/\S+"
)

_CMD_LINE_RE = re.compile(
    r"^\s*(?:(?:\$|>) ?)?(?:sudo\s+)?"
    r"(?:nmap|curl|wget|ssh|scp|rsync|docker|docker-compose|kubectl|helm|git|npm|"
    r"pnpm|pip|pip3|python|python3|node|mysql|redis-cli|psql|sqlmap|ffuf|gobuster|"
    r"dirb|nikto|hydra|msfconsole|bash|sh|systemctl|apt|apt-get|yum|brew|chmod|"
    r"chown|cat|tail|head|grep|find|tar|unzip|zip|nc|ncat|telnet|openssl|jq|awk|"
    r"sed|ls|mkdir|rm|cp|mv|ping|whoami|id|uname|ip|ifconfig|netstat|ss)\b"
)

# 从聊天界面/文档里整段复制时，代码块会掉成一行「代码块」，
# 内容变成裸文本。识别这个标记，把它还原成围栏。
_CODE_MARKER_RE = re.compile(
    r"^\s*(?:代码块|代码|code\s*block|copy\s*code|复制代码|复制|拷贝)\s*[（(]?[\w+-]*[)）]?\s*\d*\s*[:：]?\s*$",
    re.I,
)
# 中文序号标题：一、xxx / 二、xxx（从文档里复制过来的报告最常见）
_CN_HEADING_RE = re.compile(r"^\s*([一二三四五六七八九十]{1,3})[、.．]\s*(\S.*)$")
_AR_HEADING_RE = re.compile(r"^\s*(\d{1,2})[、]\s*(\S.*)$")
# 聊天界面的状态噪音（不能当标题，也不该占正文）
# 聊天界面的状态词：只有当它「下面没有任何内容」时才当噪音丢
_EMPTY_NOISE_WORDS = {"继续挖", "已完成", "已编辑", "复制", "用量", "继续"}

_NOISE_RE = re.compile(
    r"^\s*(?:已编辑\s*\S*|\+\d+\s*$|-\d+\s*$|\d{1,2}:\d{2}\s*$|"
    r".*\b\d+(?:\.\d+)?[kKmM]?\s*tok(?:ens)?\b.*)$",
    re.I,
)

_RISK_RE = re.compile(
    r"^\s*([CHML]\d{1,3}|风险\s*\d{1,3}|R\d{1,3})\s*"
    r"[—\-–:：]?\s*(严重|高危|高|中危|中|低危|低|critical|high|medium|low)?\s*"
    r"[—\-–:：]?\s*(\S.*)$",
    re.I,
)
_SEV_DANGER = ("严重", "高危", "高", "critical", "high")
_SEV_WARN = ("中", "中危", "medium")
_FIX_SECTION_RE = re.compile(r"(修复|建议|措施|待办|todo|P0)", re.I)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_EMOJI_RE = re.compile(
    "^[\U0001F000-\U0001FAFF"
    "\u2190-\u21FF\u2300-\u23FF\u2460-\u24FF"
    "\u25A0-\u27BF\u2900-\u297F\u2B00-\u2BFF"
    "\uFE0F\u200D\u20E3]+"
)
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*(\S*)")
_HR_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
_CALLOUT_RE = re.compile(r"^\s*\[!(\w+)\]([+-]?)\s*(.*)$")
_TASK_RE = re.compile(r"^\s*[-*]\s+\[([ xX~\-/])\]\s*(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:\-|]+\|[\s:\-|]*$")

# 生成块的识别（用于「先拆掉再重建」，保证幂等）
_ABSTRACT_HEAD_RE = re.compile(r"^>\s*\[!abstract\]", re.I)
# 我们生成的摘要带「覆盖：」这一行；用户手写的多半没有 —— 靠它区分
_ABSTRACT_OURS_RE = re.compile(r"^>\s*覆盖[：:]")
# 我们生成的元信息卡用「- **创建**: 📅」开头，同理
# 我们生成的元信息卡用「- **日期**: 📅 创建 …」开头，靠它区分「自己生成的」和「人写的」
_META_OURS_RE = re.compile(r"^>\s*-\s*\*\*(?:创建|日期)\*\*:\s*(?:📅|\d{4}-)")
_META_HEAD_RE = re.compile(r"^>\s*\[!info\]\s*元信息")
_TOC_HEAD_RE = re.compile(r"^##\s+📑\s*目录\s*$")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", (text or "")).strip()


def emoji_for_heading(title: str) -> str:
    """给 H2 标题配一个语义合适的 emoji（§1）"""
    plain = _strip_emoji(title)
    for keys, emoji in SECTION_EMOJI:
        if any(k.lower() in plain.lower() for k in keys):
            return emoji
    return "📌"


def emoji_for_title(title: str, scope: str = "") -> str:
    """给 H1（笔记名）配一个 emoji（§1，对齐样板间里「⚔️ 云海18001…」那种）"""
    plain = _strip_emoji(title)
    # 类型已经明确（渗透/教程）就按类型定 —— 长标题里随便一个「部署」不该把
    # 渗透记录标成 🚀
    if scope == "pentest-record":
        return "⚔️"
    by_scope = {
        "pentest-record": "⚔️", "log": "🗒️", "tutorial": "📖",
        "concept": "💡", "process": "🔧", "project": "🗂️", "expense": "🧾",
    }
    if scope in by_scope and not plain:
        return by_scope[scope]
    for keys, emoji in TITLE_EMOJI:
        if any(k.lower() in plain.lower() for k in keys):
            return emoji
    return by_scope.get(scope, "📌")


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


def _inline_tags(text: str) -> list[str]:
    """正文里的 #标签（Obsidian 行内标签）

    要排除两种假标签：
      - 链接目标 `(#1-目标与结果)` —— 那是目录锚点
      - 代码块里的 `# 注释` / `#!/bin/bash`
    """
    tags: list[str] = []
    in_code = False
    for ln in (text or "").split("\n"):
        if _FENCE_RE.match(ln):
            in_code = not in_code
            continue
        if in_code or not ln.strip():
            continue
        if ln.lstrip().startswith(("|", "#", ">")) or "](" in ln:
            continue
        # HTML/代码片段里的 # 基本都是颜色码：fill='#30456b'、href="#top"
        if "<" in ln or "fill=" in ln or "href=" in ln or "style=" in ln:
            continue
        for m in re.finditer(r"(?<![\w#(\['\"=])＃?#([\w\u4e00-\u9fff][\w\u4e00-\u9fff-]{0,31})", ln):
            t = m.group(1)
            if not t or t.isdigit():
                continue
            # 十六进制色值 / 连续十六进制串不是标签
            if re.fullmatch(r"[0-9a-fA-F]{3,8}", t) and re.search(r"\d", t):
                continue
            if t not in tags:
                tags.append(t)
    return tags


def _ensure_blank(out: list[str]) -> None:
    """块级元素前面要空一行（Markdown 里紧贴着上一段的标题不算标题）"""
    if out and out[-1].strip():
        out.append("")


def _bump(report: dict, key: str, n: int = 1) -> None:
    if n:
        report[key] = report.get(key, 0) + n


# ---------------------------------------------------------------------------
# §2 front-matter
# ---------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[str | None, str]:
    """拆出 front-matter：返回 (yaml 文本 | None, 正文)

    认不出就原样返回（None, 全文）—— 绝不把正文里的第一条分割线
    当成 front-matter 吃掉。
    """
    src = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = src.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, src
    for i in range(1, len(lines)):
        if re.match(r"^\s*(\*\*\*|___)\s*$", lines[i]):
            return None, src
        if lines[i].strip() == "---":
            block = lines[1:i]
            # 中间有空行 → 多半是正文里的分隔线，不是 front-matter
            if any(not ln.strip() for ln in block):
                return None, src
            return "\n".join(block), "\n".join(lines[i + 1:])
    return None, src


def _mini_yaml(block: str) -> dict:
    """没有 PyYAML 时的兜底解析（key: value / key: 后面跟 - item）"""
    meta: dict = {}
    cur = None
    for raw in block.split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw) or re.match(r"^-\s+(.*)$", raw)
        if item and cur:
            if not isinstance(meta.get(cur), list):
                meta[cur] = [] if not meta.get(cur) else [meta[cur]]
            meta[cur].append(_unquote(item.group(1)))
            continue
        kv = re.match(r"^([^\s:#][^:]*?)\s*:\s*(.*)$", raw)
        if kv:
            cur = kv.group(1).strip()
            val = kv.group(2).strip()
            meta[cur] = _parse_scalar(val)
    return meta


def _unquote(v: str) -> str:
    s = (v or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _parse_scalar(v: str):
    s = v.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_unquote(x.strip()) for x in inner.split(",") if x.strip()]
    return _unquote(s)


def parse_frontmatter(block: str | None) -> dict:
    """YAML front-matter → dict（解析失败也要尽量拿到东西，不能整篇丢）"""
    if not block or not block.strip():
        return {}
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}
    except Exception:
        pass
    return _mini_yaml(block)


def _yaml_scalar(v) -> str:
    """把一个值写成合法且可读的 YAML 标量"""
    if v is None:
        return '""'
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if s == "":
        return '""'
    # 这些字符会让裸标量变成别的类型 / 解析失败
    if (
        re.search(r"[:#\[\]{}&*!|>'\"%@`,]", s)
        or s != s.strip()
        or s.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~")
        or re.match(r"^[-?\s]", s)
    ):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _as_list(v) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple)):
        items = []
        for x in v:
            items.extend(_as_list(x))
        return items
    s = str(v)
    # "[[A]] [[B]]" / "[[A]] | [[B]]" 这类历史写法统一拆开
    found = re.findall(r"\[\[([^\[\]]+)\]\]", s)
    if found:
        return [x.strip() for x in found if x.strip()]
    return [s.strip()] if s.strip() else []


def normalize_related(meta: dict, report: dict | None = None) -> None:
    """§2.1 / §10：related 必须是「列表 + 引号包住的 wikilink」

    这里统一成：
        related:
          - "[[A]]"
          - "[[B]]"
    并在**写入前**做一次 yaml.safe_load 自检 —— 规范里点名的
    最常见 front-matter bug，就别再让它出现。
    """
    if "related" not in meta:
        return
    raw = meta.get("related")
    items = []
    for it in _as_list(raw):
        name = it.strip()
        if not name:
            continue
        if not (name.startswith("[[") and name.endswith("]]")):
            name = f"[[{name}]]"
        if name not in items:
            items.append(name)
    if items:
        meta["related"] = items
    else:
        meta.pop("related", None)


# 明确的语言/格式标签：单占一行时多半是「代码块的语言标识」，
# 不是章节标题（粘贴终端输出时最常见：先一行 xml，再一段 XML）
_LANGS = {
    "text", "txt", "bash", "sh", "shell", "zsh", "console", "powershell", "cmd",
    "python", "py", "js", "javascript", "ts", "typescript", "json", "jsonc",
    "yaml", "yml", "xml", "html", "css", "scss", "sql", "http", "php", "java",
    "go", "rust", "c", "cpp", "ruby", "perl", "ini", "toml", "conf", "nginx",
    "dockerfile", "makefile", "diff", "patch", "log", "csv",
}
_CODE_ISH_RE = re.compile(
    r"^\s*(?:<|\{|\[|\$|#!|curl\b|wget\b|ssh\b|sudo\b|GET\s+/|POST\s+/|"
    r"SELECT\b|INSERT\b|UPDATE\b|import\s|from\s+\w+\s+import|def\s|class\s|"
    r"docker\b|npm\b|pnpm\b|pip\b|git\b|apt(-get)?\b|systemctl\b|"
    r"[\w.-]+\s*[:=]\s*\S)",
    re.I,
)


def _looks_code_line(ln: str) -> bool:
    """这行像不像代码/命令（给「语言标签 + 代码」这种粘贴形态用）"""
    if not ln.strip():
        return False
    if _looks_like_code(ln) or _CODE_ISH_RE.match(ln):
        return True
    return False


def _is_prose(ln: str) -> bool:
    """一行像不像中文正文（用来判断代码段到哪儿结束）"""
    if not re.search(r"[\u4e00-\u9fff]", ln):
        return False
    return not _looks_like_code(ln)


def _label_fence_run(lines: list[str], i: int):
    """识别「单独一行语言标签 + 后面跟一段代码」的粘贴形态

    真实场景：从终端/文档里复制，代码围栏丢了，只剩下一个 `xml` / `bash`。
    这时候把标签当章节标题（之前的 bug）或当普通段落都不对 ——
    正确做法是把它还原成代码块的语言标识。
    返回包进围栏的行数（不含标签行），0 表示不是这种形态。
    """
    label = lines[i].strip().lower()
    if label not in _LANGS:
        return None
    # 已经是标题、列表、引用、表格行 → 不处理（标题那种由 heading 分支单独处理）
    if lines[i].lstrip().startswith(("#", "-", "*", ">", "|")):
        return None
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not _looks_code_line(lines[j]):
        return None
    k = j
    while k < len(lines) and lines[k].strip():
        if lines[k].lstrip().startswith(("#", ">", "|", "- ", "* ", "```")):
            break
        if k > j and _is_prose(lines[k]):
            break
        k += 1
    return label, lines[j:k]


_DATE_FIELDS = ("created", "updated", "date", "日期")


def resolve_actual_dates(meta: dict, today: str, report: dict | None = None) -> None:
    """§2.2：Templater 表达式（`= date(today)`）落成实际日期

    模板里写表达式没问题，但**存进 vault 的必须是实际值** ——
    否则 Dataview 查不到、git diff 也不真实。
    """
    for k in list(meta.keys()):
        if k not in _DATE_FIELDS:
            continue
        v = str(meta.get(k) or "")
        if not v.strip():
            continue
        if (
            "date(" in v
            or "{{" in v
            or v.strip().startswith("=")
        ):
            meta[k] = today
            _bump(report, "dates_resolved")


def dump_frontmatter(meta: dict) -> str:
    """dict → YAML front-matter 文本（字段顺序固定，未知键保留）"""
    keys = [k for k in FM_ORDER if k in meta] + [k for k in meta if k not in FM_ORDER]
    lines = ["---"]
    for k in keys:
        v = meta[k]
        # tags 即使为空也写（规范里它是必填项；缺字段的属性面板会少一行）
        if v is None or v == "" or (v == [] and k != "tags"):
            continue
        if k == "related":
            items = _as_list(v)
            if not items:
                continue
            lines.append("related:")
            for it in items:
                name = it if str(it).startswith("[[") else f"[[{it}]]"
                lines.append(f'  - "{name}"')
            continue
        if isinstance(v, (list, tuple)):
            lines.append(f"{k}: [{', '.join(_yaml_scalar(x) for x in v)}]")
            continue
        if isinstance(v, dict):
            # 嵌套结构不认识就别写 —— 写坏了整段 front-matter 都解析不了
            continue
        lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)


_EMOJI_HINT_SCOPE: list[tuple[tuple[str, ...], str]] = [
    (("漏洞", "渗透", "getshell", "提权", "shell", "payload", "越权", "注入",
      "未授权", "弱口令", "攻击面", "webshell", "xss", "csrf", "ssrf"), "pentest-record"),
    (("教程", "指南", "手册"), "tutorial"),
    (("步骤", "流程", "操作"), "process"),
]


def guess_scope(text: str, title: str = "") -> str:
    """猜笔记类型（§2 scope 字段）。猜不到就 concept —— 别瞎标。"""
    blob = f"{title}\n{text}".lower()
    for keys, scope in _EMOJI_HINT_SCOPE:
        if any(k.lower() in blob for k in keys):
            return scope
    # 「登录了 / 记录了 / 今天」这类流水账 → log
    if re.search(r"(记录|日志|时间线|复盘|session|session 已|今天)", blob):
        return "log"
    return "concept"


def ensure_frontmatter(
    meta: dict,
    *,
    title: str = "",
    tags: list[str] | None = None,
    source: str = "human",
    scope: str | None = None,
    status: str | None = None,
    sensitivity: str | None = None,
    today: str | None = None,
    text: str = "",
    report: dict | None = None,
) -> dict:
    """补齐 front-matter 的必填/推荐字段（§2），已有的值不覆盖"""
    today = today or date.today().isoformat()
    meta = dict(meta or {})
    report = report if report is not None else {}

    t = (title or "").strip() or str(meta.get("title") or "").strip()
    if t:
        meta["title"] = t

    # 标签：显式传入的 + front-matter 里已有的 + 正文行内 #标签
    tag_list = _as_list(meta.get("tags"))
    for x in (tags or []):
        if x and x not in tag_list:
            tag_list.append(x)
    if tag_list:
        meta["tags"] = tag_list
    else:
        meta.setdefault("tags", [])

    # 假标签清洗：fill='#30456b' 里的十六进制、#1 这种纯数字，都不是标签
    if tag_list:
        cleaned = []
        for t in tag_list:
            ts = str(t).strip().lstrip("#")
            if not ts or ts.isdigit():
                continue
            if re.fullmatch(r"[0-9a-fA-F]{3,8}", ts) and re.search(r"\d", ts):
                continue
            if ts not in cleaned:
                cleaned.append(ts)
        tag_list = cleaned
    meta["tags"] = tag_list

    meta.setdefault("created", today)
    if not str(meta.get("updated") or "").strip():
        # 只在缺失时写今天 —— 每次排版都刷新 updated，git diff 全是噪音
        meta["updated"] = today
    meta.setdefault("source", source)
    meta.setdefault("version", 1.0)
    if not str(meta.get("scope") or "").strip():
        meta["scope"] = scope or guess_scope(text, t)
    elif str(meta.get("scope")) == "concept" and not scope:
        # concept 是兜底值，不是刻意选的：内容明显是渗透/教程才升级。
        # 「log」这种弱信号不升 —— 我们自己生成的「时间线」章节就会命中它，
        # 升上去等于每次排版都改一次 scope（不幂等）。
        guessed = guess_scope(text, t)
        if guessed in ("pentest-record", "tutorial", "process"):
            meta["scope"] = guessed
    if not str(meta.get("status") or "").strip():
        meta["status"] = status or "active"
    if not str(meta.get("sensitivity") or "").strip() and sensitivity:
        meta["sensitivity"] = sensitivity

    resolve_actual_dates(meta, today, report)
    normalize_related(meta, report)

    # 合法性自检：解析不回来就说明写坏了（引号 / 冒号没处理）
    if meta:
        probe = dump_frontmatter(meta)
        if not parse_frontmatter(probe.strip("-\n")):
            _bump(report, "frontmatter_selfcheck_failed")
    return meta


# ---------------------------------------------------------------------------
# §11 敏感信息遮盖
# ---------------------------------------------------------------------------

_PLACEHOLDERISH = set("*•·xX-_.#~ ")


def _looks_credential(value: str) -> bool:
    """值的形态像不像一个真凭证

    宁可少遮，也不要把「密码已重置」这种句子遮掉 ——
    遮错了读者看不懂，遮漏了才要命。所以两头都要判：
    值必须是「token 形态」，不能是纯中文短语。
    """
    v = (value or "").strip().strip("`'\"*_，。；;")
    if len(v) < 3:
        return False
    if "secret-" in v or v.startswith("<"):
        return False
    if re.fullmatch(r"[\u4e00-\u9fff，。！？、；：（）]+", v):
        return False
    if not re.search(r"[A-Za-z0-9]", v):
        return False
    if set(v) <= _PLACEHOLDERISH:
        return False
    return True


_VAL_TAIL_RE = re.compile(r"^(.*?)([)\]）。，、；;!?！？\"']*)$", re.S)


def _mask_segment(seg: str, report: dict | None) -> str:
    def repl(m: re.Match) -> str:
        key, sep, val = m.group("key"), m.group("sep"), m.group("val")
        # 「值」里可能还挂着句尾标点/右括号：先剥掉，别把标点一起遮进密文里
        mm = _VAL_TAIL_RE.match(val)
        core, tail = (mm.group(1), mm.group(2)) if mm else (val, "")
        if not _looks_credential(core):
            return m.group(0)
        if report is not None:
            _bump(report, "secrets_masked")
        return f"{key}{sep}{_secret_span(core)}{tail}"

    return _INLINE_CRED_RE.sub(repl, seg)


_SECRET_SPAN_RE = re.compile(
    r'<span class="secret-toggle"[^>]*>\s*<span class="secret-mask">.*?</span>\s*'
    r'<span class="secret-value">(.*?)</span>\s*</span>',
    re.S,
)


def unmask_secret_spans(text: str) -> str:
    """把遮盖标记还原成明文（代码块里必须这么干）

    遮盖是给「正文/表格」用的；一旦这段内容变成了代码块，
    里面的 HTML 会被渲染器转义成一行源码 —— 既难看，又把口令的
    掩码结构暴露在代码里。代码块里要的是能直接跑的命令/原文。
    """
    return _SECRET_SPAN_RE.sub(lambda m: m.group(1), text)


def mask_inline_credentials(line: str, report: dict | None = None) -> str:
    """把一行里的「密码: xxx」换成 secret-toggle（§11）

    反引号里的内容是代码（`SET password=md5('...')`），遮了就不成命令了 ——
    按反引号切片，只处理代码之外的段落。
    """
    if _SECRET_MARK in line:
        return line
    parts = line.split("`")
    for idx in range(0, len(parts), 2):
        if parts[idx]:
            parts[idx] = _mask_segment(parts[idx], report)
    return "`".join(parts)


def mask_credentials(text: str, report: dict | None = None) -> str:
    """整篇文档的凭证遮盖（代码块跳过 —— 遮了命令就跑不动了）"""
    lines = text.split("\n")
    in_code = False
    for i, ln in enumerate(lines):
        if _FENCE_RE.match(ln):
            in_code = not in_code
            continue
        if in_code or not ln.strip():
            continue
        lines[i] = mask_inline_credentials(ln, report)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# §5 表格
# ---------------------------------------------------------------------------

def _emit_tsv_table(header: list[str], rows: list[list[str]]) -> list[str]:
    """把制表符分隔的几行渲染成 Markdown 表格

    从聊天界面整段复制时，表格会掉成 `目标\t卡点\t已排除` 这种 TSV，
    直接留在正文里就是一行挤在一起的乱码。
    """
    header = [c.strip() or "—" for c in header]
    width = len(header)
    norm_rows = []
    for r in rows:
        cells = [c.strip() for c in r]
        if len(cells) < width:
            cells += [""] * (width - len(cells))
        norm_rows.append(cells[:width])
    out = ["| " + " | ".join(f"**{c.replace('|', chr(92) + '|')}**" for c in header) + " |"]
    out.append("|" + "|".join(":---" for _ in header) + "|")
    for cells in norm_rows:
        out.append("| " + " | ".join(c.replace("|", chr(92) + "|") or " " for c in cells) + " |")
    return out


def _format_table(rows: list[str], *, report: dict | None = None,
                  mask_secrets: bool = True) -> list[str]:
    """表格美化：表头加粗、状态值配 emoji、凭证列遮盖（§5 / §11）"""
    if len(rows) < 2:
        return rows
    report = report if report is not None else {}
    header = rows[0].strip().strip("|").split("|")
    sep = rows[1]
    body = rows[2:]

    def cell(raw: str) -> str:
        return raw.strip()

    # 表头加粗（已经加粗过的不再套一层 —— 否则每排一次就多一对星号）
    def bold(h: str) -> str:
        v = cell(h)
        if v.startswith("**") and v.endswith("**"):
            return v
        return f"**{v}**"

    new_header = "| " + " | ".join(bold(h) for h in header) + " |"
    if new_header.strip() != rows[0].strip():
        _bump(report, "table_header_bold")

    # 「口令 / 密码 / token」列 → 整列遮盖（§11）
    cred_cols = [
        idx for idx, h in enumerate(header)
        if mask_secrets and _CRED_KEY_RE.search(_strip_emoji(cell(h)))
    ]

    def emoji_cell(v: str) -> str:
        # 只在整格正好是状态词时才加；含其它文字的不动
        for word, em in STATUS_EMOJI:
            if v == word:
                return f"{em} {v}"
        return v

    new_body = []
    for r in body:
        cells = r.strip().strip("|").split("|")
        out_cells = []
        for idx, c in enumerate(cells):
            v = emoji_cell(cell(c))
            if idx in cred_cols and v and "secret-" not in v and _looks_credential(v):
                v = _secret_span(v.strip("`"))
                _bump(report, "secrets_masked")
            out_cells.append(v)
        # 注意：加 emoji 时要加在**单元格内部**，
        # 不能把「状态」换成「✅」再分成两列 —— 那表格的列数就乱了
        line = "| " + " | ".join(out_cells) + " |"
        if line != r:
            _bump(report, "table_cells_normalized")
        new_body.append(line)
    return [new_header, sep] + new_body


# ---------------------------------------------------------------------------
# §4 目录
# ---------------------------------------------------------------------------

def _anchor(heading: str) -> str:
    """标题 → Obsidian 锚点（去 emoji、去标点、空格换 -）"""
    s = _strip_emoji(heading)
    s = re.sub(r"[`*_~\[\](){}<>|]", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s.lower()


def build_toc(lines: list[str]) -> list[str]:
    """按正文里的 H2/H3 生成目录（§4）"""
    items: list[str] = []
    for ln in lines:
        if _TOC_HEAD_RE.match(ln):
            continue
        m = _HEADING_RE.match(ln)
        if not m:
            continue
        level = len(m.group(1))
        if level not in (2, 3):
            continue
        title = m.group(2).strip()
        plain = _strip_emoji(title)
        if not plain:
            continue
        num = re.match(r"^(\d+(?:\.\d+)?)\.?\s+(.*)$", plain)
        if num:
            label = f"§{num.group(1)} {num.group(2)}" if level == 2 else f"{num.group(1)} {num.group(2)}"
        else:
            label = plain
        indent = "  " if level == 3 else ""
        items.append(f"{indent}- [{label}](#{_anchor(title)})")
    return items


def _first_paragraph(md: str) -> str:
    """取第一段正文（跳过 frontmatter、标题、callout、列表、表格）"""
    lines = md.split("\n")
    buf: list[str] = []
    started = False
    for ln in lines:
        s = ln.strip()
        if s == "---" and not started:
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


# ---------------------------------------------------------------------------
# 正文格式化
# ---------------------------------------------------------------------------

def _command_run(lines: list[str], i: int) -> int:
    """从第 i 行起，连续几行是命令行？（返回行数，0 表示不是）"""
    raw0 = lines[i]
    if not (_CMD_LINE_RE.match(raw0) or _HTTP_LINE_RE.match(raw0)):
        return 0
    if _looks_like_code(raw0) and raw0.strip().startswith(("#", ">")):
        return 0
    n = 0
    while i + n < len(lines):
        ln = lines[i + n]
        if not ln.strip():
            break
        if _FENCE_RE.match(ln) or _HEADING_RE.match(ln) or _TASK_RE.match(ln):
            break
        if ln.strip().startswith((">", "|", "- ", "* ")):
            break
        if not (_CMD_LINE_RE.match(ln) or _HTTP_LINE_RE.match(ln)):
            break
        # 带中文的一律不当命令行 —— 中文正文里「ip」「id」「cat」开头的句子太多
        if re.search(r"[\u4e00-\u9fff]", ln):
            break
        n += 1
    # 单行也围栏的三种形态（复制终端输出最常见）：
    #   $ 提示符、带 URL 的请求、HTTP 动词 + 路径
    if n == 1:
        one = lines[i]
        if not (
            one.lstrip().startswith("$")
            or "://" in one
            or re.match(r"^\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+/\S", one)
        ):
            return 0
    return n


def _format_body(
    body: str,
    *,
    fence_commands: bool = True,
    mask_secrets: bool = True,
    scope: str = "",
    report: dict | None = None,
) -> str:
    """正文排版（结构部分）。敏感信息在最后统一处理，避免被结构搬运打散。"""
    report = report if report is not None else {}
    src = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = src.split("\n")
    out: list[str] = []
    i = 0
    seen_h1 = False
    non_empty = [l for l in lines if l.strip()]
    single_line_doc = len(non_empty) <= 2

    in_details = False
    current_h2 = ""
    while i < len(lines):
        line = lines[i]

        # ---- <details> 折叠块（§8.2）：整块放行 ----
        if re.match(r"^\s*<details\b", line, re.I):
            in_details = True
        if in_details:
            _ensure_blank(out) if re.match(r"^\s*<details\b", line, re.I) else None
            out.append(line.rstrip())
            if re.match(r"^\s*</details>", line, re.I):
                in_details = False
                out.append("")
            i += 1
            continue

        # ---- 聊天界面的状态噪音（16:06 / 用量 38.2M tok / +155 -0）→ 丢掉 ----
        if line.strip() and _NOISE_RE.match(line.strip()) and not _HEADING_RE.match(line):
            i += 1
            continue

        # ---- 复制粘贴掉了围栏：一行「代码块」+ 后面一段裸代码（§6.1）----
        # 聊天界面整段复制时，代码块会变成一行「代码块」，内容掉成普通段落。
        # 不还原的话，正文里全是一坨一坨等宽文本，代码块等于没有。
        if _CODE_MARKER_RE.match(line):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            block: list[str] = []
            k = j
            while k < len(lines) and lines[k].strip():
                ln = lines[k]
                if (_HEADING_RE.match(ln) or _CODE_MARKER_RE.match(ln)
                        or ln.lstrip().startswith(("```", "|", ">"))):
                    break
                block.append(unmask_secret_spans(ln).rstrip())
                k += 1
            # 后面其实是 TSV 表格 → 标记行丢掉，交给表格分支
            if sum(1 for b in block if "\t" in b) >= 2:
                i += 1
                continue
            if block:
                lang = _guess_lang(block) or "text"
                _ensure_blank(out)
                out.append(f"```{'bash' if lang in ('sh', 'shell') else lang}")
                out.extend(block)
                out.append("```")
                out.append("")
                i = k
                _bump(report, "code_block_restored")
                continue

        # ---- 制表符分隔的行 → 表格（§5）----
        if "\t" in line and not line.lstrip().startswith(("#", "|", ">", "-", "*")):
            tsv = []
            k = i
            while k < len(lines) and "\t" in lines[k] and lines[k].strip():
                tsv.append(lines[k].split("\t"))
                k += 1
            if len(tsv) >= 2:
                _ensure_blank(out)
                out.extend(_emit_tsv_table([c.strip() for c in tsv[0]], tsv[1:]))
                out.append("")
                i = k
                _bump(report, "tsv_table")
                continue

        # ---- 中文序号标题：一、xxx / 二、xxx（§1）----
        cn = _CN_HEADING_RE.match(line)
        if cn:
            title_cn = cn.group(2).strip()
            _ensure_blank(out)
            out.append(f"## {emoji_for_heading(title_cn)} {title_cn}".strip())
            out.append("")
            current_h2 = title_cn
            i += 1
            _bump(report, "cn_heading")
            continue

        # ---- 「单独一行语言标签 + 代码」→ 还原成代码块（§6.1）----
        label_run = _label_fence_run(lines, i)
        if label_run:
            lang, code = label_run
            _ensure_blank(out)
            out.append(f"```{'bash' if lang in ('sh', 'shell', 'console', 'zsh') else lang}")
            out.extend(ln.rstrip() for ln in code)
            out.append("```")
            out.append("")
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            i += len(code)
            _bump(report, "code_lang")
            continue

        # ---- 代码块：补语言标识（§6.1）----
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0] * 3
            lang = fence.group(2)
            body_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                body_lines.append(unmask_secret_spans(lines[i]))
                i += 1
            i += 1  # 跳过收尾的 ```
            if not lang:
                lang = _guess_lang(body_lines)
                if lang:
                    _bump(report, "code_lang")
            _ensure_blank(out)
            out.append(f"```{lang}")
            out.extend(body_lines)
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
            _ensure_blank(out)
            out.extend(_format_table(rows, report=report, mask_secrets=mask_secrets))
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
            _ensure_blank(out)
            if callout:
                ctype = callout.group(1).lower()
                fold = callout.group(2)
                ctitle = callout.group(3).strip()
                rest = "\n".join(joined.split("\n")[1:]).strip()
                head = f"> [!{ctype}]{fold}" + (f" {ctitle}" if ctitle else "")
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
            _bump(report, "quote_to_callout")
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
                _ensure_blank(out)
                plain = _strip_emoji(title_txt)
                new_h1 = f"# {emoji_for_title(plain, scope)} {_short_h1(plain)}".strip()
                if new_h1 != line.strip():
                    _bump(report, "h1_emoji")
                out.append(new_h1)
            elif level == 2:
                plain = _strip_emoji(re.sub(r"^\d+\.\s*", "", _strip_emoji(title_txt)))

                # 标题是「代码块」→ 这一节其实就是一段裸代码，把正文还原成围栏
                if _CODE_MARKER_RE.match(plain):
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    block: list[str] = []
                    k = j
                    while k < len(lines) and lines[k].strip():
                        ln = lines[k]
                        if (_HEADING_RE.match(ln) or _CODE_MARKER_RE.match(ln)
                                or ln.lstrip().startswith(("```", "|", ">"))):
                            break
                        block.append(unmask_secret_spans(ln).rstrip())
                        k += 1
                    # 正文已经是围栏代码块了 → 这个标题纯属多余，删掉即可
                    if not block and k < len(lines) and lines[k].lstrip().startswith("```"):
                        i = k
                        continue
                    if block and sum(1 for b in block if "\t" in b) < 2:
                        lang = _guess_lang(block) or "text"
                        _ensure_blank(out)
                        out.append(f"```{'bash' if lang in ('sh', 'shell') else lang}")
                        out.extend(block)
                        out.append("```")
                        out.append("")
                        i = k
                        _bump(report, "code_block_restored")
                        continue

                # 标题里带制表符 → 表头被复制成了标题
                if "\t" in title_txt:
                    header = [c.strip() for c in title_txt.split("\t") if c.strip()]
                    if header:
                        header[0] = re.sub(r"^\d+\.\s*", "", _strip_emoji(header[0])).strip()
                    rows: list[list[str]] = []
                    k = i + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    while k < len(lines) and "\t" in lines[k] and lines[k].strip():
                        rows.append([c.strip() for c in lines[k].split("\t")])
                        k += 1
                    if len(header) >= 2 and rows:
                        _ensure_blank(out)
                        out.extend(_emit_tsv_table(header, rows))
                        out.append("")
                        i = k
                        _bump(report, "tsv_table")
                        continue

                # 聊天界面的状态条（用量 38.2M tok / 16:06 / 已完成 / 继续挖）
                # 「只有标题、下面没有内容」的一律当噪音丢掉，别进目录
                if _NOISE_RE.match(plain) or plain in _EMPTY_NOISE_WORDS:
                    nxt = ""
                    for k in range(i + 1, len(lines)):
                        if lines[k].strip():
                            nxt = lines[k].strip()
                            break
                    if (not nxt or _HEADING_RE.match(nxt)
                            or _NOISE_RE.match(nxt) or nxt in _EMPTY_NOISE_WORDS):
                        i += 1
                        continue

                if plain.lower() in _LANGS and not re.search(r"[\u4e00-\u9fff]", plain):
                    # `## xml` + 紧跟代码 → 这是丢了围栏的代码块，不是章节
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines) and _looks_code_line(lines[j]):
                        k = j
                        while k < len(lines) and lines[k].strip() and not lines[k].lstrip().startswith(
                                ("#", ">", "|", "- ", "* ", "```")):
                            if k > j and _is_prose(lines[k]):
                                break
                            k += 1
                        _ensure_blank(out)
                        out.append(f"```{'bash' if plain.lower() in ('sh', 'shell') else plain.lower()}")
                        out.extend(ln.rstrip() for ln in lines[j:k])
                        out.append("```")
                        out.append("")
                        i = k
                        _bump(report, "code_lang")
                        continue
                _ensure_blank(out)
                if not plain:
                    i += 1
                    continue
                # 标题输出：保留原 emoji，去掉旧编号与中文序号（编号由 _number_sections 统一重排）
                em0 = _EMOJI_RE.match(title_txt)
                emoji0 = em0.group(0).strip() if em0 else ""
                body0 = _strip_emoji(title_txt)
                body0 = re.sub(r"^\d+\.\s*", "", body0).strip()
                body0 = re.sub(r"^[一二三四五六七八九十]{1,3}[、.．]\s*", "", body0).strip()
                title_out = (f"{emoji0} {body0}".strip() or title_txt)
                already = _EMOJI_RE.match(title_out)
                if already:
                    out.append(f"## {title_out}")
                    current_h2 = plain
                else:
                    out.append(f"## {emoji_for_heading(title_out)} {title_out}")
                    current_h2 = plain
                    _bump(report, "h2_emoji")
            elif level == 3:
                _ensure_blank(out)
                out.append(f"### {title_txt}")
            else:
                out.append(line.rstrip())
            out.append("")
            i += 1
            continue

        # ---- 分割线（§8.1）：前后空一行 ----
        if _HR_RE.match(line):
            # 只统计「原来没留白」的：已经排好的分割线不该反复上报
            prev_blank = (not out) or out[-1] == ""
            next_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
            if out and out[-1] != "":
                out.append("")
            out.append("---")
            out.append("")
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if not (prev_blank and next_blank):
                _bump(report, "hr_spacing")
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

        # ---- 风险条目 → callout（§3）----
        # 「C2 严重 —— 图形验证码明文下发」这种行，本质是一条**发现**，
        # 摊在正文里读者扫不到；改成 danger/warning 卡片，和参考样板一个形态。
        risk = _RISK_RE.match(line)
        if risk and len((risk.group(3) or "").strip()) >= 2:
            sev = (risk.group(2) or "").lower()
            kind = ("danger" if sev in _SEV_DANGER
                    else "warning" if sev in _SEV_WARN else "note")
            detail: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j].strip():
                ln = lines[j]
                if (ln.lstrip().startswith(("#", ">", "|", "- ", "* ", "```"))
                        or _RISK_RE.match(ln)):
                    break
                detail.append(ln.strip())
                j += 1
            _ensure_blank(out)
            out.append(f"> [!{kind}] {line.strip()}")
            for d in detail:
                out.append(f"> {d}")
            out.append("")
            i = j
            _bump(report, "risk_callout")
            continue

        # ---- 修复建议 → 待办清单（§8.3）----
        # 在「修复 / 建议 / 措施 / P0」这类章节里，连着两行以上的纯文本条目
        # 就是待办项；用 - [ ] 列出来，比一段一段散文更容易勾。
        if current_h2 and _FIX_SECTION_RE.search(current_h2) and line.strip():
            if not line.lstrip().startswith(("#", ">", "|", "- ", "* ", "`", "$")):
                items: list[str] = []
                j = i
                while j < len(lines) and lines[j].strip():
                    ln = lines[j]
                    if ln.lstrip().startswith(("#", ">", "|", "- ", "* ", "`", "$")):
                        break
                    if _CMD_LINE_RE.match(ln) or _HTTP_LINE_RE.match(ln):
                        break
                    items.append(ln.strip())
                    j += 1
                if len(items) >= 2:
                    _ensure_blank(out)
                    for it in items:
                        it = re.sub(r"^(?:\d+[.)]|[①-⑩])\s*", "", it)
                        out.append(f"- [ ] {it}")
                    out.append("")
                    i = j
                    _bump(report, "fix_checklist")
                    continue

        # ---- 连续命令行 → bash 代码块（§6.1）----
        if fence_commands:
            n = _command_run(lines, i)
            if n:
                _ensure_blank(out)
                out.append("```bash")
                out.extend(lines[i:i + n])
                out.append("```")
                out.append("")
                i += n
                _bump(report, "commands_fenced")
                continue

        # ---- 裸标题 ----
        # 「背景」「部署」这种独占一行、后面不跟内容的短行，
        # 明显是标题（作者手写时忘了打 #）—— 提升成 H2 并配 emoji。
        # 判据：短（<= 12 字）、不含句号标点、下一行是空行或正文。
        # 单行笔记（整篇就一两句）不做提升：那多半是标题本身或一句话记录。
        stripped = line.strip()
        if (
            stripped
            and not single_line_doc
            and len(stripped) <= 12
            and not stripped.startswith(('#', '>', '|', '-', '*', '`', '='))
            and not re.match(r"^\d+[.)]\s", stripped)
            and not stripped.startswith("<")
            and "\t" not in line
            and not _CODE_MARKER_RE.match(stripped)
            and not _NOISE_RE.match(stripped)
            and stripped not in _EMPTY_NOISE_WORDS
            # 纯 ASCII 的短词多半是语言标签 / 字段名（xml、bash、json、curl…），
            # 不是章节标题。之前把「xml」「bash」提升成了 ## 📌 xml，很难看。
            and (re.search(r"[\u4e00-\u9fff]", stripped) is not None
                 or len(stripped) > 12)
            and not stripped.endswith(('。', '，', '.', ',', '；', ';', '：', ':', '！', '!', '？', '?'))
            and not _looks_like_code(stripped)
        ):
            # 找下一行「有内容」的行：标题后面必须真有一节内容，
            # 跟着的又是一条标题/引用/表格/代码 → 那这一行不是标题，
            # 而是上一段漏出来的残句（之前把「正文0」「xml」都提升成 H2 了）
            nxt = ""
            for k in range(i + 1, len(lines)):
                if lines[k].strip():
                    nxt = lines[k].strip()
                    break
            looks_like_heading = bool(nxt) and not nxt.startswith(
                ('#', '>', '|', '-', '*', '`', '<')
            )
            if looks_like_heading and stripped:
                out.append(f"## {emoji_for_heading(stripped)} {stripped}")
                out.append("")
                i += 1
                _bump(report, "bare_heading")
                continue

        out.append(line.rstrip())
        i += 1

    # ---- 段落密度：一句话一段的松散排版 → 合并；空章节 → 删掉 ----
    out, merged = _merge_short_paragraphs(out)
    out, dropped = _drop_empty_sections(out)
    if merged:
        _bump(report, "paragraphs_merged", merged)
    if dropped:
        _bump(report, "empty_sections_dropped", dropped)

    # ---- 收拾尾部空行 ----
    while out and out[-1] == "":
        out.pop()
    text = "\n".join(out).strip()

    if mask_secrets:
        text = mask_credentials(text, report)

    return text


# ---------------------------------------------------------------------------
# 顶部块（摘要 / 元信息 / 目录）
# ---------------------------------------------------------------------------

def _merge_short_paragraphs(lines: list[str], *, limit: int = 260) -> tuple[list[str], int]:
    """把一连串「一句话一段」合并成一段（保留换行，只去掉段间空行）

    从聊天界面整段复制出来的正文，最典型的样子是：

        先测试后台页面。
        （空行）
        后台是 web.php/admin/... 需要登录。
        （空行）
        让我用 curl 测试一下能否直接访问。

    渲染出来就是一大片「每句之间隔一屏」的松散段落，读起来非常散 ——
    用户说的「段落太丑、没有样式性」多半是这个。

    合并规则（保守）：
      · 以「段落块」为单位（连续非空行为一块），只合并纯文本块
      · 两块单独都不超过 140 字，合起来不超过 260 字
      · 上一块最后一行不以「：」结尾（那是引导列表的冒号）
      · 中间必须恰好一个空行；遇到结构块就停
    """
    def is_prose_line(ln: str) -> bool:
        t = ln.strip()
        if not t:
            return False
        if t.startswith(("#", ">", "|", "-", "*", "`", "<", "!")):
            return False
        if _HR_RE.match(t) or _TASK_RE.match(t):
            return False
        if _CMD_LINE_RE.match(t) or _HTTP_LINE_RE.match(t):
            return False
        return True

    def split_blocks(src: list[str]) -> list[list[str]]:
        blocks: list[list[str]] = []
        i = 0
        while i < len(src):
            if not src[i].strip():
                blocks.append([""])
                i += 1
                continue
            j = i
            while j < len(src) and src[j].strip():
                j += 1
            blocks.append(src[i:j])
            i = j
        return blocks

    def block_chars(b: list[str]) -> int:
        return sum(len(x.strip()) for x in b if x.strip())

    def is_prose_block(b: list[str]) -> bool:
        return bool(b) and all(is_prose_line(x) for x in b)

    blocks = split_blocks(lines)
    out: list[list[str]] = []
    merged = 0
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if is_prose_block(cur) and block_chars(cur) <= 140:
            while i + 2 < len(blocks) and blocks[i + 1] == [""] and is_prose_block(blocks[i + 2]):
                nxt = blocks[i + 2]
                if block_chars(nxt) > 140:
                    break
                if block_chars(cur) + block_chars(nxt) > limit:
                    break
                if cur[-1].strip().endswith(("：", ":")):
                    break
                cur = cur + nxt
                i += 2
                merged += 1
        out.append(cur)
        i += 1

    flat: list[str] = []
    for b in out:
        flat.extend(b)
    return flat, merged


def _drop_empty_sections(lines: list[str]) -> tuple[list[str], int]:
    """删掉「只有标题、下面什么都没有」的空章节

    从聊天里复制时，`## 恢复默认配置` 这种标题常常和正文错位 ——
    标题在上一段、正文在下一段，渲染出来就是连续几个空章节，
    目录里也全是空壳。空章节没有信息量，删掉比留着干净。
    """
    out: list[str] = []
    dropped = 0
    i = 0
    n = len(lines)
    while i < n:
        m = _HEADING_RE.match(lines[i])
        if m and len(m.group(1)) >= 2:
            j = i + 1
            body_len = 0
            has_child = False
            while j < n:
                if _HEADING_RE.match(lines[j]):
                    lvl = len(_HEADING_RE.match(lines[j]).group(1))
                    if lvl <= len(m.group(1)):
                        break
                    has_child = True
                elif lines[j].strip():
                    body_len += len(lines[j].strip())
                j += 1
            if body_len == 0 and not has_child:
                dropped += 1
                i = j
                continue
        out.append(lines[i])
        i += 1
    return out, dropped


def _strip_generated_blocks(
    lines: list[str], *, strip_meta: bool = True, strip_toc: bool = True,
    strip_abstract: bool = False,
) -> list[str]:
    """拆掉「派生块」（元信息卡 / 目录）—— 它们由 front-matter 和标题推导，
    每次重建一遍才会跟着变；幂等靠的就是「拆干净再重建」。

    摘要块**不动**：那是人写的（或第一次排版时生成的），
    规则再生成一次只会把用户的话换成一句更差的复述。
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if (strip_meta and _META_HEAD_RE.match(ln)) or (
                strip_abstract and _ABSTRACT_HEAD_RE.match(ln)):
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                i += 1
            # 顺手吃掉紧跟的一个空行，避免空行越积越多
            if i < len(lines) and not lines[i].strip():
                i += 1
            continue
        if strip_toc and _TOC_HEAD_RE.match(ln):
            i += 1
            while i < len(lines) and (not lines[i].strip() or re.match(r"^\s*-\s+", lines[i])):
                i += 1
            continue
        out.append(ln)
        i += 1
    return out


# ---------------------------------------------------------------------------
# 语义要素（规则能判的那部分）
#
# 参考样板：一篇「⚔️ 云海18001 全链路复现」的渗透记录，除了排版之外，
# 还有一些**要素**是格式撑不起来的：它得知道「这篇是什么、涉及谁、多敏感、
# 和哪几篇是同一系列」。规则判不准全部，但下面这几件事判得八九不离十：
#   · 敏感度（有凭证 + 有真实地址 → secret）
#   · 目标（IP / 域名 / 端口）
#   · 章节编号（§N / N.M）
#   · 相关笔记（按标题/标签/正文关键词匹配现有笔记）
#   · 变更日志
# 判不准的部分（真正的 TL;DR、因果叙述、风险分级）留给模型，见 AI 增强接口。
# ---------------------------------------------------------------------------

_CRED_HINT_RE = re.compile(
    r"(密码|口令|密钥|私钥|凭据|凭证|令牌|哈希|散列|弱口令|"
    r"\b(?:pass|password|passwd|pwd|token|secret|api[_-]?key|apikey|"
    r"access[_-]?key|private[_-]?key|secret[_-]?key|cookie|cookies|ck|"
    r"session[_-]?id|bearer)\b)",
    re.I,
)
_ATTACK_HINT_RE = re.compile(
    r"(渗透|攻击|提权|getshell|rce|webshell|漏洞|未授权|越权|绕过|注入|"
    r"弱口令|爆破|横向|拿下|后台|上传|反弹|data\s*export|exfil)",
    re.I,
)
_CONFIDENTIAL_HINT_RE = re.compile(
    r"(客户|合同|报价|薪资|工资|财务|发票|报销|身份证|手机号|内部|保密|"
    r"confidential|internal\s+only)",
    re.I,
)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TLD = r"(?:com|net|org|cn|io|top|xyz|site|info|me|co|cc|tv|vip|club|shop|app|dev|ai|local)"
_DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+" + _TLD + r"(?::\d{2,5})?\b",
    re.I,
)
_PORT_RE = re.compile(r"(?:端口|port)\s*[:：]?\s*(\d{2,5})\b", re.I)
_HOST_PORT_RE = re.compile(
    r"(?:(?:\d{1,3}\.){3}\d{1,3}|[a-z0-9][a-z0-9.-]*\." + _TLD + r")\s*:\s*(\d{2,5})\b",
    re.I,
)


def infer_sensitivity(text: str) -> str:
    """猜敏感度（§2 sensitivity）：secret / confidential / public

    判据刻意保守 —— 标成 secret 只是多一行提醒，标错成 public 才是真出事。
    所以只要有「凭证词 + 真地址」就按 secret 处理。
    """
    body = text or ""
    cred = len(_CRED_HINT_RE.findall(body))
    attack = bool(_ATTACK_HINT_RE.search(body))
    addr = bool(_IP_RE.search(body) or _DOMAIN_RE.search(body))
    if cred and (addr or attack):
        return "secret"
    if cred >= 3 or (attack and addr):
        return "secret"
    if cred or _CONFIDENTIAL_HINT_RE.search(body):
        return "confidential"
    return "public"


def extract_targets(text: str) -> dict:
    """从正文里抽目标：IP / 域名 / 端口

    只做「提到过什么」，不做「哪个是主要目标」—— 那是人的判断。
    去重排序，最多各 8 个，免得元信息卡被一串 IP 撑爆。
    """
    body = text or ""
    ips = []
    for ip in _IP_RE.findall(body):
        if ip not in ips:
            ips.append(ip)
    domains = []
    for d in _DOMAIN_RE.findall(body):
        d = d.strip().lower()
        if d not in domains:
            domains.append(d)
    ports = []
    for p in _PORT_RE.findall(body) + _HOST_PORT_RE.findall(body):
        if p not in ports:
            ports.append(p)
    return {
        "ips": ips[:8],
        "domains": domains[:8],
        "ports": ports[:8],
    }


TAG_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("渗透", "漏洞", "getshell", "提权", "webshell", "rce"), "pentest"),
    (("排障", "故障", "502", "超时", "异常"), "troubleshooting"),
    (("部署", "上线", "docker", "nginx", "镜像"), "ops"),
    (("数据库", "mysql", "sqlite", "redis", "sql"), "database"),
    (("前端", "vue", "css", "ui", "页面"), "frontend"),
    (("接口", "api", "http", "鉴权", "token"), "api"),
    (("会议", "纪要"), "meeting"),
    (("复盘", "总结"), "retro"),
]


def suggest_tags(text: str, limit: int = 4) -> list[str]:
    """按内容给几个「域标签」（只在用户没写标签时兜底）"""
    blob = (text or "").lower()
    out: list[str] = []
    for keys, tag in TAG_HINTS:
        hit = False
        for k in keys:
            kl = k.lower()
            if re.fullmatch(r"[a-z0-9_+-]+", kl):
                if re.search(r"(?<![a-z0-9])" + re.escape(kl) + r"(?![a-z0-9])", blob):
                    hit = True
                    break
            elif kl in blob:
                hit = True
                break
        if hit and tag not in out:
            out.append(tag)
    return out[:limit]


_GENERATED_H2_RE = re.compile(
    r"^##\s+.*(?:风险清单|目标与结果|时间线|相关|变更日志)\s*$"
)


def core_text(text: str) -> str:
    """取出「作者写的那部分」正文（去掉 front-matter、生成块、callout）

    用途：相关笔记打分。排版过的笔记比原文多出摘要、元信息卡、风险表、目录……
    直接拿全文打分，第二遍排版就会算出另一批「相关笔记」—— 于是 related 变了，
    笔记也跟着变（不幂等）。打分只认作者原话，结果才稳定。
    """
    _fm, body = split_frontmatter(text or "")
    lines = body.split("\n")
    out: list[str] = []
    skip = False
    for ln in lines:
        if _TOC_HEAD_RE.match(ln) or _GENERATED_H2_RE.match(ln):
            skip = True
            continue
        if skip:
            if re.match(r"^##\s+", ln) and not _GENERATED_H2_RE.match(ln):
                skip = False
            else:
                continue
        if ln.lstrip().startswith(">"):
            continue
        out.append(ln)
    return "\n".join(out)


def element_audit(text: str) -> list[dict]:
    """要素体检：这篇笔记「该有的东西」有没有

    前端把它画成一张对勾表 —— 用户一眼能看到还缺什么，
    而不是「感觉没那味儿」但说不清缺哪一块。
    """
    body = text or ""
    has_fm = body.lstrip().startswith("---")
    fm = parse_frontmatter(split_frontmatter(body)[0]) if has_fm else {}
    h1 = re.search(r"^#\s+", body, re.M)
    h1_emoji = bool(re.search(r"^#\s+" + _EMOJI_RE.pattern.strip("^") + "", body, re.M)) if h1 else False
    checks = [
        ("frontmatter", "§2", "front-matter", has_fm),
        ("fields", "§2", "必填字段（title/tags/created/source）",
         all(str(fm.get(k) or "").strip() for k in ("title", "created", "source")) and "tags" in fm),
        ("enhanced", "§2", "增强字段（updated/version/scope/status/sensitivity）",
         all(k in fm for k in ("updated", "version", "scope", "status", "sensitivity"))),
        ("related", "§2.1", "related 关联笔记", bool(fm.get("related"))),
        ("h1", "§1", "H1 带语义 emoji", h1_emoji),
        ("numbered", "§1", "章节编号（§N / N.M）", bool(re.search(r"^##\s+\S+\s+\d+\.\s", body, re.M))),
        ("abstract", "§3.2", "顶部摘要卡", "[!abstract]" in body),
        ("meta_card", "§3.2", "元信息卡", "[!info] 元信息" in body),
        ("toc", "§4", "目录", "## 📑 目录" in body),
        ("table", "§5", "表格", bool(re.search(r"^\|.*\|\s*$", body, re.M))),
        ("code_lang", "§6.1", "代码块带语言", bool(re.search(r"^```[a-zA-Z]", body, re.M))),
        ("callout", "§3", "callout（> [!type]）", bool(re.search(r"^>\s*\[!\w+\]", body, re.M))),
        ("secrets", "§11", "凭证遮盖", "secret-toggle" in body),
        ("changelog", "§10", "变更日志", "变更日志" in body),
        ("related_section", "§10", "相关链接区", bool(re.search(r"^##\s+\S*相关", body, re.M))),
        ("divider", "§8.1", "分隔线", bool(re.search(r"^---\s*$", body.replace("\ufeff", ""), re.M))),
    ]
    return [
        {"id": i, "section": sec, "name": name, "present": bool(ok)}
        for i, sec, name, ok in checks
    ]


def _meta_card_lines(meta: dict, facts: dict | None = None) -> list[str]:
    """§3.2 顶部元信息卡（从 front-matter 派生，别让人手抄）

    排布比规范里的「一行一个字段」更紧凑：创建/更新合成一行，
    来源/类型/状态/敏感度/版本合成一行 —— 参考样板就 6 行。
    11 行的元信息卡会把正文顶出屏幕，那是把规范读死了。
    """
    labels = {
        "human": "👤 人工", "agent": "🤖 Agent", "hybrid": "🤝 人机",
        "draft": "📝 草稿", "active": "✅ 生效", "deprecated": "🚫 废弃",
        "archived": "📦 归档", "secret": "🔴 SECRET",
        "confidential": "🟠 机密", "public": "🟢 公开",
        "log": "🗒️ 记录", "tutorial": "📖 教程", "process": "🔧 流程",
        "concept": "💡 概念", "project": "🗂️ 项目", "pentest-record": "⚔️ 渗透记录",
        "troubleshoot": "🧯 排障", "generic": "📌 通用",
    }
    rows: list[str] = []

    created = str(meta.get("created") or "").strip()
    updated = str(meta.get("updated") or "").strip()
    if created:
        line = f"📅 创建 {created}"
        if updated and updated != created:
            line += f" · 🔄 更新 {updated}"
        rows.append(f"> - **日期**: {line}")

    facts_line = []
    for key, name in (("source", "来源"), ("scope", "类型"),
                      ("status", "状态"), ("sensitivity", "敏感度"),
                      ("version", "版本")):
        val = meta.get(key)
        if val is None or str(val).strip() == "":
            continue
        shown = labels.get(str(val), str(val))
        facts_line.append(f"{name} {shown}")
    if facts_line:
        rows.append("> - " + " · ".join(facts_line))

    tg = (facts or {}).get("targets") or {}
    hosts = list(tg.get("ips") or []) + list(tg.get("domains") or [])
    ports = list(tg.get("ports") or [])
    if hosts:
        line = "> - **目标**: 🎯 " + " / ".join(f"`{h}`" for h in hosts[:6])
        if ports:
            line += " · 端口 " + ", ".join(f"`{p}`" for p in ports[:6])
        rows.append(line)

    tags = _as_list(meta.get("tags"))
    if tags:
        rows.append("> - **标签**: " + " ".join(f"#{t}" for t in tags))

    related = _as_list(meta.get("related"))
    if related:
        rows.append("> - **关联**: " + " ".join(
            f"[[{_strip_emoji(r)}]]" if not str(r).startswith("[[") else str(r)
            for r in related))

    if not rows:
        return []
    return ["> [!info] 元信息"] + rows


_CHANGELOG_H2_RE = re.compile(r"^##\s+.*变更日志")
_RELATED_H2_RE = re.compile(r"^##\s+.*相关\s*$")


def _number_sections(lines: list[str]) -> list[str]:
    """给章节编号（§N / N.M），参考样板那种「## 🎯 1. 目标与结果」

    编号是**派生**的：每次都把旧编号剥掉重新编号，
    中间插一节、删一节，后面的编号自动跟上 —— 不用人去改。
    """
    out: list[str] = []
    n = 0
    sub = 0
    for ln in lines:
        m = _HEADING_RE.match(ln)
        if m and len(m.group(1)) == 2:
            if _TOC_HEAD_RE.match(ln) or _CHANGELOG_H2_RE.match(ln):
                out.append(ln)
                continue
            n += 1
            sub = 0
            raw = m.group(2)
            em = _EMOJI_RE.match(raw)
            emoji = em.group(0).strip() if em else ""
            title = _strip_emoji(raw)
            title = re.sub(r"^\d+\.\s*", "", title).strip()
            title = re.sub(r"^[一二三四五六七八九十]{1,3}[、.．]\s*", "", title).strip()
            if not title:
                out.append(ln)
                continue
            emoji = emoji or emoji_for_heading(title)
            out.append(f"## {emoji} {n}. {title}".strip())
            continue
        if m and len(m.group(1)) == 3 and n:
            sub += 1
            raw = m.group(2)
            title = _strip_emoji(raw)
            title = re.sub(r"^\d+\.\d+\.?\s*", "", title).strip()
            out.append(f"### {n}.{sub} {title}".strip() if title else ln)
            continue
        out.append(ln)
    return out


def _append_tail_sections(
    lines: list[str], meta: dict, *, version: str = "1.0",
    today: str = "", enrich: bool = True, with_changelog: bool = True,
) -> list[str]:
    """正文尾部补齐「相关」和「变更日志」两块（§10）"""
    out = list(lines)
    related = _as_list(meta.get("related"))
    has_related = any(_RELATED_H2_RE.match(ln) for ln in out)
    if related and not has_related:
        out += ["", "---", "", "## 🔗 相关", ""]
        for r in related:
            name = str(r).strip()
            link = name if name.startswith("[[") else f"[[{_strip_emoji(name)}]]"
            out.append(f"- 📖 {link}")
    if enrich and with_changelog and not any(_CHANGELOG_H2_RE.match(ln) for ln in out):
        out += [
            "", "---", "", "## 📝 变更日志", "",
            "| **📅 日期** | **🔖 版本** | **📋 变更** |",
            "|:---|:---|:---|",
            f"| {today or date.today().isoformat()} | v{version} | 按《笔记 UI 排版规范》自动排版 |",
        ]
    return out


def _dedupe_sections(lines: list[str], head_re) -> list[str]:
    """同名章节只留第一份（历史上重复追加过的「相关」区要收掉）"""
    out: list[str] = []
    seen = False
    skipping = False
    for ln in lines:
        if head_re.match(ln):
            if seen:
                skipping = True
                continue
            seen = True
            skipping = False
            out.append(ln)
            continue
        if skipping:
            # 跳过整节（到下一个 H2 为止），把多余的分隔线也一起吃掉
            if re.match(r"^##\s+", ln):
                skipping = False
                out.append(ln)
            continue
        out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return out


def _banner_lines(sensitivity: str) -> list[str]:
    """敏感度横幅（§3）：secret → danger 横幅，confidential → warning"""
    if sensitivity == "secret":
        return [
            "> [!danger] 最高机密 (TOP SECRET)",
            "> 本文含真实地址、账号口令或可复现的攻击细节，**仅限内部使用**，不要外传。",
            "",
        ]
    if sensitivity == "confidential":
        return [
            "> [!warning] 内部资料",
            "> 含内部信息，转发前请确认接收范围。",
            "",
        ]
    return []


_BANNER_RE = re.compile(r"^>\s*\[!(?:danger|warning)\]\s*(?:最高机密|内部资料|机密)")
_SEV_EMOJI = {"严重": "🔴", "高": "🟠", "中": "🟡", "低": "🟢"}


def _structure_block(structure: dict, existing_titles: set[str]) -> list[str]:
    """把 AI 提取的事实渲染成「速览三块」：目标 / 风险 / 时间线"""
    if not structure:
        return []
    out: list[str] = []

    targets = structure.get("targets") or []
    if targets and not any("目标" in t for t in existing_titles):
        out += ["## 🎯 目标与结果", "",
                "| **🎯 资产** | **🔌 端口** | **📦 系统** | **✅ 结果** |",
                "|:---|:---|:---|:---|"]
        for t in targets:
            out.append("| " + " | ".join(
                (t.get(k) or "—").replace("|", "\\|")
                for k in ("name", "port", "stack", "result")) + " |")
        out.append("")

    risks = structure.get("risks") or []
    if risks and not any("风险" in t for t in existing_titles):
        out += ["## ⚠️ 风险清单", "",
                "| **🆔 编号** | **⚠️ 等级** | **📋 发现** | **🔍 证据** |",
                "|:---|:---|:---|:---|"]
        for r in risks:
            sev = (r.get("severity") or "").strip()
            sev_cell = f"{_SEV_EMOJI.get(sev, '⚪')} {sev}".strip()
            out.append("| " + " | ".join([
                f"**{(r.get('id') or '—')}**",
                sev_cell or "—",
                (r.get("title") or "—").replace("|", "\\|"),
                (r.get("evidence") or "—").replace("|", "\\|"),
            ]) + " |")
        out.append("")

    timeline = structure.get("timeline") or []
    if timeline and not any("时间线" in t for t in existing_titles):
        out += ["## ⏱️ 时间线", "",
                "| **🕐 时间** | **📌 事件** |",
                "|:---|:---|"]
        for e in timeline:
            out.append("| " + " | ".join([
                (e.get("time") or "—").replace("|", "\\|"),
                (e.get("event") or "—").replace("|", "\\|"),
            ]) + " |")
        out.append("")

    return out


def _short_h1(text: str, limit: int = 46) -> str:
    """H1 太长时截到一句话（标题字段不动，只影响正文标题）

    实测：从聊天里整段复制，首行常常是一整段结论（100+ 字）。
    原样当 H1，页面上就是一大块黑压压的标题，非常丑。
    """
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    for sep in ("：", "。", "；", "，", "—", " - "):
        idx = t.find(sep)
        if 0 < idx <= limit:
            return t[:idx].rstrip()
    return t[:limit].rstrip() + "…"


def _plain_excerpt(md: str, limit: int = 100) -> str:
    """把一段 Markdown 压成一句人话（摘要用）

    - 遮盖标记（secret-toggle）只留遮罩，不要把密文带进摘要
    - 去掉强调/代码/链接记号
    """
    s = str(md or "")
    s = re.sub(r'<span class="secret-toggle"[\s\S]*?</span>\s*</span>', '••••••', s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[\[([^\[\]]+?)\]\]", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[`*_~#>]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _summary_lines(remainder: list[str], title: str) -> list[str]:
    """§3.2 顶部摘要：第一句 + 覆盖了哪几节

    规则版写不出「概括」，但能写**事实**：
    这篇第一句说了什么、后面分了几节。重复标题或重复首段都不算摘要 ——
    宁可少写一行，也不要放一段读者已经看过的废话。
    """
    body = "\n".join(remainder)
    heads: list[str] = []
    for ln in remainder:
        m = _HEADING_RE.match(ln)
        if not m or len(m.group(1)) != 2:
            continue
        plain = _strip_emoji(m.group(2))
        # 生成块（目录/变更日志）和「相关」不是内容章节，不进覆盖清单
        if not plain or plain in ("目录",) or "变更日志" in plain or _RELATED_H2_RE.match(ln):
            continue
        plain = re.sub(r"^\d+\.\s*", "", plain).strip()
        if plain:
            heads.append(plain)
    parts: list[str] = []

    para = _first_paragraph(body)
    plain_title = _strip_emoji(title)
    # 一整段都是命令/URL 的话，不能拿来当 TL;DR（读者看不出这篇讲什么）
    if para and (_CMD_LINE_RE.match(para) or _HTTP_LINE_RE.match(para)
                 or para.lstrip().startswith("$")):
        para = ""
    if para:
        sentence = _plain_excerpt(para, 100)
        # 「非 PHP 文件明文返回（无 PHP 执行）：」这种半句话不是摘要
        if sentence.endswith(("：", ":")) or len(sentence) < 8:
            sentence = ""
        # 第一句就是标题本身（一句话笔记）→ 不重复
        if sentence and sentence.rstrip("。.…") != plain_title:
            parts.append(sentence)

    # 首段是半句话、标题本身却是一句结论时：取标题冒号后面那半句当 TL;DR
    # （标题的冒号前那截就是 H1，重复它没有意义）
    if not parts and len(plain_title) >= 20:
        seg = re.split(r"[：:]", plain_title, maxsplit=1)
        tail = seg[1].strip() if len(seg) > 1 and len(seg[1].strip()) >= 10 else ""
        cand = _short_h1(tail or plain_title, 80)
        if cand and cand != _short_h1(plain_title):
            parts.append(cand)

    if len(heads) >= 2:
        shown = " / ".join(heads[:6]) + (" / …" if len(heads) > 6 else "")
        parts.append(f"覆盖：{shown}")

    return ["> [!abstract] 摘要"] + [f"> {p}" for p in parts] if parts else []


def _assemble(
    body: str,
    *,
    meta: dict,
    title: str,
    add_summary: bool = True,
    toc: bool | None = None,
    meta_card: bool = True,
    facts: dict | None = None,
    structure: dict | None = None,
    version: str = "1.0",
    enrich: bool = True,
    today: str = "",
    report: dict | None = None,
) -> str:
    """把 H1 / 顶部 callout / 目录 / 分隔线 / 正文重新拼成一篇笔记"""
    report = report if report is not None else {}
    raw_lines = [ln.rstrip() for ln in body.split("\n")]
    # 这两块如果是我上次生成的，就可以跟着 front-matter 一起更新；
    # 用户自己手写的（没有我们的记号）一律保留原样。
    meta_is_ours = any(_META_OURS_RE.match(ln) for ln in raw_lines)
    abstract_is_ours = any(_ABSTRACT_OURS_RE.match(ln) for ln in raw_lines)

    # 先记下「这篇原来有没有生成块」—— 报告只统计**真的新增**的
    prior = {
        "abstract": any(_ABSTRACT_HEAD_RE.match(ln) for ln in raw_lines),
        "meta": any(_META_HEAD_RE.match(ln) for ln in raw_lines),
        "toc": any(_TOC_HEAD_RE.match(ln) for ln in raw_lines),
    }

    card = _meta_card_lines(meta, facts) if meta_card else []
    # 目录是**派生数据**：无条件拆掉，等正文（含结构块）定稿后再决定要不要重建。
    # 先拆后判，才不会「第一遍没目录、第二遍突然多一个」。
    lines = _strip_generated_blocks(
        raw_lines, strip_meta=bool(card) and meta_is_ours, strip_toc=True,
        strip_abstract=abstract_is_ours,
    )
    while lines and not lines[0].strip():
        lines.pop(0)

    # H1
    h1_idx = next((i for i, ln in enumerate(lines) if re.match(r"^#\s+", ln)), None)
    if h1_idx is None and title:
        title_line = (f"# {emoji_for_title(_strip_emoji(title), str(meta.get('scope') or ''))} "
                      f"{_short_h1(_strip_emoji(title))}").strip()
        head_line, rest = title_line, lines
    elif h1_idx is not None:
        head_line, rest = lines[h1_idx], lines[h1_idx + 1:]
    else:
        head_line, rest = "", lines

    # 顶部用户自己写的 callout（例如 `> [!danger] 最高机密`）要排在生成块前面
    user_top: list[str] = []
    j = 0
    while j < len(rest):
        if not rest[j].strip() or rest[j].startswith(">"):
            user_top.append(rest[j])
            j += 1
            continue
        if _HR_RE.match(rest[j]):
            # 用户拿分割线分块：保留内容、去掉线，稍后统一补
            j += 1
            continue
        break
    while user_top and not user_top[0].strip():
        user_top.pop(0)
    while user_top and not user_top[-1].strip():
        user_top.pop()
    remainder = rest[j:]
    while remainder and not remainder[0].strip():
        remainder.pop(0)
    while remainder and not remainder[-1].strip():
        remainder.pop()

    # 正文开头重复了一遍标题 → 删掉那一行（H1 已经写了）
    # 一句话笔记就是「删完没内容」，多段笔记则是「别再重复标题」
    if head_line and remainder:
        h1_plain = _strip_emoji(re.sub(r"^#\s+", "", head_line))
        first_real = next((k for k, ln in enumerate(remainder)
                           if ln.strip() and not _HR_RE.match(ln)), None)
        if first_real is not None:
            probe = remainder[first_real]
            hm = _HEADING_RE.match(probe)
            probe_plain = (_strip_emoji(hm.group(2)) if hm else _plain_excerpt(probe))
            probe_plain = re.sub(r"^\d+\.\s*", "", probe_plain).strip()
        title_full = _strip_emoji(title or "")
        dup = probe_plain == h1_plain
        if not dup and title_full and len(title_full) >= 6:
            dup = probe_plain.startswith(title_full[:20]) and len(probe_plain) <= len(title_full) + 20
        if (first_real is not None and dup):
            remainder.pop(first_real)
            while remainder and not remainder[0].strip():
                remainder.pop(0)
        meaningful = [ln for ln in remainder if ln.strip() and not _HR_RE.match(ln)]
        if not meaningful:
            remainder = []

    # AI 结构化出来的速览块（目标 / 风险 / 时间线）放在正文最前面
    if structure:
        existing_titles = {
            _strip_emoji(m.group(2))
            for m in (_HEADING_RE.match(ln) for ln in remainder)
            if m and len(m.group(1)) == 2
        }
        fast = _structure_block(structure, existing_titles)
        if fast:
            remainder = fast + [""] + remainder
            _bump(report, "structure_sections")

    # 尾部要素（相关 / 变更日志）先补上，编号才能把它们一起排进去
    remainder = _append_tail_sections(
        remainder, meta, version=version, today=today, enrich=enrich,
        # 变更日志是「制度」不是「装饰」：每篇都要能回答「谁改的、什么时候」，
        # 所以不再按长度挑（短笔记也加，就一行表）。
        with_changelog=True,
    )
    remainder = _dedupe_sections(remainder, _RELATED_H2_RE)

    # 章节编号（§N / N.M）—— 派生数据，每次重排
    remainder = _number_sections(remainder)

    h2_count = sum(1 for ln in remainder if re.match(r"^##\s+", ln))
    body_line_count = sum(1 for ln in remainder if ln.strip())
    # 目录门槛：正文 40 行以上、或者分了 4 节以上。
    # 规范原文写的是「>50 行或 H2≥5」，但那个「行」算的是含 front-matter 的整篇；
    # 这里 body_line_count 只数正文（不含摘要/元信息卡），门槛要相应下调，
    # 否则一篇 70 行的笔记反而不给目录（实测踩到过）。
    want_toc = toc if toc is not None else (body_line_count > 40 or h2_count >= 4)

    gen: list[str] = []

    # 敏感度横幅：secret / confidential 才加，且全文只加一次
    if enrich:
        banner = _banner_lines(str(meta.get("sensitivity") or ""))
        if banner and not any(_BANNER_RE.match(x) for x in user_top + raw_lines):
            gen.extend(banner)
            _bump(report, "banner_added")

    # §3.2 摘要：按规范放在「第一个 H2 之前」
    # 两行以内的笔记写 TL;DR 是耍流氓 —— 读者一眼就看完了
    tldr = [x for x in ((structure or {}).get("tldr") or []) if str(x).strip()]
    if (add_summary and (not prior["abstract"] or abstract_is_ours)
            and (body_line_count >= 4 or h2_count >= 2)):
        if tldr:
            summary = ["> [!abstract] 摘要"] + [f"> {x}" for x in tldr[:3]]
            gen.extend(summary + [""])
            if not prior["abstract"]:
                _bump(report, "abstract_added")
        else:
            summary = _summary_lines(remainder, title or _strip_emoji(head_line))
            if summary:
                gen.extend(summary + [""])
                _bump(report, "abstract_added")

    if card and (not prior["meta"] or meta_is_ours):
        gen.extend(card + [""])
        if not prior["meta"]:
            _bump(report, "meta_card")

    # §4 目录：>50 行 或 H2 ≥ 5 时才有必要
    if want_toc:
        toc_lines = build_toc(remainder)
        if toc_lines:
            gen.extend(["## 📑 目录", ""] + toc_lines + [""])
            _bump(report, "toc_added")

    out: list[str] = []
    if head_line:
        out.extend([head_line, ""])
    if user_top:
        out.extend(user_top + [""])
    if gen:
        out.extend(gen)
    if remainder:
        # 只有前面真的排了东西，才需要一条分隔线把「头部」和正文分开
        if head_line or user_top or gen:
            out.extend(["---", ""])
        out.extend(remainder)

    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n" if text else ""


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def format_note(
    text: str,
    *,
    title: str = "",
    tags: list[str] | None = None,
    add_summary: bool = True,
    frontmatter: bool | None = None,
    mask_secrets: bool = True,
    toc: bool | None = None,
    meta_card: bool = True,
    fence_commands: bool = True,
    source: str = "human",
    scope: str | None = None,
    status: str | None = None,
    sensitivity: str | None = None,
    today: str | None = None,
    enrich: bool = True,
    related: list[str] | None = None,
    force_related: bool = False,
    structure: dict | None = None,
    version: str = "1.0",
    report: dict | None = None,
) -> str:
    """把一段正文排成符合《笔记 UI 排版规范》的笔记。

    做的事情（都能在规范里对上号）：
      §1  H1/H2 标题补语义 emoji；保证全文只有一个 H1
      §2  front-matter 合并/补齐；related 规范化；日期落成实际值
      §3  引用块转成 Obsidian callout；顶部摘要 + 元信息卡
      §4  长笔记自动生成目录
      §5  表格表头加粗、状态值配 emoji
      §6  代码块补语言标识；连续命令行围栏成 bash
      §8  分割线前后留空行；任务列表统一 GitHub 风格
      §11 凭证自动遮盖

    要素层（`enrich=True`，参考样板里那些「格式撑不起来」的东西）：
      §2  敏感度判定（有凭证 + 有真地址 → secret）、标签兜底
      §3  敏感度横幅（secret → [!danger] 最高机密）
      §1  章节编号（1. / 1.1）
      §10 相关链接区、变更日志表

    `frontmatter=None` 是「自动」：原文已经有 front-matter、或者调用方
    给了标题（新建笔记的路径），才写 front-matter。
    纯正文的临时排版（AI 气泡里的「美化排版」）不会凭空加一堆属性。
    """
    if not text or not text.strip():
        return text or ""
    report = report if report is not None else {}
    today = today or date.today().isoformat()

    fm_text, body = split_frontmatter(text)
    meta = parse_frontmatter(fm_text) if fm_text else {}

    want_fm = frontmatter if frontmatter is not None else bool(fm_text or title)

    # 要素层：从正文里判敏感度 / 目标（front-matter 优先，没写才兜底）
    facts: dict = {}
    structure = structure or {}
    if enrich:
        facts = {
            "sensitivity": infer_sensitivity(body),
            "targets": extract_targets(body),
        }
        # 模型给的目标并进来：第一遍也要有「目标」这一行，
        # 否则第二遍从正文里再抽一次，元信息卡会突然多一行（不幂等）
        for t in (structure.get("targets") or []):
            name = str(t.get("name") or "").strip()
            port = str(t.get("port") or "").strip()
            if not name:
                continue
            tg = facts["targets"]
            bucket = "ips" if _IP_RE.fullmatch(name) else "domains"
            if name not in tg[bucket]:
                tg[bucket].append(name)
            if port and port not in tg["ports"]:
                tg["ports"].append(port)
        if want_fm:
            # 敏感度取「规则」和「模型」里更严的那个：
            # 模型偶尔会把带凭证的渗透记录判成 confidential，不能让它降级
            _rank = {"public": 0, "confidential": 1, "secret": 2}
            ai_sens = str(structure.get("sensitivity") or "").strip().lower()
            if ai_sens not in _rank:
                ai_sens = "public"
            rule_sens = facts["sensitivity"]
            strongest = max((ai_sens, rule_sens), key=lambda v: _rank[v])
            if not str(meta.get("sensitivity") or "").strip():
                meta["sensitivity"] = strongest
            if not _as_list(meta.get("tags")):
                auto = list(structure.get("tags") or []) or suggest_tags(body)
                if auto and not fm_text:
                    meta["tags"] = auto
            # 相关笔记只在「新建」或调用方显式要求时写入。
            # 已有 front-matter 的笔记不再自动加 —— 内容一改，打分就会变，
            # 每次都重算等于每次排版都改一次 related（不幂等）。
            if related and not meta.get("related") and (not fm_text or force_related):
                meta["related"] = [str(r) for r in related if str(r).strip()][:8]
    if want_fm:
        meta = ensure_frontmatter(
            meta, title=title, tags=tags, source=source,
            scope=scope, status=status, sensitivity=sensitivity,
            today=today, text=body, report=report,
        )
        if not fm_text:
            _bump(report, "frontmatter_added")
        # 正文里的 #标签 也并进 front-matter（Obsidian 里行内标签就是属性）
        inline = _inline_tags(body)
        if inline:
            tags_now = _as_list(meta.get("tags"))
            for t in inline:
                if t not in tags_now:
                    tags_now.append(t)
            if tags_now:
                meta["tags"] = tags_now

    formatted_body = _format_body(
        body, fence_commands=fence_commands, mask_secrets=mask_secrets,
        scope=str(meta.get("scope") or scope or ""), report=report,
    )

    result = _assemble(
        formatted_body,
        meta=meta,
        title=title or str(meta.get("title") or ""),
        add_summary=add_summary,
        toc=toc,
        meta_card=meta_card and want_fm,
        facts=facts,
        structure=structure,
        version=version,
        enrich=enrich,
        today=today,
        report=report,
    )

    if want_fm and meta:
        new_fm = dump_frontmatter(meta)
        if fm_text and new_fm != fm_text.strip():
            # 字段顺序 / 引号 / 日期被规范化过 —— 报告里要能看见
            _bump(report, "frontmatter_normalized")
        result = new_fm + "\n\n" + result
    return result


def format_note_with_report(text: str, **kwargs) -> tuple[str, dict]:
    """format_note 的带报告版本 —— 前端要拿「改了哪几处」给用户看"""
    report: dict = {}
    out = format_note(text, report=report, **kwargs)
    # 一字未改就把报告清空 —— 前端要能说「这篇已经很规范了」
    if out == text:
        report.clear()
    return out, report


# ---------------------------------------------------------------------------
# 保存时维护（人工编辑的真实痕迹）
# ---------------------------------------------------------------------------

def _fmt_version(v) -> str:
    try:
        return f"{float(v):.1f}"
    except Exception:
        return "1.0"


def _refresh_meta_card(lines: list[str], meta: dict) -> tuple[list[str], bool]:
    """元信息卡如果是我们生成的，就跟着 updated / version 一起刷新"""
    idx = next((i for i, ln in enumerate(lines) if _META_HEAD_RE.match(ln)), None)
    if idx is None:
        return lines, False
    is_ours = any(_META_OURS_RE.match(ln) for ln in lines[idx:idx + 3])
    if not is_ours:
        return lines, False
    end = idx + 1
    while end < len(lines) and lines[end].startswith(">"):
        end += 1
    card = _meta_card_lines(meta, {"targets": extract_targets("\n".join(lines))})
    if not card:
        return lines, False
    return lines[:idx] + card + lines[end:], True


def _sec_key(title: str) -> str:
    """章节标题归一：去 emoji、去编号、去标点 —— 用来跨版本对齐同一节"""
    t = _strip_emoji(title or "")
    t = re.sub(r"^\d+(?:\.\d+)?\.?\s*", "", t)
    t = re.sub(r"^[一二三四五六七八九十]{1,3}[、.．]\s*", "", t)
    return t.strip() or "（无标题）"


def _split_sections(body: str) -> dict[str, list[str]]:
    """按 H2 切段：{归一标题: 行列表}；第一个 H2 之前的内容归到「（开头）」"""
    secs: dict[str, list[str]] = {"（开头）": []}
    cur = "（开头）"
    for ln in (body or "").split("\n"):
        m = re.match(r"^##\s+(.*)$", ln)
        if m:
            cur = _sec_key(m.group(1))
            secs.setdefault(cur, [])
            continue
        secs.setdefault(cur, []).append(ln)
    return secs


def _good_snippet(line: str) -> bool:
    """这一行适合当「改动片段」吗（表格/代码围栏/分隔线不适合）"""
    t = (line or "").strip()
    if not t:
        return False
    if t.startswith(("|", "```", "~~~", "---", ">", "<")):
        return False
    if re.fullmatch(r"[\W_]+", t):
        return False
    return True


def _snippet(line: str, limit: int = 26) -> str:
    """把一行压成一句能看的片段（给变更日志用）"""
    t = line.strip()
    t = re.sub(r"^(?:[-*+]\s+|>\s*|\|\s*)", "", t)
    t = _strip_emoji(t)
    t = re.sub(r"[`*_~\[\]]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    return t[:limit] + ("…" if len(t) > limit else "")


def describe_change(old_content: str, new_content: str, *, limit: int = 140) -> str:
    """把「这次改了什么」写成一句人话（变更日志用）

    只写「+12 字符」等于没写 —— 过两周没人知道改了哪。这里做的是**结构级差异**：

        · 哪个字段变了（标题改名 / 标签增删）
        · 哪一节新增 / 删除
        · 哪一节改动最多，并带一句**原文片段**（第一处新增或删掉的行）
        · 每节的 +行/−行

    例：
        改「P0 修复」：生产环境关闭 auth.register（+6/−2）；新增「时间线」
    """
    ofm, obody = split_frontmatter(old_content or "")
    nfm, nbody = split_frontmatter(new_content or "")
    ometa = parse_frontmatter(ofm) if ofm else {}
    nmeta = parse_frontmatter(nfm) if nfm else {}

    parts: list[str] = []

    # ---- 字段级 ----
    ot, nt = str(ometa.get("title") or "").strip(), str(nmeta.get("title") or "").strip()
    if ot != nt and (ot or nt):
        parts.append(f"标题改为「{_snippet(nt or ot, 20)}」")
    otags, ntags = set(_as_list(ometa.get("tags"))), set(_as_list(nmeta.get("tags")))
    if otags != ntags:
        add, rem = sorted(ntags - otags), sorted(otags - ntags)
        bits = []
        if add:
            bits.append("+" + " ".join(f"#{t}" for t in add[:3]))
        if rem:
            bits.append("−" + " ".join(f"#{t}" for t in rem[:3]))
        parts.append("标签 " + " ".join(bits))
    for key, label in (("sensitivity", "敏感度"), ("status", "状态"), ("scope", "类型")):
        ov, nv = str(ometa.get(key) or ""), str(nmeta.get(key) or "")
        if ov != nv and (ov or nv):
            parts.append(f"{label} {ov or '空'} → {nv or '空'}")

    # ---- 章节级 ----
    osec, nsec = _split_sections(obody), _split_sections(nbody)
    added = [k for k in nsec if k not in osec]
    removed = [k for k in osec if k not in nsec]
    changed = []
    import difflib as _dl

    for k in nsec:
        if k not in osec:
            continue
        a = [x for x in osec[k] if x.strip()]
        b = [x for x in nsec[k] if x.strip()]
        if a == b:
            continue
        plus = minus = 0
        snippet = ""
        sm = _dl.SequenceMatcher(None, a, b)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("replace", "insert"):
                plus += j2 - j1
                if not snippet:
                    snippet = next((_snippet(b[k]) for k in range(j1, j2)
                                    if _good_snippet(b[k])), "")
            if tag in ("replace", "delete"):
                minus += i2 - i1
                if not snippet:
                    snippet = next((_snippet(a[k]) for k in range(i1, i2)
                                    if _good_snippet(a[k])), "")
        if plus or minus:
            changed.append((k, plus, minus, snippet))

    changed.sort(key=lambda x: -(x[1] + x[2]))
    for k, plus, minus, snip in changed[:2]:
        label = "正文开头" if k == "（开头）" else f"「{k}」"
        seg = f"改{label}"
        if snip:
            seg += f"：{snip}"
        seg += f"（+{plus}/−{minus} 行）"
        parts.append(seg)

    for k in added[:2]:
        first = next((_snippet(x) for x in nsec[k] if _good_snippet(x)), "")
        label = "正文开头" if k == "（开头）" else f"「{k}」"
        parts.append(f"新增{label}" + (f"：{first}" if first else ""))
    for k in removed[:2]:
        label = "正文开头" if k == "（开头）" else f"「{k}」"
        parts.append(f"删除{label}")

    total = len(changed) + len(added) + len(removed)
    shown = min(len(changed), 2) + min(len(added), 2) + min(len(removed), 2)
    if total > shown:
        parts.append(f"等 {total} 处")

    if not parts:
        # 只剩字数变化（纯措辞调整）
        delta = len(nbody) - len(obody)
        parts.append(f"正文微调（{'+' if delta >= 0 else '−'}{abs(delta)} 字符）")

    desc = "；".join(parts)
    return desc[:limit] + ("…" if len(desc) > limit else "")


def ensure_derived(content: str, *, today: str | None = None) -> tuple[str, list[str]]:
    """补齐「派生块」：元信息卡 / 目录 / 相关 / 变更日志

    为什么需要它：编辑器里可能拿着一份**旧快照**（用户在我重新排版之前就打开了编辑），
    一保存就把排版生成的目录、相关、变更日志整段覆盖没了 ——
    用户看到的就是「变更日志不见了」。

    保存时先做一次结构自愈：只补**缺的**派生块，正文一个字不动。
    （正文层面的重排仍然只在「排版」按钮里做。）
    """
    if not content or not content.strip():
        return content, []
    fm_text, body = split_frontmatter(content)
    if not fm_text:
        return content, []

    lines = body.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    meta = parse_frontmatter(fm_text)
    today = today or date.today().isoformat()

    def has(pattern) -> bool:
        return any(pattern.match(ln) for ln in lines)

    # 目录/元信息卡/变更日志都有门槛：三行笔记不该被塞三个块
    h2_early = sum(1 for ln in lines if re.match(r"^##\s+", ln))
    body_early = sum(1 for ln in lines if ln.strip())

    missing: list[str] = []
    if not has(_META_HEAD_RE) and (body_early >= 8 or h2_early >= 2):
        missing.append("元信息卡")
    if not has(_TOC_HEAD_RE):
        missing.append("目录")
    if _as_list(meta.get("related")) and not has(_RELATED_H2_RE):
        missing.append("相关")
    if not has(_CHANGELOG_H2_RE):
        missing.append("变更日志")

    # 目录只在够长时才该有；不然「补目录」等于给三行笔记加个空壳
    h2 = h2_early
    body_lines = body_early
    want_toc = body_lines > 40 or h2 >= 4
    if "目录" in missing and not want_toc:
        missing.remove("目录")
    if not missing:
        return content, []

    # 复用装配逻辑：它知道这些块该放在哪儿、怎么编号
    repaired = _assemble(
        "\n".join(lines),
        meta=meta,
        title=str(meta.get("title") or ""),
        add_summary=False,
        toc=True if want_toc else False,
        meta_card=("元信息卡" in missing),
        enrich=True,
        today=today,
    )
    return dump_frontmatter(meta) + "\n\n" + repaired, missing


def _sync_meta(content: str, title: str | None, tags: list[str] | None) -> str:
    """把记录字段（title / tags）同步进 front-matter

    笔记的「标题」在库里有字段、在正文 front-matter 里也有一份。
    用户在页面上改了标题，只改了字段 —— 不 ← 同步的话：
      · 属性面板显示的还是旧标题；
      · 变更日志的「改了什么」也看不到标题变化。
    """
    if title is None and tags is None:
        return content
    fm_text, body = split_frontmatter(content)
    if not fm_text:
        return content
    meta = parse_frontmatter(fm_text)
    changed = False
    if title is not None and str(title).strip() and str(meta.get("title") or "").strip() != str(title).strip():
        meta["title"] = str(title).strip()
        changed = True
    if tags is not None:
        new_tags = [str(t).strip() for t in tags if str(t).strip()]
        old_tags = _as_list(meta.get("tags"))
        if new_tags != old_tags:
            meta["tags"] = new_tags
            changed = True
    if not changed:
        return content
    return dump_frontmatter(meta) + "\n\n" + body


def touch_note(
    content: str,
    *,
    old_content: str = "",
    title: str | None = None,
    tags: list[str] | None = None,
    source: str = "human",
    today: str | None = None,
) -> tuple[str, dict]:
    """保存笔记时调用：更新 updated / version，并往「变更日志」追加一行真实记录

    为什么必须做这件事：
      排版时生成的变更日志只有一行「按规范自动排版」，之后人在页面上改了正文，
      这一行**不会变** —— 日志就成了一句谎话（用户实测发现：改了、保存了，
      变更日志纹丝不动）。

    现在的规矩：
      · 正文没变 → 返回原文（不产生噪音）
      · 正文变了 → version +0.1、updated 改成今天、变更日志追加
        `| 日期 | vX.Y | 人工编辑（+a / −b 字符） |`
      · 没有变更日志章节的笔记，顺手补一个（长笔记才算，短的加空表没意义）
    """
    if not content or not content.strip():
        return content, {}
    fm_text, body = split_frontmatter(content)
    if not fm_text:
        return content, {}

    # 记录字段（标题/标签）先同步进 front-matter，改了什么才看得出来
    content = _sync_meta(content, title, tags)
    fm_text, body = split_frontmatter(content)
    if not fm_text:
        return content, {}

    # 用户这次实际改动的正文（自愈补的派生块不算改动，描述也基于它）
    incoming_content = content
    incoming_body_len = len(body)

    # 结构自愈：旧快照保存时把目录/相关/变更日志覆盖没了 → 先补回来
    content, _repaired = ensure_derived(content, today=today)
    fm_text, body = split_frontmatter(content)
    if not fm_text:
        return content, {}

    # 正文没变 → 什么都不做（避免「保存一次版本＋0.1」的版本号灌水）
    if old_content:
        _ofm0, old_body0 = split_frontmatter(old_content)
        if (old_body0 if _ofm0 else old_content) == body:
            return content, {}

    meta = parse_frontmatter(fm_text)
    today = today or date.today().isoformat()
    old_ver = _fmt_version(meta.get("version") or 1.0)
    try:
        new_ver = f"{round(float(old_ver) + 0.1, 1):.1f}"
    except Exception:
        old_ver, new_ver = "1.0", "1.1"

    meta["version"] = float(new_ver)
    meta["updated"] = today

    # 字数差：按「去掉 front-matter 的正文」算，别把元数据算进去
    _ofm, old_body = split_frontmatter(old_content or "")
    delta = incoming_body_len - len(old_body or "")

    who = {
        "human": "人工编辑", "": "人工编辑", "agent": "Agent 更新",
        "format": "重新排版", "ai": "AI 整理",
    }.get(source, source)

    # 「改了什么」要说清楚：哪一节、哪句、+几行/−几行；只写「+12 字符」等于没写
    desc = describe_change(old_content, incoming_content)
    if not desc:
        desc = f"正文调整（{'+' if delta >= 0 else '−'}{abs(delta)} 字符）"
    row = f"| {today} | v{new_ver} | {who} · {desc} |"

    lines = body.split("\n")
    # 先去掉尾部空行：否则补「变更日志」时会多出一个空行（下次排版又会被吃掉，来回抖）
    while lines and not lines[-1].strip():
        lines.pop()
    idx = next((i for i, ln in enumerate(lines) if _CHANGELOG_H2_RE.match(ln)), None)
    if idx is None:
        if sum(1 for ln in lines if ln.strip()) >= 15:
            lines += [
                "", "---", "", "## 📝 变更日志", "",
                "| **📅 日期** | **🔖 版本** | **📋 变更** |",
                "|:---|:---|:---|",
                row,
            ]
    else:
        end = next((k for k in range(idx + 1, len(lines))
                    if re.match(r"^##\s+", lines[k])), len(lines))
        last_row = None
        has_table = False
        for k in range(idx + 1, end):
            t = lines[k].strip()
            if t.startswith("|"):
                has_table = True
                if not re.match(r"^\|[\s:|-]+\|$", t):
                    last_row = k
        if last_row is not None:
            lines.insert(last_row + 1, row)
        elif has_table:
            # 只有表头没有数据行
            lines.insert(idx + 2, row)
        else:
            lines[idx + 1:idx + 1] = [
                "", "| **📅 日期** | **🔖 版本** | **📋 变更** |",
                "|:---|:---|:---|", row,
            ]

    lines, _ = _refresh_meta_card(lines, meta)
    new_body = "\n".join(lines).strip() + "\n"
    return dump_frontmatter(meta) + "\n\n" + new_body, {
        "version": new_ver,
        "delta": delta,
        "updated": today,
    }


# 规则清单（给前端展示「规范条目 → 我们做了没有」）
RULE_CATALOG: list[dict] = [
    {"id": "frontmatter", "section": "§2", "title": "补齐 front-matter",
     "desc": "title / tags / created / updated / version / scope / status，已有值不覆盖",
     "report_key": "frontmatter_added"},
    {"id": "related", "section": "§2.1/§10", "title": "related 规范化",
     "desc": '统一成列表 + 引号包住的 wikilink，写完用 YAML 自检', "report_key": "frontmatter_normalized"},
    {"id": "dates", "section": "§2.2", "title": "日期落成实际值",
     "desc": "Templater 的 = date(today) 一律换成真实日期", "report_key": "dates_resolved"},
    {"id": "h1", "section": "§1", "title": "笔记名配 emoji",
     "desc": "按笔记类型/标题语义给 H1 加一个 emoji", "report_key": "h1_emoji"},
    {"id": "h2", "section": "§1", "title": "章节标题配 emoji",
     "desc": "H2 按章节类型（背景/步骤/警告…）加 emoji", "report_key": "h2_emoji"},
    {"id": "bare_heading", "section": "§1", "title": "裸标题提升",
     "desc": "独占一行的短标题（忘了打 #）提升成 H2", "report_key": "bare_heading"},
    {"id": "abstract", "section": "§3.2", "title": "顶部摘要卡",
     "desc": "第一个 H2 之前放 > [!abstract] TL;DR", "report_key": "abstract_added"},
    {"id": "meta_card", "section": "§3.2", "title": "元信息卡",
     "desc": "从 front-matter 生成 > [!info] 元信息", "report_key": "meta_card"},
    {"id": "callout", "section": "§3", "title": "引用块转 callout",
     "desc": "普通 > 引用转成 > [!note]，保留已有 callout", "report_key": "quote_to_callout"},
    {"id": "toc", "section": "§4", "title": "自动目录",
     "desc": "正文 > 50 行或 H2 ≥ 5 时生成 📑 目录（锚点可跳）", "report_key": "toc_added"},
    {"id": "table", "section": "§5", "title": "表格美化",
     "desc": "表头加粗、状态值配 emoji、列数不动", "report_key": "table_header_bold"},
    {"id": "code_lang", "section": "§6.1", "title": "代码块补语言",
     "desc": "扫全文猜语言（bash/python/sql/json…），猜不到不瞎标", "report_key": "code_lang"},
    {"id": "commands", "section": "§6.1", "title": "命令行围栏",
     "desc": "连续命令行（$ 提示符或 ≥2 行裸命令）包成 bash 代码块", "report_key": "commands_fenced"},
    {"id": "hr", "section": "§8.1", "title": "分割线留白",
     "desc": "--- 前后各空一行", "report_key": "hr_spacing"},
    {"id": "task", "section": "§8.3", "title": "任务列表统一",
     "desc": "- [~] → - [-]，状态词配 emoji", "report_key": "task_normalized"},
    {"id": "density", "section": "§8.1", "title": "段落密度",
     "desc": "「一句话一段」的松散排版合并成正常段落", "report_key": "paragraphs_merged"},
    {"id": "empty_section", "section": "§1", "title": "空章节清理",
     "desc": "只有标题、下面没有内容的空章节删掉", "report_key": "empty_sections_dropped"},
    {"id": "banner", "section": "§3", "title": "敏感度横幅",
     "desc": "secret → [!danger] 最高机密，confidential → [!warning] 内部资料",
     "report_key": "banner_added"},
    {"id": "risk_callout", "section": "§3", "title": "风险条目卡片",
     "desc": "「C2 严重 —— …」这类发现变成 danger/warning 卡片", "report_key": "risk_callout"},
    {"id": "cn_heading", "section": "§1", "title": "中文序号标题",
     "desc": "「一、」「二、」从文档里复制过来的标题", "report_key": "cn_heading"},
    {"id": "code_restore", "section": "§6.1", "title": "还原丢失的代码块",
     "desc": "只留下「代码块」标记的裸代码重新包进围栏", "report_key": "code_block_restored"},
    {"id": "tsv_table", "section": "§5", "title": "制表符表格",
     "desc": "复制成 TSV 的表格还原成 Markdown 表格", "report_key": "tsv_table"},
    {"id": "fix_checklist", "section": "§8.3", "title": "修复建议清单",
     "desc": "修复/建议章节里的条目变成 - [ ]", "report_key": "fix_checklist"},
    {"id": "structure", "section": "§3", "title": "AI 速览三表",
     "desc": "目标 / 风险 / 时间线", "report_key": "structure_sections"},
    {"id": "secrets", "section": "§11", "title": "凭证遮盖",
     "desc": "密码/口令/token/私钥等值包成 secret-toggle（桌面悬停、移动端点按）",
     "report_key": "secrets_masked"},
]


def rule_catalog() -> list[dict]:
    return [dict(r) for r in RULE_CATALOG]


def note_template(title: str, *, tags: list[str] | None = None,
                  source: str = "human", scope: str = "concept",
                  status: str = "draft", summary: str = "",
                  related: list[str] | None = None,
                  sensitivity: str = "") -> str:
    """新建笔记的模板（§2 front-matter + §1 标题层级）

    和 Obsidian 里「从模板新建」是一回事 ——
    新笔记一建出来就是符合规范的形态，不用事后再排一遍。
    """
    today = date.today().isoformat()
    t = (title or "").strip()
    meta = {
        "title": t,
        "tags": list(tags or []),
        "created": today,
        "updated": today,
        "source": source,
        "version": 1.0,
        "scope": scope,
        "status": status,
    }
    if sensitivity:
        meta["sensitivity"] = sensitivity
    if related:
        meta["related"] = list(related)

    body_title = f"# {emoji_for_title(t, scope)} {t}".strip() if t else "# 无标题"
    parts = [dump_frontmatter(meta), "", body_title, ""]
    if summary:
        parts += ["> [!abstract] 摘要", f"> {summary}", ""]
    parts += ["---", "", "", ""]
    return "\n".join(parts).rstrip() + "\n"
