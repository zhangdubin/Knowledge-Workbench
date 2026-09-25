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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
