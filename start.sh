#!/bin/bash
# 一键启动 / 停止 / 重启 知识管理工作台
set -e

cd "$(dirname "$0")"

ACTION="${1:-up}"

case "$ACTION" in
  up|start)
    echo "▶️  启动知识工作台..."
    # bind mount 的宿主机目录必须预先存在（Docker 不会自动创建），
    # 否则报 "Bind mount failed"。路径全部从 .env 读，与 compose 保持一致。
    if [ ! -f .env ]; then
      echo "❌ 缺少 .env：先执行 cp .env.example .env 并改好配置"
      exit 1
    fi
    get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r'; }
    DATA_DIR=$(get_env KB_DATA_DIR);     DATA_DIR=${DATA_DIR:-./data}
    FILES_DIR=$(get_env KB_FILE_STORE_DIR); FILES_DIR=${FILES_DIR:-./files}
    BK_DIR=$(get_env KB_BACKUP_DIR);     BK_DIR=${BK_DIR:-./backups}
    BK_ALT=$(get_env KB_BACKUP_ALT_HOST_DIR); BK_ALT=${BK_ALT:-./backups-alt}
    for d in "$DATA_DIR" "$FILES_DIR" "$BK_DIR" "$BK_ALT"; do
      mkdir -p "$d" || { echo "❌ 无法创建目录 ${d}（检查路径与权限）"; exit 1; }
    done
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
    exec "$0" up
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