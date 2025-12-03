# DBDIAG Web Console Docker Image
#
# 构建:
#   docker build -t dbdiag .
#
# 运行示例（假设 config 在 /a, 数据在 /b, 数据库放 /c）:
#
# 1. 初始化数据库:
#   docker run --rm \
#     -v /a/config.yaml:/app/config.yaml \
#     -v /c:/c \
#     dbdiag python -m dbdiag init --db /c/tickets.db
#
# 2. 导入数据:
#   docker run --rm \
#     -v /a/config.yaml:/app/config.yaml \
#     -v /b/raw_tickets.json:/app/raw_tickets.json \
#     -v /c:/c \
#     dbdiag python -m dbdiag import --data /app/raw_tickets.json --db /c/tickets.db
#
# 3. 重建索引:
#   docker run --rm \
#     -v /a/config.yaml:/app/config.yaml \
#     -v /c:/c \
#     dbdiag python -m dbdiag rebuild-index --db /c/tickets.db
#
# 4. 启动 CLI:
#   docker run -it --rm \
#     -v /a/config.yaml:/app/config.yaml \
#     -v /c:/c \
#     dbdiag python -m dbdiag cli --db /c/tickets.db
#
# 5. 启动 Web 服务:
#   docker run -d -p 8000:8000 \
#     -v /a/config.yaml:/app/config.yaml \
#     -v /c:/c \
#     dbdiag python -m dbdiag web --host 0.0.0.0 --db /c/tickets.db
#
# 环境变量（可选，命令行参数优先）:
#   CONFIG_PATH: 配置文件路径
#   DB_PATH: 数据库文件完整路径
#   DATA_DIR: 数据目录路径（数据库默认为 DATA_DIR/tickets.db）

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
