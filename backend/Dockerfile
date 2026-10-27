FROM python:3.12-slim

WORKDIR /app

# 镜像源（清华 PyPI）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# ==== 可选：装 git + docker CLI（只有「一键升级」用得上）====
#
# 为什么默认关闭（ARG 默认 0）：
# 绝大多数部署只用「检查更新」，那时根本不需要在容器里跑 git / docker。
# 而这两个东西不便宜：git 连 perl 一块约 40MB，docker 静态二进制约 50MB，
# 白涨镜像体积、拖慢每一次构建。只有真的要「一键升级」时才值得付这个代价。
#
# 开启方式（见 docker-compose.yml 里 backend.build.args 的注释）：
#   INSTALL_UPGRADE_TOOLS=1
# 同时必须在编排文件里把**项目目录**与 **docker.sock** 挂进后端容器 ——
# 少任何一样，「一键升级」接口都会如实报出缺什么，不会假装能升。
ARG INSTALL_UPGRADE_TOOLS=0
# docker CLI 静态二进制版本（不需要本地守护进程，只跟 docker.sock 说话）
ARG DOCKER_CLI_VERSION=27.3.1
# compose v2 插件版本。compose 是**插件**，不在上面的 tarball 里，
# 必须单独下载并放进 CLI 的插件目录，否则 `docker compose` 找不到它。
ARG DOCKER_COMPOSE_VERSION=2.29.7

RUN set -eux; \
    if [ "$INSTALL_UPGRADE_TOOLS" != "1" ]; then \
      echo "跳过 git / docker CLI 安装（INSTALL_UPGRADE_TOOLS=$INSTALL_UPGRADE_TOOLS）"; \
      exit 0; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends git ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    # 架构：优先用 buildx 注入的 TARGETARCH，退回 dpkg 的架构名
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64|x86_64) darch=x86_64 ;; \
      arm64|aarch64) darch=aarch64 ;; \
      *) echo "不支持的架构：$arch" >&2; exit 1 ;; \
    esac; \
    # 用 python 的 urllib 下载（镜像里已经有 python，不必再装 curl）
    python -c "import sys,urllib.request as u; u.urlretrieve(sys.argv[1], sys.argv[2])" \
      "https://download.docker.com/linux/static/stable/${darch}/docker-${DOCKER_CLI_VERSION}.tgz" \
      /tmp/docker.tgz; \
    tar -xzf /tmp/docker.tgz -C /tmp; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker /tmp/docker.tgz; \
    install -d /usr/local/libexec/docker/cli-plugins; \
    python -c "import sys,urllib.request as u; u.urlretrieve(sys.argv[1], sys.argv[2])" \
      "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${darch}" \
      /usr/local/libexec/docker/cli-plugins/docker-compose; \
    chmod 0755 /usr/local/libexec/docker/cli-plugins/docker-compose; \
    git --version; \
    docker --version; \
    docker compose version || echo "警告：compose 插件自检未通过（不影响镜像构建）"

# 代码
COPY . .

# 数据目录
RUN mkdir -p /app/data/uploads

EXPOSE 8000

# 健康检查写进**镜像**，不只写在 compose 的 healthcheck 里。
#
# 原因：compose 的 healthcheck 是编排文件的一项。宿主上的编排文件换了版本、
# 容器又没跟着重建，两者就对不上 —— compose 会报
#   "container kb-backend has no healthcheck configured"
# 连带把依赖它 service_healthy 的前端卡住，整个栈起不来。
#
# 写进镜像，容器从镜像创建出来就自带健康检查，
# 无论宿主上的编排文件是哪个版本都不会丢。
# compose 里显式写的 healthcheck 会覆盖这一条（值一致，无副作用）。
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
