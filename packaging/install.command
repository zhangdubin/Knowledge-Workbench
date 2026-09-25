#!/bin/bash
# ============================================================
#  macOS 双击入口 —— 在 Finder 里双击本文件即可安装
#  （等价于在终端执行 bash install.sh）
# ============================================================
cd "$(dirname "$0")" || exit 1

echo "知识管理工作台 · 离线安装"
echo

bash ./install.sh "$@"
RC=$?

echo
if [ "$RC" -ne 0 ]; then
  echo "✘ 安装未完成（退出码 ${RC}）"
else
  echo "✔ 安装流程结束"
fi
echo
read -n 1 -s -r -p "按任意键关闭此窗口…"
echo
exit "$RC"
