FROM python:3.12-slim

WORKDIR /app

# 镜像源（清华 PyPI）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

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
