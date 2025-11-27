# 数据库运维问题诊断助手

基于多假设追踪的智能数据库问题诊断系统，帮助运维人员快速定位数据库问题的根本原因。

## ✨ 特性

- **多假设追踪**: 并行追踪 Top-3 根因假设，动态计算置信度
- **现象级检索**: 跨工单组合诊断现象，应对新型问题
- **智能推荐**: 三阶段决策逻辑（确认/鉴别/询问），自适应引导
- **LLM 增强**: 自然语言生成诊断建议和解释
- **引用溯源**: 引用历史工单，提供诊断依据
- **知识图谱可视化**: 生成交互式 HTML 可视化根因-工单-现象关系

## 🏗️ 架构

```
dbdiag/
├── dbdiag/               # 核心业务逻辑（领域层）
│   ├── core/               # 核心逻辑
│   │   ├── retriever.py          # 现象检索 (向量+关键词)
│   │   ├── hypothesis_tracker.py # 多假设追踪
│   │   ├── recommender.py        # 推荐引擎
│   │   ├── response_generator.py # 响应生成
│   │   └── dialogue_manager.py   # 对话管理
│   ├── api/                # FastAPI 接口
│   │   ├── main.py             # FastAPI 应用入口
│   │   ├── chat.py             # 聊天 API
│   │   └── session.py          # 会话 API
│   ├── services/           # 服务层
│   │   ├── session_service.py    # 会话持久化
│   │   ├── embedding_service.py  # 向量化服务
│   │   └── llm_service.py        # LLM 调用
│   ├── models/             # 数据模型
│   └── utils/              # 工具函数
├── cli/                  # 命令行界面（应用层）
├── scripts/              # 初始化脚本
│   ├── init_db.py              # 创建数据库
│   ├── import_tickets.py       # 导入工单数据
│   ├── build_embeddings.py     # 生成向量索引
│   └── visualize_knowledge_graph.py  # 知识图谱可视化
├── tests/                # 测试
└── data/                 # 数据存储
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- SQLite 3.x
- OpenAI API Key (或兼容 API)

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

1. 复制配置模板:

```bash
cp config.yaml.example config.yaml
```

2. 编辑 `config.yaml`,填写 API 配置:

```yaml
llm:
  api_key: "your-api-key"
  base_url: "https://api.openai.com/v1"
  model: "gpt-4"

embedding_model:
  api_key: "your-api-key"
  base_url: "https://api.openai.com/v1"
  model: "text-embedding-3-large"
  dimension: 1024
```

### 初始化数据

1. 创建数据库结构:

```bash
python -m dbdiag init
```

2. 导入工单数据:

```bash
python -m dbdiag import --data data/example_tickets.json
```

3. 生成向量索引:

```bash
python -m dbdiag rebuild-index
```

### 启动服务

#### 方式 1: CLI 命令行 (推荐)

```bash
python -m dbdiag cli
```

#### 方式 2: FastAPI 服务

```bash
python -m dbdiag api
```

API 文档: http://localhost:8000/docs

## 📖 使用方法

### CLI 命令行

1. 启动交互式诊断:

```bash
python -m dbdiag cli
```

2. 输入问题描述（例如: "查询变慢"）
3. 根据系统推荐确认现象（如: "1确认 2确认 3否定"）
4. 系统自动更新假设置信度，推荐下一组现象
5. 重复 3-4 直到定位根因

**可用命令**:
- `/help` - 显示帮助信息
- `/status` - 查看当前诊断进展
- `/history` - 查看对话历史（最近5轮）
- `/reset` - 重新开始新的诊断会话
- `/exit` - 退出程序

**反馈格式**:
- `确认` / `是` - 确认所有待确认现象
- `1确认 2否定 3确认` - 批量确认/否定
- `全否定` / `都不是` - 否定所有待确认现象

### FastAPI

#### 开始对话

```bash
curl -X POST http://localhost:8000/api/chat/start \
  -H "Content-Type: application/json" \
  -d '{"user_problem": "数据库查询变慢"}'
```

#### 继续对话

```bash
curl -X POST http://localhost:8000/api/chat/continue \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess_20250125_123456_abc123",
    "user_message": "确认"
  }'
```

### 知识图谱可视化

```bash
# 默认力导向布局
python -m dbdiag visualize

# 分层布局（根因 → 工单 → 现象）
python -m dbdiag visualize --layout hierarchical

# 生成后自动打开浏览器
python -m dbdiag visualize --layout tree --open
```

## 🧪 测试

运行所有测试:

```bash
python -m pytest tests/ -v
```

运行单元测试:

```bash
python -m pytest tests/unit/ -v
```

## 🔧 命令行工具

```bash
# 查看所有命令
python -m dbdiag --help

# 初始化数据库（仅创建表结构）
python -m dbdiag init

# 导入工单数据
python -m dbdiag import --data <json文件路径>

# 重建向量索引
python -m dbdiag rebuild-index

# 启动命令行交互诊断
python -m dbdiag cli

# 启动 FastAPI 服务
python -m dbdiag api --host 0.0.0.0 --port 8000

# 生成知识图谱可视化
python -m dbdiag visualize --layout hierarchical --open
```

## 📄 许可

MIT License
