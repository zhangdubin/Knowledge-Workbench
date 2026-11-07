#!/usr/bin/env python3
"""核对「命令式 Element Plus 组件的样式」确实进了构建产物

为什么要有这个脚本：
    frontend/tests/element-plus-styles.test.mjs 守的是**源码** ——
    「引了这几个 CSS 文件」「规则写了没有」。
    但源码写了不等于产物里有：构建配置一改（换 resolver、换打包方式），
    样式照样可能不進包，源码断言却还是绿的。

    真正的失效现场是产物：dist/ 里的 CSS 有没有那几条规则。
    这个脚本直接读产物，堵住最后这一段。

背景：
    确认框曾经是**透明**的 —— Element Plus 的 message-box 样式
    压根没进包（它只出现在 JS 调用里，扫模板的 resolver 扫不到）。

用法：
    python3 scripts/verify-ep-imperative-styles.py [--dist frontend/dist]
退出码：
    0 = 全部在位；1 = 有缺失
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (说明, 必须在产物 CSS 里出现的选择器)
REQUIRED = [
    ("确认框的底色规则", ".el-message-box"),
    ("确认框的正文样式", ".el-message-box__content"),
    ("确认框按钮排布", ".el-message-box__btns"),
    ("提示条定位（fixed）", ".el-message{"),
    ("提示条的层级容器", ".el-overlay-message"),
    ("提示条的成功样式", ".el-message--success"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(ROOT / "frontend" / "dist"))
    args = ap.parse_args()

    dist = Path(args.dist)
    css_files = sorted(dist.glob("assets/*.css"))
    if not css_files:
        print(f"✘ 没找到构建产物：{dist}/assets/*.css（先跑 npm run build）")
        return 1

    blob = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in css_files)
    print(f"▸ 读了 {len(css_files)} 个 CSS 产物，共 {len(blob) / 1024:.0f} KB")

    missing = []
    for label, needle in REQUIRED:
        hit = needle in blob
        print(("  ✓ " if hit else "  ✗ ") + label + ("" if hit else f"  —— 产物里找不到 {needle!r}"))
        if not hit:
            missing.append(label)

    if missing:
        print()
        print("缺了 " + str(len(missing)) + " 项 ❌")
        print("多半是 Element Plus 命令式组件的样式没进包：")
        print("  frontend/src/main.js 里显式 import 了 el-message.css / el-message-box.css 吗？")
        return 1

    print()
    print("命令式组件的样式都在产物里 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
