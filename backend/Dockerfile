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
    # 源换成 https。
    # 为什么：Debian 默认源走 http://deb.debian.org:80，这条路在不少网络里
    # 会被限速甚至掐断（实测过：同一个 Packages 文件，先 Hit 再 Err，
    # apt 直接以 100 退出，整个构建失败）。而 443 端口的 https 通路稳定得多 ——
    # 下面下载 docker CLI 和 compose 插件走的也是 https。
    # 基础镜像里已经带了 ca-certificates，apt 走 https 不需要额外装。
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list; \
    fi; \
    # apt 自带重试：Acquire::Retries=6、每条连接 30 秒超时。
    # 为什么必须开：Debian 源的可达性在很多网络里是**时断时续**的
    # （实测：同一份 Packages 先 Hit 再 Err，apt 直接以 100 退出，构建整个失败）。
    # apt 的重试是内建的，比在 shell 里套循环稳（它会复用已下载的部分）。
    apt-get -o Acquire::Retries=6 -o Acquire::http::Timeout=30 update; \
    apt-get -o Acquire::Retries=6 install -y --no-install-recommends git ca-certificates; \
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
    # compose 是**插件形态**：光把二进制放对位置不算数，
    # 必须实跑一次 `docker compose version` 出版本号才算装上了。
    #
    # 为什么这里改成「失败就中断构建」（原来是 `|| echo 警告`）：
    # 一个没有 compose 的「带工具镜像」比没有镜像更糟 —— 用户会以为
    # 工具齐了，点「一键升级」才被后端报出「没有可用的 compose 命令」，
    # 而那时他已经改了编排文件、重建了镜像。
    # 构建期就炸掉，问题只出现在真正需要这个变体的人身上。
    docker compose version

# ==== 一键升级自检 ====
#
# 为什么把自检做成镜像里的一个命令：
#   「能不能一键升级」取决于五件事（git / docker / socket / compose / 项目目录），
#   少一样都不行。让用户自己进容器里一条条试是不现实的，
#   一条 `docker exec <backend> kb-upgrade-selftest` 就能看清缺哪一样。
#
# 为什么用 printf 逐行写而不是 COPY 一个脚本文件：
#   镜像的构建上下文只有 backend/，多放一个文件就得同步维护两处；
#   而这里的内容只有几十行，printf 一次写完更省事。
RUN set -eux; \
    printf '%s\n' \
      '#!/bin/sh' \
      '# 知识工作台 · 一键升级自检' \
      '# 逐项检查「自动升级」需要的每一环，缺哪样一目了然。' \
      'ok=0; bad=0' \
      'report() {' \
      '  if [ "$3" = "0" ]; then printf "  [OK] %-14s %s\n" "$1" "$2"; ok=$((ok+1));' \
      '  else printf "  [NG] %-14s %s\n" "$1" "$2"; bad=$((bad+1)); fi' \
      '}' \
      'echo ""' \
      'echo "一键升级自检："' \
      'if command -v git >/dev/null 2>&1; then' \
      '  report "git" "$(git --version 2>/dev/null || echo 本机)" 0' \
      'else' \
      '  report "git" "没有装（镜像构建参数 INSTALL_UPGRADE_TOOLS）" 1' \
      'fi' \
      'if command -v docker >/dev/null 2>&1; then' \
      '  report "docker" "$(docker --version 2>/dev/null || echo 本机)" 0' \
      'else' \
      '  report "docker" "没有装（镜像构建参数 INSTALL_UPGRADE_TOOLS）" 1' \
      'fi' \
      'if [ -S /var/run/docker.sock ]; then' \
      '  report "docker.sock" "已挂载" 0' \
      'else' \
      '  report "docker.sock" "没挂载（编排文件里加 - /var/run/docker.sock:/var/run/docker.sock）" 1' \
      'fi' \
      'if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then' \
      '  report "compose" "$(docker compose version 2>/dev/null | head -1)" 0' \
      'else' \
      '  report "compose" "没有可用的 compose 命令（插件形态，镜像构建时没装上）" 1' \
      'fi' \
      'PDIR="${KB_INSTALL_DIR:-${KB_PROJECT_DIR:-/app/install}}"' \
      'if [ -d "$PDIR" ]; then' \
      '  report "部署目录" "$PDIR" 0' \
      'else' \
      '  report "部署目录" "$PDIR 不存在（编排文件里挂载安装目录并设 KB_INSTALL_DIR）" 1' \
      'fi' \
      'echo ""' \
      'echo "检查完毕：$ok 项通过，$bad 项缺失。"' \
      'if [ "$bad" = "0" ]; then' \
      '  echo "可以使用了：系统设置 → 升级与更新 里的一键升级"' \
      'else' \
      '  echo "一键升级暂时用不了：按上面每项后面的说明补齐即可。"' \
      'fi' \
      'exit "$bad"' \
    > /usr/local/bin/kb-upgrade-selftest; \
    chmod 0755 /usr/local/bin/kb-upgrade-selftest

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
