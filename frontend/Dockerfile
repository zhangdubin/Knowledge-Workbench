# 构建阶段
FROM node:22-alpine AS builder

WORKDIR /app

# 镜像源
RUN npm config set registry https://registry.npmmirror.com

COPY package*.json ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

# 运行阶段
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

# nginx 配置走官方镜像的 envsubst 模板机制：
# 容器启动时把 /etc/nginx/templates/*.template 里的 ${KB_*} 换成实际环境变量，
# 输出到 /etc/nginx/conf.d/。
#
# 为什么要模板而不是直接 COPY：后端地址可能要按部署现场调整
# （前端与后端不在同一个 compose 网络时），用环境变量覆盖就不必重新构建镜像。
COPY nginx.conf /etc/nginx/templates/default.conf.template

# 后端上游地址（host:port）。默认指向同一个 compose 网络里的 backend 服务；
# 覆盖它请用环境变量 KB_BACKEND_ADDR。
ENV KB_BACKEND_ADDR=backend:8000

# 只替换 KB_ 前头的变量：模板里还有 $host / $remote_addr 这些 nginx 自己的变量，
# 一并替换会把它们清空。
ENV NGINX_ENVSUBST_FILTER=^KB_

EXPOSE 80