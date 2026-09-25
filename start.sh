#!/bin/bash
# 一键启动 / 停止 / 重启 知识管理工作台
set -e

cd "$(dirname "$0")"

ACTION="${1:-up}"

case "$ACTION" in
  up|start)
    echo "▶️  启动知识工作台..."
    docker compose up -d --build
    echo ""
    echo "✅ 启动成功！"
    echo "   🌐 前端地址: http://localhost:8082"
    echo "   🔧 后端API:  http://localhost:8001/api/docs"
    echo "   📂 数据卷:   kb-data (Docker volume)"
    echo ""
    echo "查看日志: docker compose logs -f"
    echo "停止服务: $0 stop"
    ;;
  stop)
    echo "⏹  停止..."
    docker compose down
    ;;
  restart)
    echo "🔄 重启..."
    docker compose down
    docker compose up -d --build
    ;;
  logs)
    docker compose logs -f
    ;;
  status)
    docker compose ps
    ;;
  clean)
    echo "⚠️  即将删除所有数据（含未授权/部分存储）"
    read -p "确认？(y/N) " r
    if [[ "$r" =~ ^[Yy]$ ]]; then
      docker compose down -v
      echo "✅ 已清理"
    fi
    ;;
  rebuild)
    echo "🔨 重新构建..."
    docker compose build --no-cache
    docker compose up -d
    ;;
  *)
    echo "用法: $0 {up|stop|restart|logs|status|clean|rebuild}"
    exit 1
    ;;
esac