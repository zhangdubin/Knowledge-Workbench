"""笔记骨架（按笔记类型预置「要素齐全」的结构）

**为什么要这个东西**

参考样板（`云海18001-ZFAKA全链路复现与数据导出记录-20261108`）之所以好读，
靠的不只是排版 —— 是它**该有的东西一件不缺**：
最高机密横幅、TL;DR、元信息（日期/目标/类型/敏感度/历史报告）、目录、
带编号的章节、结果表、证据 callout、时间线、修复建议表、相关、变更日志。

这些「要素」跟具体内容无关，是**类型决定的**：渗透记录就该有「目标与结果 /
攻击链 / 数据落地 / 时间线 / 修复建议」，排障记录就该有「现象 / 定位 / 根因 /
修复 / 回归」。规则排不出来，是因为它不知道「你要写的是哪种笔记」。

所以这里给每种类型一份骨架：新建时选类型 → 骨架先铺好 → 填内容即可。
骨架本身是规范形态，`note_format.format_note` 再跑一遍不会变形（幂等）。

和 Obsidian 的关系：Obsidian 的 Templates 插件就是干这个的 —— 只是它的模板
是静态文本，这里的骨架会跟着 front-matter（日期/敏感度/关联）和章节编号自动对齐。
"""
from __future__ import annotations

import re
from datetime import date

from . import note_format as nf

# 每个 profile：
#   key        —— 存进 front-matter 的 scope
#   name       —— 界面上显示的名字
#   emoji      —— H1 用的图标（骨架阶段就定下来，避免和标题语义打架）
#   sensitivity—— 默认敏感度（渗透类默认 secret，其余 public）
#   sections   —— [(层级, 标题, [内容行...])]，内容行里的空字符串是空行
PROFILES: dict[str, dict] = {
    "pentest-record": {
        "key": "pentest-record",
        "name": "渗透 / 复现记录",
        "emoji": "⚔️",
        "sensitivity": "secret",
        "desc": "目标 · 攻击链 · 数据落地 · 时间线 · 修复建议",
        "sections": [
            (2, "目标与结果", [
                "> [!note] 一句话",
                "> 从哪个入口进、拿到什么、影响到哪。",
                "",
                "| 🎯 资产 | 🔌 端口 | 📦 系统 | ✅ 结果 |",
                "|:---|:---|:---|:---|",
                "|  |  |  |  |",
            ]),
            (2, "⛓️ 攻击链 / 复现步骤", [
                (3, "入口", ["", "```text", "（把入口与凭据/前置条件写在这里）", "```"]),
                (3, "提权 / 横向", ["", "```bash", "# 关键命令（可复现）", "```"]),
                (3, "取数 / 验证", ["", "证据放 `<details>` 里，长的就别摊在正文。"]),
            ]),
            (2, "📦 数据落地", [
                "| 📦 产物 | 📏 大小 | 📂 内容 | ✅ 校验 |",
                "|:---|:---|:---|:---|",
                "|  |  |  |  |",
            ]),
            (2, "🔒 证据与凭证", [
                "> [!warning] 敏感",
                "> 口令、哈希、CK 一律用 `secret-toggle` 遮盖（排版时会自动遮）。",
                "",
                "<details>",
                "<summary>🔍 展开原始响应</summary>",
                "",
                "```text",
                "（原始响应 / 截图路径 / 证据目录）",
                "```",
                "",
                "</details>",
            ]),
            (2, "⏱️ 时间线", [
                "| 🕐 时间 | 📌 事件 |",
                "|:---|:---|",
                "|  |  |",
            ]),
            (2, "🧹 未清理的残留", [
                "> [!danger] 收尾检查",
                "> 改过的库、上传的文件、加的账号 —— 逐条确认回滚了没有。",
            ]),
            (2, "🛠️ 修复建议", [
                "| 🥇 优先级 | 🔧 措施 |",
                "|:---|:---|",
                "| P0 |  |",
                "| P1 |  |",
            ]),
        ],
    },
    "troubleshoot": {
        "key": "troubleshoot",
        "name": "排障记录",
        "emoji": "🧯",
        "sensitivity": "confidential",
        "desc": "现象 · 定位 · 根因 · 修复 · 回归",
        "sections": [
            (2, "💥 现象", [
                "> [!failure] 报错原文",
                "> 把用户看到的报错原样贴进来（不要转述）。",
                "",
                "```text",
                "（报错栈 / 状态码 / 日志片段）",
                "```",
            ]),
            (2, "📦 影响范围", [
                "| 🎯 对象 | 📦 版本 | ✅ 是否受影响 |",
                "|:---|:---|:---|",
                "|  |  |  |",
            ]),
            (2, "🔍 定位过程", [
                (3, "假设 1", ["", "> [!question] 怎么证伪的", "> 跑了什么、看到什么、结论是什么。"]),
                (3, "假设 2", ["", ""]),
            ]),
            (2, "🎯 根因", [
                "> [!note] 一句话根因",
                "> 一句话说清「为什么会这样」，再展开细节。",
            ]),
            (2, "🔧 修复", [
                "```bash",
                "# 实际执行的命令",
                "```",
                "",
                "> [!tip] 回滚方式",
                "> 改坏了怎么退回去。",
            ]),
            (2, "✅ 回归验证", [
                "- [ ] 原现象不再出现",
                "- [ ] 相邻功能没被带坏",
                "- [ ] 监控/告警恢复",
            ]),
        ],
    },
    "tutorial": {
        "key": "tutorial",
        "name": "教程 / 手册",
        "emoji": "📖",
        "sensitivity": "public",
        "desc": "前置条件 · 步骤 · 验证 · 常见问题",
        "sections": [
            (2, "🎯 适用场景", ["> [!info] 给谁看", "> 什么情况下需要这份文档。"]),
            (2, "📋 前置条件", [
                "- [ ] 环境 / 权限 / 依赖",
                "- [ ] 备份与回滚点",
            ]),
            (2, "🔧 操作步骤", [
                (3, "第一步", ["", "```bash", "# 命令", "```"]),
                (3, "第二步", ["", ""]),
            ]),
            (2, "✅ 验证方法", [
                "```bash",
                "# 怎么确认做对了",
                "```",
            ]),
            (2, "❓ 常见问题", [
                "> [!question] 报错 xxx 怎么办",
                "> 原因 + 处理。",
            ]),
        ],
    },
    "generic": {
        "key": "concept",
        "name": "通用笔记",
        "emoji": "📌",
        "sensitivity": "public",
        "desc": "背景 · 结论 · 细节 · 待办",
        "sections": [
            (2, "🎯 背景", ["> [!note] 为什么记这篇", ""]),
            (2, "📌 结论 / 要点", ["- ", "- "]),
            (2, "🗂️ 细节", [""]),
            (2, "📋 待办", ["- [ ] "]),
        ],
    },
}


def list_profiles() -> list[dict]:
    """给前端下拉用的类型清单（不含骨架正文）"""
    return [
        {
            "key": p["key"],
            "name": p["name"],
            "emoji": p["emoji"],
            "desc": p["desc"],
            "sensitivity": p["sensitivity"],
        }
        for p in PROFILES.values()
    ]


def _render_sections(sections) -> list[str]:
    """(层级, 标题, 内容) 列表 → markdown 行（支持嵌套 H3）"""
    out: list[str] = []
    for item in sections:
        level, title, body = item
        if level == 3:
            out += [f"### {title}", ""]
            out += [ln for ln in body]
            out += [""]
            continue
        # 标题里已经写了 emoji 就用它（类型骨架里每个章节配什么图标是定好的，
        # 交给关键词猜反而会把「目标与结果」猜成 ✅）
        if re.match(r"^[\u2190-\u21FF\u2300-\u23FF\u25A0-\u27BF\u2900-\u297F\u2B00-\u2BFF\U0001F000-\U0001FAFF]", title):
            head = f"## {title}"
        else:
            head = f"## {nf.emoji_for_heading(title)} {title}".strip()
        out += [head, ""]
        for ln in body:
            if isinstance(ln, tuple):
                out += _render_sections([ln])
                continue
            out.append(ln)
        out += [""]
    return out


def skeleton(
    profile: str,
    *,
    title: str = "",
    tags: list[str] | None = None,
    sensitivity: str = "",
    related: list[str] | None = None,
    today: str | None = None,
) -> str:
    """生成一篇「要素齐全」的空笔记骨架

    返回的文本还会经过 `note_format.format_note()` 再排一遍 ——
    所以这里不用自己加编号、目录、变更日志，那些是排版的活。
    """
    prof = PROFILES.get(profile) or PROFILES["generic"]
    today = today or date.today().isoformat()
    sens = sensitivity or prof["sensitivity"]
    t = (title or "").strip() or "（未命名）"

    meta = {
        "title": t,
        "tags": list(tags or []),
        "created": today,
        "updated": today,
        "source": "human",
        "version": 1.0,
        "scope": prof["key"],
        "status": "active",
        "sensitivity": sens,
    }
    if related:
        meta["related"] = list(related)

    body: list[str] = [f"# {prof['emoji']} {t}".strip(), ""]

    if sens == "secret":
        body += [
            "> [!danger] 最高机密 (TOP SECRET)",
            "> 本文含真实地址、账号口令或可复现细节，**仅限内部使用**，不要外传。",
            "",
        ]
    elif sens == "confidential":
        body += [
            "> [!warning] 内部资料",
            "> 含内部信息，转发前请确认接收范围。",
            "",
        ]

    body += [
        "> [!abstract] TL;DR",
        "> （两三行说清：这是什么、结论是什么、别人最该知道哪一点）",
        "",
        "---",
        "",
    ]
    body += _render_sections(prof["sections"])

    text = nf.dump_frontmatter(meta) + "\n\n" + "\n".join(body).rstrip() + "\n"
    # 骨架也走一遍排版：编号、目录、元信息卡、分隔线、结尾要素全部对齐
    return nf.format_note(
        text, title=t, tags=tags, scope=prof["key"], sensitivity=None,
        source="human", related=related,
    )
