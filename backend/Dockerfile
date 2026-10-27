# syntax=docker/dockerfile:1
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
# 是否额外装 git。**默认不装**，这是有意的：
#
#   离线包部署的自动升级路径是「下载镜像包 → docker load → compose up -d」，
#   全程用不到 git。而 git 只能从 apt 装，会连带拖进 perl 全家桶
#   （压缩 23MB、装完 122MB），还得先下 9.6MB 的 Packages 索引 ——
#   实测在慢速网络上这一步要跑十几分钟，还经常因为源抖动直接失败。
#   把 git 拆出来之后，「带工具镜像」的构建就只剩两个静态二进制
#   （docker CLI + compose 插件，都从 CDN 直下），又快又稳。
#
#   只有**源码部署**的自动升级路径（git fetch → checkout → build）才需要 git，
#   那时用 INSTALL_GIT=1 一起构建。
ARG INSTALL_GIT=0
# docker CLI 静态二进制版本（不需要本地守护进程，只跟 docker.sock 说话）
ARG DOCKER_CLI_VERSION=27.3.1
# compose v2 插件版本。compose 是**插件**，不在上面的 tarball 里，
# 必须单独下载并放进 CLI 的插件目录，否则 `docker compose` 找不到它。
ARG DOCKER_COMPOSE_VERSION=2.29.7

# 用 build secret 挂载预置的二进制，**不产生镜像层**。
#
# 为什么不是 COPY：COPY 会把 260MB 的缓存打进每一层，镜像直接涨到 1.2GB。
# secret 是挂载机制，构建完就没了，镜像里干干净净。
#
# 怎么传（构建脚本会自动做）：
#   --secret id=docker_cli,src=backend/.docker-cache/docker-cli-<arch>.tgz
#   --secret id=docker_compose,src=backend/.docker-cache/docker-compose-<arch>
# 没有也可以 —— 这时走联网下载（见下面 dl 函数）。
# 用 bind mount 把预置的二进制挂进来 —— 挂载机制，**不产生镜像层**。
#
# 为什么不用 COPY：COPY 会把 260MB 的缓存打进每一层，镜像直接涨到 1.2GB。
# 为什么不用 build secret：secret 有 500KiB 的大小上限，装不下这两个二进制
# （secret 是给令牌、证书那种小文件用的）。
# bind mount 两者都满足：不留层，也没有大小限制。
#
# 挂载源是**命名构建上下文** dockercache（构建脚本用
#   --build-context dockercache=./backend/.docker-cache 传进来）。
# 为什么用命名上下文而不是直接 source=.docker-cache：
#   .docker-cache 被 .dockerignore 排除了（不然 `COPY . .` 会把 260MB
#   的缓存拷进镜像），被排除的目录没法直接 bind mount。
# 目录是空的就照常联网下载（见下面 dl 函数）。
RUN --mount=type=bind,from=dockercache,source=.,target=/tmp/docker-cache \
    set -eux; \
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
    # git 是**可选**的：离线包部署用不到它，只有源码部署的自动升级才需要。
    # 不装 git 就完全不碰 apt —— 这一步在慢速网络上是整个构建最慢、
    # 也最容易失败的一环，能省就省。
    if [ "$INSTALL_GIT" = "1" ]; then \
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
    else \
      echo "跳过 git 安装（INSTALL_GIT=$INSTALL_GIT）—— 离线包部署的自动升级用不到它"; \
    fi; \
    # 架构：优先用 buildx 注入的 TARGETARCH，退回 dpkg 的架构名
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    # darch 是下载源用的架构名（x86_64 / aarch64），
    # dtag 是我们自己的标签名（amd64 / arm64）——
    # 预置缓存的文件名按 dtag 命名（docker-cli-amd64.tgz），别搞混了。
    case "$arch" in \
      amd64|x86_64) darch=x86_64; dtag=amd64 ;; \
      arm64|aarch64) darch=aarch64; dtag=arm64 ;; \
      *) echo "不支持的架构：$arch" >&2; exit 1 ;; \
    esac; \
    # 为什么必须重试：这条 https 链路在慢速/抖动网络上是会断的
    # （实测 urlretrieve 报 SSL: UNEXPECTED_EOF_WHILE_READING，
    #  docker CLI 和 compose 插件各断过一次）。
    # 一次 EOF 就让整个构建失败，代价太大；重试 5 次、间隔递增，基本能兜住。
    dl() { \
      _url="$1"; _dest="$2"; _n=0; \
      # urlopen 带 60 秒 socket 超时。
      # 为什么不能直接用 urlretrieve：它没有超时参数，连接一旦停滞就永远挂着
      # （实测 compose 插件的下载卡了 4 分钟不动，日志里一行都没有）。
      # 走 urlopen + copyfileobj，每个读操作都有超时，断了能立刻重试。
      until python -c "import sys,urllib.request as u,shutil as s;r=u.urlopen(sys.argv[1],timeout=60);f=open(sys.argv[2],\"wb\");s.copyfileobj(r,f);f.close()" \
        "$_url" "$_dest"; do \
        _n=$((_n+1)); \
        if [ "$_n" -ge 5 ]; then echo "下载失败（已重试 $_n 次）：$_url" >&2; exit 1; fi; \
        echo "第 $_n 次下载失败，$((_n*3)) 秒后重试：$_url" >&2; \
        sleep $((_n*3)); rm -f "$_dest"; \
      done; \
    }; \
    # 优先用构建上下文里预置好的副本（.docker-cache/）。
    # 为什么：受限网络里从公网下这两个二进制会慢到几 KB/s，还反复断
    # （实测同一份文件，宿主机 curl 13MB/s、buildkit 沙箱里 5KB/s ——
    #  差的是沙箱的网络策略，不是源）。
    # 宿主机上用 curl 断点续传下好再喂进来，是可靠得多的做法。
    # 目录里没有就照常联网下（别人克隆下来直接构建也是通的）。
    if [ -f "/tmp/docker-cache/docker-cli-${dtag}.tgz" ]; then \
      echo "用预置的 docker CLI（/tmp/docker-cache/docker-cli-${dtag}.tgz）"; \
      cp "/tmp/docker-cache/docker-cli-${dtag}.tgz" /tmp/docker.tgz; \
    else \
      dl "https://download.docker.com/linux/static/stable/${darch}/docker-${DOCKER_CLI_VERSION}.tgz" \
        /tmp/docker.tgz; \
    fi; \
    tar -xzf /tmp/docker.tgz -C /tmp; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker /tmp/docker.tgz; \
    install -d /usr/local/libexec/docker/cli-plugins; \
    if [ -f "/tmp/docker-cache/docker-compose-${dtag}" ]; then \
      echo "用预置的 compose 插件（/tmp/docker-cache/docker-compose-${dtag}）"; \
      cp "/tmp/docker-cache/docker-compose-${dtag}" \
         /usr/local/libexec/docker/cli-plugins/docker-compose; \
    else \
      dl "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${darch}" \
        /usr/local/libexec/docker/cli-plugins/docker-compose; \
    fi; \
    chmod 0755 /usr/local/libexec/docker/cli-plugins/docker-compose; \
    if [ "$INSTALL_GIT" = "1" ]; then git --version; fi; \
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
      'PDIR="${KB_INSTALL_DIR:-${KB_PROJECT_DIR:-/app/install}}"' \
      'if command -v git >/dev/null 2>&1; then' \
      '  report "git" "$(git --version 2>/dev/null || echo 本机)" 0' \
      'elif [ -d "$PDIR/.git" ]; then' \
      '  report "git" "没有装，但这是源码部署（$PDIR/.git 存在），自动升级需要它" 1' \
      'else' \
      '  report "git" "没装也没关系：离线包部署的自动升级用不到它" 0' \
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
