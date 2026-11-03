# -*- coding: utf-8 -*-
"""页面标题图标校验：icon-key 写的名字必须在 pageIcons.js 的表里

为什么要有这个脚本：
  PageTitle 按名字取图标，取不到就静默回退成兜底图标（工作台那个表盘）。
  这种问题用户看不出来 —— 他只看到「两个页面的标题图标长得一样」，
  比报错更难查。
  所以在构建期扫一遍：页面上写了哪个 icon-key，表里就得有哪个。

跑法：python3 scripts/verify-page-icons.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
MAP_FILE = SRC / "components" / "pageIcons.js"

# icon-key="MagicStick" / :icon-key="xxx"
ICON_KEY_RE = re.compile(r'(?<![:a-zA-Z-])icon-key\s*=\s*["\']([A-Za-z0-9]+)["\']')
# PAGE_ICONS = { A, B, C }
MAP_RE = re.compile(r'export const PAGE_ICONS = \{([^}]*)\}', re.S)


def collect_used() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in (".vue", ".js"):
            continue
        text = path.read_text(encoding="utf-8")
        for m in ICON_KEY_RE.finditer(text):
            used.setdefault(m.group(1), []).append(str(path.relative_to(ROOT)))
    return used


def collect_mapped() -> set[str]:
    text = MAP_FILE.read_text(encoding="utf-8")
    m = MAP_RE.search(text)
    if not m:
        raise SystemExit("pageIcons.js 里找不到 PAGE_ICONS 表")
    return {n.strip() for n in m.group(1).replace("\n", " ").split(",") if n.strip()}


def main() -> int:
    if not MAP_FILE.exists():
        print(f"✗ 缺少 {MAP_FILE}")
        return 1
    used = collect_used()
    mapped = collect_mapped()
    missing = {k: v for k, v in used.items() if k not in mapped}
    unused = sorted(mapped - set(used) - {"Odometer"})

    print(f"页面用到的图标：{len(used)} 个")
    print(f"图标表里的图标：{len(mapped)} 个")
    if missing:
        print("\n✗ 有 icon-key 没登记到 pageIcons.js（页面上会静默变成兜底图标）：")
        for k, files in sorted(missing.items()):
            print(f"  - {k}：{', '.join(files[:3])}")
        return 1
    if unused:
        # 不算错，只是提示：表里多了就说明有图标改名后没清理
        print(f"提示：pageIcons.js 里有 {len(unused)} 个没被任何页面用到：{' '.join(unused)}")
    print("\n✓ 页面图标全部登记在册")
    return 0


if __name__ == "__main__":
    sys.exit(main())
