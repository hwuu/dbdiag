# DBDIAG Web Console Docker Image
#
# 构建:
#   docker build -t dbdiag .
#
# 运行:
#   docker run -d -p 8000:8000 \
#     -v /path/to/config.yaml:/app/config.yaml \
#     -v /path/to/data:/app/data \
#     dbdiag
#
# 环境变量:
#   CONFIG_PATH: 配置文件路径（默认 /app/config.yaml）
#   DATA_DIR: 数据目录路径（默认 /app/data）
#
# 首次运行需要初始化数据库和导入数据:
#   docker run --rm \
#     -v /path/to/config.yaml:/app/config.yaml \
#     -v /path/to/data:/app/data \
#     -v /path/to/tickets.json:/app/tickets.json \
#     dbdiag python -m dbdiag init --db /app/data/tickets.db
#
#   docker run --rm \
#     -v /path/to/config.yaml:/app/config.yaml \
#     -v /path/to/data:/app/data \
#     -v /path/to/tickets.json:/app/tickets.json \
#     dbdiag python -m dbdiag import --data /app/tickets.json --db /app/data/tickets.db
#
#   docker run --rm \
#     -v /path/to/config.yaml:/app/config.yaml \
#     -v /path/to/data:/app/data \
#     dbdiag python -m dbdiag rebuild-index --db /app/data/tickets.db

FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY dbdiag/ ./dbdiag/

# 创建数据目录
RUN mkdir -p /app/data

# 环境变量
ENV CONFIG_PATH=/app/config.yaml
ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8000

# 启动 Web 服务
CMD ["python", "-m", "dbdiag", "web", "--host", "0.0.0.0", "--port", "8000"]
