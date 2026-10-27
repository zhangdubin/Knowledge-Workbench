服务器现场排查用命令（按顺序执行，把输出贴回来）

────────────────────────────────────────
第 0 步：先把后端拉起来（它现在是停的）
────────────────────────────────────────
  cd /root/kb-workbench
  docker compose up -d --force-recreate backend
  docker compose ps

────────────────────────────────────────
第 1 步：查清「no healthcheck」到底出在哪
────────────────────────────────────────
  # ① compose 解析后的真实配置（合并了 override 文件）
  #    重点看 backend 段里有没有 healthcheck
  docker compose config | sed -n '/^  backend:/,/^  frontend:/p'

  # ② 有没有 override 文件在偷偷改配置
  ls -la docker-compose*.yml compose*.yml 2>/dev/null

  # ③ 容器真实状态
  docker ps -a --filter name=kb- --format '{{.Names}} | {{.Status}} | {{.Image}}'

  # ④ 后端容器自己的 healthcheck 与它属于哪个 compose 项目
  docker inspect kb-backend --format 'health={{json .Config.Healthcheck}}'
  docker inspect kb-backend --format 'project={{index .Config.Labels "com.docker.compose.project"}} service={{index .Config.Labels "com.docker.compose.service"}}'

  # ⑤ 后端最近报了什么
  docker compose logs backend --tail 30

────────────────────────────────────────
第 2 步：架构（决定离线包用哪个）
────────────────────────────────────────
  uname -m
  docker version --format '{{.Server.Arch}}'
