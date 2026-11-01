"""源码蒸馏器 —— 把源码里的「方法与经验」抽出来，原文不留

为什么需要这个东西：源码不该长期躺在知识库里 ——
体积大、泄密风险高、过期得快；
但里面的**方法与经验**（怎么写的、踩过什么坑、什么约定、调用顺序）非常值钱。
于是有了蒸馏：读源码 → 抽出可复用的经验基因 → 原文不留。

四条硬约束，比功能本身更重要：

1. **不抄原文**。输出里只允许「中文描述 + 极短的骨架片段」。
   这条一旦破了，「吸收经验后销毁源码」的前提就没了 ——
   等于把源码换了个地方存，还多了一份没人维护的副本。
   为了不靠自觉，最后还加了一道**输出闸**（_Guard）：
   任何原样抄来的源码行都必须事先登记，否则在输出前被替换掉。

2. **不联网、不调模型**。纯静态分析。
   蒸馏器要能离线跑在受限环境里，而且结果必须可复现 ——
   同一个文件跑两次必须给出同样的基因，否则「经验库」就成了薛定谔的库。

3. **不新增依赖**。中文分词、摘要这些能力都不需要；
   Python 用标准库 ast，其它语言用正则。

4. **不抛异常**。蒸馏器是「增强环节」：
   源码再烂也不该把调用方的流程打断，
   解析失败就降级（language='unknown' + 一条 warning），
   混淆代码就只给摘要。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, field

# ---------- 规模与安全边界 ----------

# 超过 2 MB 的文件基本不是「一份源码」，多半是数据导出或打包产物
MAX_BYTES = 2 * 1024 * 1024
# 超限时只取前面这一段：经验通常集中在文件头部（说明、入口、配置）
MAX_TAKE_BYTES = 200 * 1024

# 骨架最多 12 行：这是「不抄原文」的量化边界
MAX_SKELETON_LINES = 12
# 每条基因里允许附带的骨架片段行数（签名级别，不是实现体）
MAX_FRAGMENT_LINES = 6

# 单行超过这个长度就当异常：minify 后的 JS 一行能上万字符
LONG_LINE = 1000
# 平均行长超过这个值基本可以断定是压缩过的
AVG_LINE_OBFUSCATED = 200
# 行数很多**且**平均行长也不小，才判压缩：
# 只有一个条件成立时，长文件或宽表格都可能误判
MANY_LINES = 5000
AVG_LINE_MANY = 80

# 敏感词：键名里出现就换值（子串匹配，宁可多换不可漏换）
#
# 注意别把 "auth" 放进来：author / authority 这类普通词会被误伤，
# 而 Authorization 场景由 Bearer 规则单独兜。
SECRET_WORDS = (
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "access_key", "private_key", "bearer", "credential", "authorization",
    # 中文键名同样要脱敏：这个仓库的源码注释全是中文
    "密码", "口令", "密钥", "令牌",
)
REDACTED = "***"


@dataclass
class DistillResult:
    language: str
    summary: str
    sha256: str
    lines: int
    genes: list[dict]
    skeleton: str
    stats: dict
    warnings: list[str] = field(default_factory=list)


def _empty_stats() -> dict:
    return {"functions": 0, "classes": 0, "error_paths": 0,
            "config_keys": 0, "imports": 0, "todos": 0}


# ---------- 脱敏 ----------

# key = value / key: value / "key": "value" —— 值一律换成 ***
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)([\"']?[\w.\-]*(?:" + "|".join(SECRET_WORDS) + r")[\w.\-]*[\"']?"
    r"\s*[:=]\s*)([\"']?)([^\s\"',;#\)\]\}]+)(\2)"
)
# URL 里的 user:pass@host
_URL_CRED_RE = re.compile(r"([a-zA-Z][\w+.\-]*://)([^\s/:@]+):([^\s/@]+)@")
# Authorization: Bearer xxxxx
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._\-]{6,})")


def _redact(text: str) -> str:
    """把敏感值替换成 ***，键名保留

    为什么键名要留着：调用方要知道「这里有一个叫 API_KEY 的东西」，
    才知道去查配置；把键名一起抹掉，基因就只剩一句废话。
    """
    if not text:
        return text
    out = _SECRET_ASSIGN_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    out = _URL_CRED_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}:{REDACTED}@", out)
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
    return out


def _redact_default(name: str, value: str) -> str:
    """函数默认参数：参数名敏感时换值"""
    low = (name or "").lower()
    if any(w in low for w in SECRET_WORDS):
        return REDACTED
    return _redact(value)


# ---------- 小工具 ----------

def _short(text: str, n: int = 60) -> str:
    """截断并去掉换行，保证是「一行」"""
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _first_line(text: str) -> str:
    """取第一段非空行"""
    for line in (text or "").split("\n"):
        s = line.strip().strip("#").strip()
        if s:
            return s
    return ""


def _clean(text: str, n: int = 80) -> str:
    """把源码片段清理成一行可读文本（并脱敏）"""
    return _short(_redact(text or ""), n)


class _Guard:
    """输出前的最后一道闸：原样抄来的源码行必须事先登记

    为什么需要这道闸：蒸馏器的全部价值都压在「不抄原文」这一条上。
    只要有一处不小心把实现体整段贴进 content，
    「吸收经验后销毁源码」的前提就破了 ——
    而且这种泄漏肉眼很难发现（输出看起来就是正常的说明文字）。
    所以这里用集合比对：凡是要原样出现在输出里的源码行，
    必须先 allow() 登记；没登记的一律在输出前替换掉。
    """

    def __init__(self, text: str):
        self.source_lines = {ln.strip() for ln in (text or "").split("\n") if ln.strip()}
        self.allowed: set[str] = set()

    def allow(self, line: str) -> str:
        self.allowed.add((line or "").strip())
        return line

    def allow_safe(self, line: str) -> str:
        """登记并返回**脱敏后**的行

        必须脱敏后再登记：
        骨架里直接放原始行，等于把 export DB_PASSWORD=xxx 这种值
        原样抄了出来 —— 闸门放行的恰恰是最不该放的东西。
        """
        safe = _redact(line or "")
        self.allowed.add(safe.strip())
        return safe

    def scrub(self, line: str) -> str:
        s = (line or "").strip()
        if s and s in self.source_lines and s not in self.allowed:
            return "（源码片段已省略）"
        return line

    def scrub_text(self, text: str) -> str:
        return "\n".join(self.scrub(ln) for ln in (text or "").split("\n"))


# ---------- 语言识别 ----------

_LANG_BY_EXT = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ksh": "shell",
    ".sql": "sql",
    ".yaml": "config", ".yml": "config", ".json": "config",
    ".toml": "config", ".ini": "config", ".cfg": "config", ".conf": "config",
    ".env": "config", ".properties": "config",
    ".md": "markdown", ".markdown": "markdown",
}

_LANG_LABEL = {
    "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
    "shell": "Shell", "sql": "SQL", "config": "配置", "markdown": "Markdown",
    "unknown": "未知",
}


def _detect_language(filename: str, text: str) -> str:
    """先看扩展名，再看内容

    为什么不只信扩展名：Dockerfile、Makefile 没有扩展名；
    而 .conf 到底是 ini 还是别的格式，光看扩展名也猜不准。
    """
    name = (filename or "").strip()
    low = name.lower()
    base = low.rsplit("/", 1)[-1]

    if base in ("dockerfile", "makefile", "jenkinsfile"):
        return "shell"
    if base.startswith(".env"):
        return "config"
    if "." in base:
        ext = "." + base.rsplit(".", 1)[-1]
        if ext in _LANG_BY_EXT:
            return _LANG_BY_EXT[ext]

    head = (text or "")[:4000]
    if head.startswith("#!") and re.search(r"\b(bash|sh|zsh)\b", head.split("\n", 1)[0]):
        return "shell"
    if re.search(r"(?i)\b(create\s+table|create\s+view|select\s+.+\s+from)\b", head):
        return "sql"
    if head.lstrip()[:1] in "{[":
        try:
            json.loads(head)
            return "config"
        except Exception:
            pass
    if re.search(r"^\s*(def|class)\s+\w+", head, re.M):
        return "python"
    if re.search(r"(?m)^\s*(export\s+)?(default\s+)?(async\s+)?function\s+\w+", head):
        return "javascript"
    if re.search(r"(?m)^\s*#{1,6}\s+\S", head):
        return "markdown"
    return "unknown"


def _looks_obfuscated(lines: list[str]) -> bool:
    """判断是不是压缩/混淆过的代码

    三个信号：
      - 单行超长（minify 的特征）
      - 平均行长 > 200（整体被压成宽行）
      - 行数 > 5000 且平均行长 > 80（又长又宽）
    第三个条件要两个信号同时成立：
    只按行数判会把正常的日志文件、生成的代码算成压缩件，
    只按平均行长判又会把宽表格（CSV）算进去。
    """
    real = [ln for ln in lines if ln.strip()]
    if not real:
        return False
    max_len = max(len(ln) for ln in real)
    avg = sum(len(ln) for ln in real) / len(real)
    if max_len > LONG_LINE:
        return True
    if avg > AVG_LINE_OBFUSCATED:
        return True
    if len(real) > MANY_LINES and avg > AVG_LINE_MANY:
        return True
    return False


# ---------- 基因构造 ----------

def _gene(kind: str, title: str, content: str, tags: list[str],
          confidence: float, *, filename: str, language: str,
          function: str = "", risk: str = "low") -> dict:
    """基因的统一形状

    confidence 是「这条经验有多可靠」的判断，不是概率：
    异常处理路径（有代码佐证）给高值，
    注释里的 TODO（作者自己说的）给中值，
    靠正则猜出来的（比如配置项）给低值。
    """
    return {
        "kind": kind,
        "title": _short(title, 60),
        "content": content,
        "tags": list(dict.fromkeys([t for t in tags if t]))[:8],
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "meta": {
            "function": function,
            "file": filename,
            "language": language,
            "risk": risk,
        },
    }


# ---------- 通用（不依赖语言）的抽取 ----------

# TODO 类标记按约定都是大写：加 (?i) 的话，正文里的 "note"（笔记）
# 会被当成待办标记，满屏都是没意义的基因
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG|NOTE)\b[:：\-]?\s*(.*)")
_SECRET_NAME_RE = re.compile(
    r"(?i)\b([A-Za-z_][\w]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[A-Za-z_]*)\b")
_DANGER_NAMES = ("eval", "exec", "compile", "os.system", "os.popen",
                 "subprocess.call", "subprocess.run", "subprocess.Popen",
                 "child_process.exec", "child_process.spawn")


def _todo_genes(text: str, filename: str, language: str,
                guard: _Guard) -> list[dict]:
    """TODO / FIXME / HACK 注释 —— 作者亲手写下的坑

    这类注释的信息密度极高：
    「TODO: 这里还没处理超时」比任何自动摘要都值钱。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for idx, line in enumerate((text or "").split("\n"), 1):
        m = _TODO_RE.search(line)
        if not m:
            continue
        kind_word = m.group(1).upper()
        note = _clean(m.group(2), 70)
        key = f"{kind_word}:{note}"
        if key in seen:
            continue
        seen.add(key)
        hint = {
            "TODO": "这里还没做完，改动时要留意别把它当成已实现",
            "FIXME": "这里已知有缺陷，触发条件多半是它旁边那几行",
            "HACK": "这里是权宜之计，别顺手「优化」掉",
            "XXX": "这里有问题待查",
            "BUG": "这里是已知缺陷",
            "NOTE": "这里是作者特意留的提醒",
        }.get(kind_word, "这里是作者留的备注")
        out.append(_gene(
            "experience",
            f"{kind_word}：{note or '（无说明）'}",
            f"源码第 {idx} 行留了一条 {kind_word} 注释：{note or '（没写内容）'}。"
            f"{hint}。",
            [kind_word, "注释"],
            0.75, filename=filename, language=language,
        ))
    return out


def _danger_genes(text: str, filename: str, language: str) -> list[dict]:
    """危险调用 —— 政策类基因

    「这段代码会执行外部命令」这件事，
    半年后接手的人不会自己看出来，但它是改动时必须知道的前提。
    """
    out: list[dict] = []
    for name in _DANGER_NAMES:
        # 用词边界匹配：直接 find("eval") 会把 evaluate / retrieval 也算进来
        m = re.search(r"\b" + re.escape(name) + r"\s*\(", text or "")
        if not m:
            continue
        idx = m.start()
        line_no = text[:idx].count("\n") + 1
        shell = bool(re.search(r"(?i)shell\s*=\s*True", text[idx:idx + 200]))
        detail = "并且指定了 shell=True（命令会经过 shell 解释）" if shell else ""
        out.append(_gene(
            "policy",
            f"存在高危调用：{name}",
            f"源码第 {line_no} 行附近调用了 {name}{detail}。"
            f"这类调用会把外部输入变成可执行内容，改动或复用这段经验时必须确认输入可控。",
            ["安全", "高危", name.split(".")[-1]],
            0.8, filename=filename, language=language, risk="high",
        ))
    return out


def _secret_name_genes(text: str, filename: str, language: str) -> list[dict]:
    """看起来像密钥的变量名 —— 提醒它应该来自配置而不是硬编码"""
    out: list[dict] = []
    seen: set[str] = set()
    for m in _SECRET_NAME_RE.finditer(text or ""):
        name = m.group(1)
        if name in seen or name.upper() in seen:
            continue
        seen.add(name.upper())
        out.append(_gene(
            "policy",
            f"疑似硬编码密钥变量：{name}",
            f"源码里出现了名为 {name} 的标识符。"
            f"蒸馏输出里它的值已被替换成 {REDACTED}；"
            f"如果原文件里写的是字面量，那本身就是一处隐患，应当改从环境变量或配置读。",
            ["安全", "密钥", name],
            0.6, filename=filename, language=language, risk="medium",
        ))
        if len(out) >= 5:
            break
    return out


# ---------- Python 蒸馏 ----------

def _callee_name(func) -> str:
    """取调用目标的名字（a.b.c() → a.b.c；f() → f）

    为什么不直接 ast.unparse(func)：
    对 select(count(x)) 这种写法，unparse 出来的是整个调用表达式
    「select(func.count(EntityRecord.id))」——
    等于把调用点的一整段源码抄进了输出。
    只取名字，既干净又不泄实现。
    """
    parts: list[str] = []
    cur = func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    parts.reverse()
    return ".".join(parts)


class _PythonDistiller:
    """用标准库 ast 把 Python 源码拆成基因

    为什么 Python 要单独写（而不是跟其它语言共用正则）：
    正则能认出函数名，却认不出「这个 except 分支里到底做了什么」。
    而异常路径恰恰是整个蒸馏器最值钱的部分 ——
    「这里为什么会失败、失败时怎么处理」只有 AST 才拿得到。
    """

    def __init__(self, text: str, filename: str, guard: _Guard):
        self.text = text
        self.filename = filename
        self.guard = guard
        self.genes: list[dict] = []
        self.skeleton: list[str] = []
        self.stats = _empty_stats()

    # -- 入口 --
    def run(self) -> tuple[list[dict], list[str], dict] | None:
        try:
            tree = ast.parse(self.text)
        except (SyntaxError, ValueError, RecursionError) as e:
            return None
        self._module(tree)
        return self.genes, self.skeleton, self.stats

    # -- 模块级 --
    def _module(self, tree: ast.Module) -> None:
        doc = ast.get_docstring(tree)
        if doc:
            first = _first_line(doc)
            self.genes.append(_gene(
                "fact",
                f"模块用途：{first}",
                f"这个模块的文档说明写着：{_clean(first, 90)}。"
                f"模块级共定义了 {self._count_defs(tree)} 个顶层符号"
                f"（函数与类）。",
                ["模块", "说明"],
                0.8, filename=self.filename, language="python",
            ))

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.stats["imports"] += 1
            elif isinstance(node, ast.ClassDef):
                self._class(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(node, None)
            elif isinstance(node, ast.Assign):
                self._constant(node)

    def _count_defs(self, tree: ast.Module) -> int:
        n = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                n += 1
        return n

    def _constant(self, node: ast.Assign) -> None:
        """模块级常量 —— 配置项基因"""
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if name.startswith("_"):
                continue
            value = ""
            try:
                value = ast.unparse(node.value)
            except Exception:
                value = ""
            shown = _redact_default(name, value) if value else "（表达式）"
            self.stats["config_keys"] += 1
            self.genes.append(_gene(
                "interface",
                f"配置项 {name}",
                f"模块级常量 {name}，值为 {shown}。"
                f"改这个值会同时影响所有引用它的函数。",
                ["配置", "常量"],
                0.7, filename=self.filename, language="python", function=name,
            ))

    # -- 类 --
    def _class(self, node: ast.ClassDef) -> None:
        self.stats["classes"] += 1
        methods = [n for n in node.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        bases = []
        for b in node.bases:
            try:
                bases.append(_short(ast.unparse(b), 30))
            except Exception:
                pass
        doc = ast.get_docstring(node) or ""
        first = _first_line(doc)
        if first:
            # 文档字符串的第一行是「作者自己写的说明」，
            # 属于要吸收的经验，放行；但只放一行，且后面会被截断
            self.guard.allow(first)
        sig = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
        sig = self.guard.allow_safe(sig)
        self.skeleton.append(sig)
        self.genes.append(_gene(
            "method",
            f"类 {node.name}：{first}" if first else f"类 {node.name}（{len(methods)} 个方法）",
            f"类 {node.name} 定义了 {len(methods)} 个方法"
            f"（{', '.join(m.name for m in methods[:8])}）"
            f"{'，继承 ' + ', '.join(bases) if bases else ''}。"
            + (f"类文档说明：{_clean(first, 80)}。" if first else ""),
            ["类", node.name],
            0.75, filename=self.filename, language="python", function=node.name,
        ))
        for m in methods:
            self._function(m, node.name)

    # -- 函数 --
    def _function(self, node, cls: str | None) -> None:
        self.stats["functions"] += 1
        sig = self.guard.allow_safe(self._signature(node))
        self.skeleton.append(("    " if cls else "") + sig)

        doc = ast.get_docstring(node) or ""
        first = _first_line(doc)
        if first:
            self.guard.allow(first)
        params = self._params(node)
        calls = self._calls(node)
        raises, handlers = self._exception_paths(node)

        where = f"类 {cls} 的方法" if cls else "模块级函数"
        title = f"{node.name}：{first}" if first else f"{node.name}（{where}）"
        content = (
            f"{where} {node.name}，定义在第 {node.lineno} 行，"
            f"接收 {len(params)} 个参数"
            f"（{', '.join(params[:6]) if params else '无'}）。"
        )
        if node.returns is not None:
            try:
                content += f"声明返回 {ast.unparse(node.returns)}。"
            except Exception:
                pass
        else:
            content += "没有声明返回类型。"
        if first:
            content += f"文档说明：{_clean(first, 80)}。"
        if calls:
            content += f"内部调用了 {', '.join(calls[:6])}。"
        if handlers:
            content += f"有 {len(handlers)} 处异常捕获路径，{len(raises)} 处主动抛出。"
        content += "\n骨架：\n" + sig

        self.genes.append(_gene(
            "method",
            title,
            content,
            ["函数", node.name] + (["异步"] if isinstance(node, ast.AsyncFunctionDef) else []),
            0.75 if first else 0.6,
            filename=self.filename, language="python", function=node.name,
        ))

        for item in raises + handlers:
            self.genes.append(item)

    def _signature(self, node) -> str:
        """渲染函数签名（默认值脱敏）"""
        a = node.args
        parts: list[str] = []

        def _one(arg, default=None):
            if default is None:
                return arg.arg
            try:
                shown = ast.unparse(default)
            except Exception:
                shown = "…"
            return f"{arg.arg}={_redact_default(arg.arg, shown)}"

        pos = list(a.posonlyargs) + list(a.args)
        defaults = list(a.defaults)
        pad = len(pos) - len(defaults)
        for i, arg in enumerate(pos):
            d = defaults[i - pad] if i >= pad else None
            parts.append(_one(arg, d))
        if a.vararg:
            parts.append("*" + a.vararg.arg)
        elif a.kwonlyargs:
            parts.append("*")
        for arg, d in zip(a.kwonlyargs, a.kw_defaults):
            parts.append(_one(arg, d))
        if a.kwarg:
            parts.append("**" + a.kwarg.arg)
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        sig = f"{prefix} {node.name}({', '.join(parts)})"
        if node.returns is not None:
            try:
                sig += f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass
        return sig

    def _params(self, node) -> list[str]:
        a = node.args
        return [arg.arg for arg in list(a.posonlyargs) + list(a.args)]

    def _calls(self, node) -> list[str]:
        out: list[str] = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = _callee_name(sub.func)
                name = _short(name, 40)
                if name and name not in out:
                    out.append(name)
        return out

    def _exception_paths(self, node) -> tuple[list[dict], list[dict]]:
        """异常路径 —— 整个蒸馏器最值钱的部分

        异常路径回答的是「这里为什么会失败、失败时怎么处理」，
        这是任何摘要工具都会丢掉的语义。
        """
        raises: list[dict] = []
        handlers: list[dict] = []
        fname = node.name

        for sub in ast.walk(node):
            if isinstance(sub, ast.ExceptHandler):
                self.stats["error_paths"] += 1
                exc = ""
                if sub.type is not None:
                    try:
                        exc = _short(ast.unparse(sub.type), 40)
                    except Exception:
                        exc = ""
                trigger = ""
                if sub.name:
                    trigger = f"异常变量 {sub.name}"
                body_desc = self._handler_body(sub)
                detail = (
                    f"函数 {fname}（第 {sub.lineno} 行起）捕获了 {exc or '所有异常'}"
                    f"{'，绑定到 ' + trigger if trigger else ''}。"
                    f"处理方式是{body_desc}。"
                    f"这条路径决定了这类错误发生时流程会往哪走 —— "
                    f"复用这段经验时必须照着同样的语义处理，否则错误会被静默吞掉。"
                )
                handlers.append(_gene(
                    "experience",
                    f"{fname} 捕获 {exc or '异常'} 的处理路径",
                    detail,
                    ["异常", exc or "异常", fname],
                    0.9, filename=self.filename, language="python", function=fname,
                    risk="medium",
                ))
            elif isinstance(sub, ast.Raise):
                exc_name = ""
                msg = ""
                is_reraise = False
                if sub.exc is None:
                    # 裸 raise：把刚才捕获的异常原样抛出去
                    exc_name = "当前异常"
                    is_reraise = True
                else:
                    try:
                        exc_name = _short(ast.unparse(sub.exc), 50)
                    except Exception:
                        exc_name = ""
                    if isinstance(sub.exc, ast.Call) and sub.exc.args:
                        try:
                            msg = _short(ast.unparse(sub.exc.args[0]), 60)
                        except Exception:
                            msg = ""
                    elif isinstance(sub.exc, ast.Name):
                        # raise last：把之前存下来的异常抛出去
                        is_reraise = True
                title = (f"{fname} 重新抛出异常" if is_reraise
                         else f"{fname} 主动抛出 {exc_name or '异常'}")
                detail = (
                    f"函数 {fname}（第 {sub.lineno} 行）"
                    + ("把捕获到的异常原样抛出，不做包装。" if is_reraise
                       else f"主动抛出 {exc_name or '异常'}"
                            f"{'，信息：' + msg if msg else ''}。")
                    + "抛错的地方就是调用方必须处理的边界："
                      "调用顺序或参数错了就会走到这里。"
                )
                raises.append(_gene(
                    "experience",
                    title,
                    detail,
                    ["异常", "抛出", fname],
                    0.85, filename=self.filename, language="python", function=fname,
                ))
        return raises, handlers

    def _handler_body(self, handler: ast.ExceptHandler) -> str:
        """把 except 分支体概括成一句中文"""
        if not handler.body:
            return "什么都不做（直接吞掉异常）"
        acts: list[str] = []
        for stmt in handler.body:
            if isinstance(stmt, ast.Raise):
                acts.append("重新抛出")
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                try:
                    name = ast.unparse(stmt.value.func)
                except Exception:
                    name = ""
                if "log" in name.lower() or "print" in name.lower():
                    acts.append("记录日志")
                elif name:
                    acts.append(f"调用 {name}")
            elif isinstance(stmt, ast.Return):
                acts.append("返回兜底值")
            elif isinstance(stmt, ast.If):
                acts.append("按条件分支处理")
            elif isinstance(stmt, ast.Assign):
                acts.append("记录到变量")
        if not acts:
            acts.append(f"执行 {len(handler.body)} 条语句")
        # 去重但保序
        seen: list[str] = []
        for a in acts:
            if a not in seen:
                seen.append(a)
        return "、".join(seen[:4])


# ---------- JavaScript / TypeScript 蒸馏 ----------

_JS_FUNC_RE = re.compile(
    r"(?m)^[ \t]*(?P<pre>(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<args>[^)]*)\))")
_JS_ARROW_RE = re.compile(
    r"(?m)^[ \t]*(?P<pre>(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s*)?\((?P<args>[^)]*)\)\s*=>)")
_JS_ARROW1_RE = re.compile(
    r"(?m)^[ \t]*(?P<pre>(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?(?P<arg>[A-Za-z_$][\w$]*)\s*=>)")
_JS_CLASS_RE = re.compile(
    r"(?m)^[ \t]*(?P<pre>(?:export\s+)?(?:default\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*))")
_JS_METHOD_RE = re.compile(
    r"(?m)^[ \t]{2,}(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<args>[^)]*)\)\s*\{")
_JS_THROW_RE = re.compile(
    r"(?m)throw\s+new\s+(?P<type>[A-Za-z_$][\w$]*)\s*\((?P<msg>[^)]*)\)")
_JS_CATCH_RE = re.compile(r"catch\s*\(\s*(?P<var>[A-Za-z_$][\w$]*)?\s*\)")
_JS_EXPORT_DEFAULT_RE = re.compile(r"(?m)^\s*export\s+default\s+")
_JS_ENV_RE = re.compile(r"process\.env(?:\.([A-Za-z_$][\w$]*)|\[['\"]([^'\"]+)['\"]\])")
_TS_INTERFACE_RE = re.compile(
    r"(?m)^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)")
_TS_TYPE_RE = re.compile(
    r"(?m)^\s*(?:export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*=")
_TS_ENUM_RE = re.compile(r"(?m)^\s*(?:export\s+)?enum\s+(?P<name>[A-Za-z_$][\w$]*)")


def _distill_js(text: str, filename: str, language: str,
                guard: _Guard) -> tuple[list[dict], list[str], dict]:
    """JS / TS 用正则蒸馏

    为什么不上解析器：没有 node、没有第三方解析器可用（不许加依赖），
    而正则足以拿到「有哪些函数、哪些类、哪里抛错、读了哪些环境变量」——
    这些正是经验的主要载体。
    """
    genes: list[dict] = []
    skeleton: list[str] = []
    stats = _empty_stats()
    label = "TypeScript" if language == "typescript" else "JavaScript"

    funcs: list[tuple[str, str]] = []
    for rx in (_JS_FUNC_RE, _JS_ARROW_RE):
        for m in rx.finditer(text):
            funcs.append((m.group("name"), _short(m.group("args"), 60)))
    for m in _JS_ARROW1_RE.finditer(text):
        funcs.append((m.group("name"), m.group("arg")))

    classes = [(m.group("name"), m.group("pre").strip())
               for m in _JS_CLASS_RE.finditer(text)]

    for name, args in funcs:
        stats["functions"] += 1
        sig = f"function {name}({args})"
        sig = guard.allow_safe(sig)
        skeleton.append(sig)
        params = [a.strip() for a in args.split(",") if a.strip()]
        genes.append(_gene(
            "method",
            f"函数 {name}",
            f"{label} 函数 {name}，接收 {len(params)} 个参数"
            f"（{', '.join(params[:6]) if params else '无'}）。"
            f"它在整个文件里被当作可复用的调用单元，"
            f"调用顺序与入参约定要照原样使用。\n骨架：\n{sig}",
            ["函数", name],
            0.6, filename=filename, language=language, function=name,
        ))

    for name, pre in classes:
        stats["classes"] += 1
        sig = f"class {name}"
        sig = guard.allow_safe(sig)
        skeleton.append(sig)
        methods = [m.group("name") for m in _JS_METHOD_RE.finditer(text)]
        genes.append(_gene(
            "method",
            f"类 {name}",
            f"{label} 类 {name}，"
            f"可见方法有 {', '.join(methods[:8]) if methods else '（未识别到）'}。"
            f"类里的方法通常各自承担一个动作，调用方依赖它们的返回结构。",
            ["类", name],
            0.6, filename=filename, language=language, function=name,
        ))

    # 抛错 = 错误边界，最值钱
    for m in _JS_THROW_RE.finditer(text):
        stats["error_paths"] += 1
        msg = _clean(m.group("msg"), 70)
        genes.append(_gene(
            "experience",
            f"抛出 {m.group('type')}：{msg}" if msg else f"抛出 {m.group('type')}",
            f"代码里有一处主动抛出 {m.group('type')}"
            f"{'，信息是 ' + msg if msg else ''}。"
            f"主动抛错的地方就是这条链路的边界条件："
            f"调用方要么捕获它，要么明确让它冒泡。",
            ["异常", "抛出", m.group("type")],
            0.8, filename=filename, language=language,
        ))

    for m in _JS_CATCH_RE.finditer(text):
        stats["error_paths"] += 1
        var = m.group("var")
        genes.append(_gene(
            "experience",
            f"捕获异常{'（' + var + '）' if var else ''}",
            f"这里有一段 catch，捕获后{'把错误存进 ' + var if var else '做兜底处理'}。"
            f"捕获路径决定了失败时是「降级继续」还是「向上抛出」，"
            f"复用时必须保持一致，否则错误会被静默吞掉。",
            ["异常", "捕获"],
            0.6, filename=filename, language=language,
        ))

    envs: list[str] = []
    for m in _JS_ENV_RE.finditer(text):
        name = m.group(1) or m.group(2)
        if name and name not in envs:
            envs.append(name)
    for name in envs:
        stats["config_keys"] += 1
        genes.append(_gene(
            "interface",
            f"环境变量 {name}",
            f"代码从进程环境里读 {name}。"
            f"部署时这个变量必须存在，否则相关功能直接不可用 —— "
            f"这是这份代码对外的隐含契约。",
            ["配置", "环境变量", name],
            0.75, filename=filename, language=language, function=name,
        ))

    if language == "typescript":
        for rx, kind in ((_TS_INTERFACE_RE, "接口"), (_TS_TYPE_RE, "类型别名"),
                         (_TS_ENUM_RE, "枚举")):
            for m in rx.finditer(text):
                stats["classes"] += 1
                name = m.group("name")
                sig = f"{kind} {name}"
                sig = guard.allow_safe(sig)
                skeleton.append(sig)
                genes.append(_gene(
                    "interface",
                    f"类型契约 {name}（{kind}）",
                    f"文件里声明了 {kind} {name}，"
                    f"这是这段代码对外的数据形状约定："
                    f"别的文件按这个形状传数据进来，形状变了就会在编译期或运行期炸掉。",
                    ["类型", kind, name],
                    0.7, filename=filename, language=language, function=name,
                ))

    if _JS_EXPORT_DEFAULT_RE.search(text):
        genes.append(_gene(
            "interface",
            "模块对外只导出一个默认入口",
            "这个文件用 export default 导出，"
            "使用方按「一个默认对象」来引用，"
            "改名或改成具名导出都会打断所有引用点。",
            ["导出", "入口"],
            0.6, filename=filename, language=language,
        ))

    return genes, skeleton, stats


# ---------- Shell 蒸馏 ----------

def _distill_shell(text: str, filename: str, guard: _Guard):
    genes: list[dict] = []
    skeleton: list[str] = []
    stats = _empty_stats()

    for idx, line in enumerate((text or "").split("\n"), 1):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#!") and not skeleton:
            s = guard.allow_safe(s)
            skeleton.append(s)
            genes.append(_gene(
                "fact",
                f"脚本解释器：{s}",
                f"脚本声明用 {s} 解释。"
                f"换解释器往往意味着行为不同（尤其 bash 与 sh 的数组、管道差异）。",
                ["脚本", "解释器"],
                0.8, filename=filename, language="shell",
            ))
            continue
        if re.match(r"^set\s+-[a-zA-Z]*e", s) or "pipefail" in s:
            s = guard.allow_safe(s)
            skeleton.append(s)
            genes.append(_gene(
                "policy",
                f"脚本启用了严格模式：{s}",
                f"脚本用 {s} 声明了严格模式："
                f"命令失败、管道中段失败、变量未定义都会直接终止脚本。"
                f"这是一条重要的约定 —— 改动时别把它去掉，"
                f"否则脚本会在出错后继续往下跑，留下半成品状态。",
                ["脚本", "严格模式"],
                0.85, filename=filename, language="shell", risk="medium",
            ))
            continue
        m = re.match(r"^export\s+([A-Za-z_][\w]*)=(.*)$", s)
        if m:
            stats["config_keys"] += 1
            # 按**键名**判定敏感：值本身没有键，脱敏正则认不出来
            name, value = m.group(1), _redact_default(m.group(1), m.group(2))
            # 骨架里写成「NAME=值」而不是原样照抄那一行：
            # 声明式信息保留，原文不抄
            s = guard.allow_safe(f"{name}={value}")
            skeleton.append(s)
            genes.append(_gene(
                "interface",
                f"环境变量 {name}",
                f"脚本导出环境变量 {name}，默认值 {value[:40]}。"
                f"外部可以在调用时覆盖它，脚本内部按这个值走。",
                ["配置", "环境变量", name],
                0.75, filename=filename, language="shell", function=name,
            ))
            continue
        if re.search(r"(?i)\brm\s+-[a-zA-Z]*[rf]", s) or re.search(r"(?i)curl[^|]*\|\s*(ba)?sh", s) \
                or re.search(r"(?i)\bsudo\b", s):
            stats["error_paths"] += 1
            s = guard.allow_safe(s)
            genes.append(_gene(
                "policy",
                f"脚本里有高危命令：{s[:40]}",
                f"第 {idx} 行附近是破坏性或提权命令。"
                f"复用这段经验时必须确认目标路径与执行身份，"
                f"这类命令一旦参数错位，代价是不可逆的。",
                ["安全", "高危"],
                0.8, filename=filename, language="shell", risk="high",
            ))
            continue
        if s.startswith("#"):
            note = _clean(s.lstrip("#").strip(), 80)
            if len(note) < 6:
                continue
            stats["todos"] += 1
            genes.append(_gene(
                "method",
                f"脚本注释：{note}",
                f"脚本第 {idx} 行有说明：{note}。"
                f"注释里写的通常是这段脚本的用法前提，照着用才不会出错。",
                ["脚本", "注释"],
                0.6, filename=filename, language="shell",
            ))

    return genes, skeleton, stats


# ---------- SQL 蒸馏 ----------

_SQL_DDL_RE = re.compile(
    r"(?is)\bcreate\s+(?:or\s+replace\s+)?(table|view)\s+(?:if\s+not\s+exists\s+)?"
    r"[`\"\[]?([\w.]+)[`\"\]]?\s*\((.*?)\)\s*(?:;|$)")
_SQL_INDEX_RE = re.compile(
    r"(?is)\bcreate\s+(?:unique\s+)?index\s+(?:if\s+not\s+exists\s+)?"
    r"[`\"\[]?([\w.]+)[`\"\]]?\s+on\s+([`\"\[]?[\w.]+[`\"\]]?)\s*\(([^)]*)\)")


def _distill_sql(text: str, filename: str, guard: _Guard):
    genes: list[dict] = []
    skeleton: list[str] = []
    stats = _empty_stats()

    for m in _SQL_DDL_RE.finditer(text):
        obj_type, name, body = m.group(1), m.group(2), m.group(3)
        stats["classes"] += 1
        cols: list[str] = []
        for part in body.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if len(tokens) >= 2:
                col = f"{tokens[0]} {tokens[1]}"
                if "primary key" in part.lower():
                    col += "（主键）"
                cols.append(col)
            elif tokens:
                cols.append(tokens[0])
        sig = f"CREATE {obj_type.upper()} {name}"
        sig = guard.allow_safe(sig)
        skeleton.append(sig)
        genes.append(_gene(
            "interface",
            f"表结构 {name}（{obj_type}）",
            f"这里定义了 {obj_type} {name}，共 {len(cols)} 列："
            f"{'；'.join(cols[:12])}。"
            f"表结构就是接口约定：写入方按这套列名与类型来，"
            f"改列名会让所有依赖它的查询一起失效。",
            ["表结构", obj_type, name],
            0.8, filename=filename, language="sql", function=name,
        ))

    for m in _SQL_INDEX_RE.finditer(text):
        stats["config_keys"] += 1
        sig = f"CREATE INDEX {m.group(1)}"
        sig = guard.allow_safe(sig)
        skeleton.append(sig)
        cols = _clean(m.group(3), 60)
        genes.append(_gene(
            "fact",
            f"索引 {m.group(1)} 建在 {m.group(2)} 上",
            f"索引覆盖的列是 {cols}。"
            f"索引是有成本的写入代价换查询速度，"
            f"删索引之前先确认没有查询依赖它 —— 否则数据量一大查询会直接变慢。",
            ["索引", "性能"],
            0.75, filename=filename, language="sql", function=m.group(1),
        ))

    for m in re.finditer(r"(?m)^\s*--\s*(.+)$", text):
        note = _clean(m.group(1), 80)
        if len(note) < 6:
            continue
        stats["todos"] += 1
        genes.append(_gene(
            "method",
            f"SQL 注释：{note}",
            f"SQL 里有注释：{note}。"
            f"注释通常是这条语句的用途或坑点说明。",
            ["SQL", "注释"],
            0.6, filename=filename, language="sql",
        ))

    return genes, skeleton, stats


# ---------- 配置蒸馏 ----------

def _flatten_json(obj, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.extend(_flatten_json(v, path))
    elif isinstance(obj, list):
        out.append((prefix, f"[{len(obj)} 项]"))
    else:
        out.append((prefix, "" if obj is None else str(obj)))
    return out


def _flatten_yaml(text: str) -> list[tuple[str, str]]:
    """按缩进扫出 YAML 的键值（不引第三方 YAML 库）

    只取「键 → 标量值」，嵌套用缩进层级表示成点号路径；
    列表与多行块（| / >）不深挖 —— 那部分通常不是配置项。
    """
    out: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    for raw in (text or "").split("\n"):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if line.startswith("-"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().strip("\"'")
        value = value.strip().strip("\"'")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
        path = ".".join(k for _, k in stack)
        if value and not value.startswith("|") and not value.startswith(">"):
            out.append((path, value))
        elif not value:
            out.append((path, "（嵌套）"))
    return out


def _distill_config(text: str, filename: str, language: str, guard: _Guard):
    genes: list[dict] = []
    skeleton: list[str] = []
    stats = _empty_stats()
    lower = (filename or "").lower()

    pairs: list[tuple[str, str]] = []
    if lower.endswith(".json"):
        try:
            pairs = _flatten_json(json.loads(text or "{}"))
        except Exception:
            pairs = []
    elif lower.endswith(".toml"):
        try:
            import tomllib
            pairs = _flatten_json(tomllib.loads(text or ""))
        except Exception:
            pairs = []
    elif lower.endswith((".yaml", ".yml")):
        pairs = _flatten_yaml(text or "")
    else:
        # .env / .ini / .conf：KEY=VALUE 或 KEY: VALUE
        for raw in (text or "").split("\n"):
            line = raw.strip()
            if not line or line.startswith(("#", ";", "[")):
                continue
            m = re.match(r"^(?:export\s+)?([A-Za-z_][\w.\-]*)\s*[:=]\s*(.*)$", line)
            if m:
                pairs.append((m.group(1), m.group(2).strip()))

    for key, value in pairs:
        stats["config_keys"] += 1
        shown = _redact_default(key, value)
        sig = f"{key} = {shown}" if value else f"{key}"
        sig = guard.allow_safe(sig)
        skeleton.append(sig)
        genes.append(_gene(
            "interface",
            f"配置项 {key}",
            f"配置项 {key}，默认值 {shown}。"
            f"配置项的默认值只是「没人显式设置时」的兜底，"
            f"真正生效的值通常来自环境变量或配置中心 —— "
            f"改动它之前先确认部署侧有没有覆盖。",
            ["配置", key.split(".")[0]],
            0.75, filename=filename, language=language, function=key,
        ))

    return genes, skeleton, stats


# ---------- Markdown 蒸馏 ----------

def _distill_markdown(text: str, filename: str, guard: _Guard):
    """Markdown：每个一级标题一段，列表项是经验点"""
    genes: list[dict] = []
    skeleton: list[str] = []
    stats = _empty_stats()

    section = ""
    bullets: list[str] = []
    in_fence = False
    h1 = ""
    h2 = ""

    def flush():
        if not section:
            return
        sig = section[:60]
        sig = guard.allow_safe(sig)
        skeleton.append(sig)
        stats["todos"] += len(bullets)
        genes.append(_gene(
            "method",
            f"文档段落：{section[:40]}",
            f"标题「{section}」下写了 {len(bullets)} 条要点："
            + ("；".join(bullets[:6]) if bullets else "（没有列表项）")
            + "。这一段是作者写下来的经验，改动相关代码前应先读这一段。",
            ["文档", "段落"],
            0.7, filename=filename, language="markdown",
        ))

    for raw in (text or "").split("\n"):
        line = raw.rstrip()
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            if level == 1:
                flush()
                h1, h2 = title, ""
                section = title
                bullets = []
            elif level == 2:
                flush()
                # 同级标题要**替换**而不是追加：
                # 否则第二个二级标题会变成「一 / 备份 / 排查」，路径越滚越长
                h2 = title
                section = f"{h1} / {h2}" if h1 else h2
                bullets = []
            continue
        b = re.match(r"^\s*[-*+]\s+(.*\S)\s*$", line)
        if b and section:
            bullets.append(_clean(b.group(1), 60))
    flush()

    return genes, skeleton, stats


# ---------- 兜底 ----------

def _distill_generic(text: str, filename: str, language: str, guard: _Guard):
    """认不出语言时的通用抽取：只拿与语言无关的经验

    注释里的待办、高危调用、疑似密钥这三类信号在任何文本里都成立，
    认出语言只是为了能讲得更清楚；认不出时也不该空手而归。
    """
    genes: list[dict] = []
    skeleton: list[str] = []
    stats = _empty_stats()
    stats["todos"] = len(_TODO_RE.findall(text or ""))
    return genes, skeleton, stats


# ---------- 主入口 ----------

def distill_code(text: str, filename: str) -> DistillResult:
    """把一份源码蒸馏成「经验基因」

    不抛异常：解析失败、编码怪异、文件超大都只降级不报错。
    蒸馏器是增强环节 —— 它坏了，源码本身还是好源码。
    """
    raw = text or ""
    warnings: list[str] = []

    sha = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()

    size = len(raw.encode("utf-8", "replace"))
    if size > MAX_BYTES:
        raw = raw.encode("utf-8", "replace")[:MAX_TAKE_BYTES].decode("utf-8", "ignore")
        warnings.append(
            f"文件超过 {MAX_BYTES // 1024 // 1024} MB，只蒸馏了前 {MAX_TAKE_BYTES // 1024} KB")

    lines = raw.split("\n")
    language = _detect_language(filename, raw)
    guard = _Guard(raw)

    if _looks_obfuscated(lines):
        warnings.append("疑似压缩/混淆代码（单行过长或平均行长异常），只保留摘要未蒸馏")
        return DistillResult(
            language=language,
            summary=f"疑似压缩或混淆的{_LANG_LABEL.get(language, language)}代码，未做结构化蒸馏",
            sha256=sha,
            lines=len(lines),
            genes=[],
            skeleton="",
            stats=_empty_stats(),
            warnings=warnings,
        )

    genes: list[dict] = []
    skeleton_lines: list[str] = []
    stats = _empty_stats()

    if language == "python":
        distiller = _PythonDistiller(raw, filename, guard)
        result = distiller.run()
        if result is None:
            # 解析失败：语言标成 unknown，并降级到与语言无关的抽取。
            # 不能直接放弃 —— 待办注释、高危调用这些信号不需要语法树也能拿到，
            # 扔掉它们等于白白丢掉半份经验。
            language = "unknown"
            warnings.append("Python 源码解析失败（语法错误或非标准语法），已降级为通用抽取")
        else:
            genes, skeleton_lines, stats = result
    elif language in ("javascript", "typescript"):
        genes, skeleton_lines, stats = _distill_js(raw, filename, language, guard)
    elif language == "shell":
        genes, skeleton_lines, stats = _distill_shell(raw, filename, guard)
    elif language == "sql":
        genes, skeleton_lines, stats = _distill_sql(raw, filename, guard)
    elif language == "config":
        genes, skeleton_lines, stats = _distill_config(raw, filename, language, guard)
    elif language == "markdown":
        genes, skeleton_lines, stats = _distill_markdown(raw, filename, guard)
    else:
        genes, skeleton_lines, stats = _distill_generic(raw, filename, language, guard)
        warnings.append(f"未能识别文件类型（判定为 {language}），只做了通用抽取")

    # 与语言无关的信号最后统一补一遍：
    # 待办注释（作者亲手写下的坑）、高危调用、疑似密钥
    todo_genes = _todo_genes(raw, filename, language, guard)
    genes += todo_genes
    stats["todos"] += len(todo_genes)
    genes += _danger_genes(raw, filename, language)
    genes += _secret_name_genes(raw, filename, language)

    # 骨架最多 12 行：这是「不抄原文」的量化边界
    skeleton_lines = skeleton_lines[:MAX_SKELETON_LINES]
    if len(skeleton_lines) > MAX_SKELETON_LINES:
        warnings.append("骨架超过 12 行，已截断")

    # 输出前过一遍闸：没登记过的源码行一律替换掉
    clean_genes: list[dict] = []
    for g in genes:
        g["content"] = guard.scrub_text(g["content"])
        clean_genes.append(g)
    genes = clean_genes

    summary = _summary(language, genes, stats, raw)
    if not genes:
        warnings.append("未能蒸馏出结构化经验")

    return DistillResult(
        language=language,
        summary=summary,
        sha256=sha,
        lines=len(lines),
        genes=genes,
        skeleton="\n".join(guard.scrub(l) for l in skeleton_lines),
        stats=stats,
        warnings=warnings,
    )


def _summary(language: str, genes: list[dict], stats: dict, raw: str) -> str:
    """一句话说清这份源码是干什么的（≤60 字）

    没有模型，只能做结构性摘要：
    有模块文档就用它开头那一句，后面补上规模；
    没有就用「定义了什么」来概括。

    规模部分按语言换词：
    说「Shell 源码（0 个函数、0 个类）」既荒唐又没信息量 ——
    脚本里根本没有函数和类，它有的是配置项与命令。
    """
    label = _LANG_LABEL.get(language, language)
    doc_line = ""
    if language == "python":
        try:
            doc_line = _first_line(ast.get_docstring(ast.parse(raw)) or "")
        except Exception:
            doc_line = ""
    if not doc_line:
        for g in genes:
            if g["kind"] == "fact" and "模块" in g["tags"]:
                doc_line = g["title"].split("：", 1)[-1]
                break

    tails = {
        "python": lambda s: f"{s['functions']} 个函数、{s['classes']} 个类、"
                            f"{s['error_paths']} 处异常路径",
        "javascript": lambda s: f"{s['functions']} 个函数、{s['classes']} 个类、"
                               f"{s['error_paths']} 处异常路径",
        "typescript": lambda s: f"{s['functions']} 个函数、{s['classes']} 个类型/类",
        "shell": lambda s: f"{s['config_keys']} 个配置项、{s['error_paths']} 处高危命令",
        "sql": lambda s: f"{s['classes']} 个表/视图、{s['config_keys']} 个索引",
        "config": lambda s: f"{s['config_keys']} 个配置项",
        "markdown": lambda s: f"{len(genes)} 个段落",
        "unknown": lambda s: f"{len(genes)} 条经验",
    }
    tail = tails.get(language, tails["unknown"])(stats)
    head = f"{label}源码：{doc_line}" if doc_line else f"{label}源码"
    return _short(f"{head}（{tail}）", 60)
