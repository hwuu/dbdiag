# 数据库运维问题诊断助手设计文档

## 一、背景与目标

### 1.1 项目目标

基于专家标注的数据库运维工单（tickets）数据，构建一个支持多轮自然语言交互的辅助根因定位问答助手，帮助用户快速定位数据库问题的根本原因。

### 1.2 核心特性

1. **多轮交互式诊断**：通过多轮对话逐步收集现象，缩小根因范围
2. **可溯源推理**：每个结论和操作建议必须引用具体的历史工单
3. **跨案例组合能力**：支持从多个历史案例中组合诊断现象，应对未见过的新问题
4. **动态假设追踪**：并行追踪多个可能的根因假设，动态评估和排序

### 1.3 设计理念

数据库问题诊断本质上是一个**模式匹配过程**：
- DBA 看到异常现象后，联想到历史案例中类似的现象组合
- 通过累积观察到的现象，逐步缩小根因可能性范围
- 最终在置信度足够高时给出根因判断和解决方案

**核心认知**：诊断是联想式、集合式的，而非严格线性流程。

**设计原则**：

1. **现象级检索**（Phenomenon-Level Retrieval）
   - 检索的最小单位是标准化的现象（phenomenon），而非整个工单
   - 支持从不同工单中提取相关现象进行组合

2. **上下文累积**（Context Accumulation）
   - 每轮对话累积更多已确认的现象
   - 基于累积的上下文动态调整假设和推荐

3. **多路径并行**（Multi-Hypothesis Tracking）
   - 同时追踪 Top-N 个最可能的根因假设
   - 推荐能最大程度区分不同假设的观察现象

---

## 二、系统架构

### 2.1 整体架构

```
┌───────────────────────────────────────────────────────────────┐
│                        用户交互层                             │
│     CLI (Click)  |  Web API (FastAPI)                         │
└─────────────────────────────┬─────────────────────────────────┘
                              │
┌─────────────────────────────▼─────────────────────────────────┐
│                       对话管理器                              │
│                    (DialogueManager)                          │
│                                                               │
│  ┌────────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │HypothesisTracker│  │  Recommender │  │ResponseGenerator│   │
│  │  假设追踪器    │  │  推荐引擎    │  │  响应生成器     │   │
│  └───────┬────────┘  └──────┬───────┘  └────────┬────────┘   │
│          │                  │                   │             │
│  ┌───────▼──────────────────▼───────────────────▼──────────┐ │
│  │                   Retriever 检索器                      │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────┬─────────────────────────────────┘
                              │
┌─────────────────────────────▼─────────────────────────────────┐
│                         服务层                                │
│  ┌────────────────┐  ┌────────────────┐                      │
│  │  LLMService    │  │EmbeddingService│                      │
│  │   LLM 服务     │  │  向量服务      │                      │
│  └────────────────┘  └────────────────┘                      │
└─────────────────────────────┬─────────────────────────────────┘
                              │
┌─────────────────────────────▼─────────────────────────────────┐
│                      DAO 数据访问层                           │
│  ┌─────────────┐ ┌────────────┐ ┌──────────────────────────┐ │
│  │PhenomenonDAO│ │ TicketDAO  │ │ RootCauseDAO | SessionDAO│ │
│  └─────────────┘ └────────────┘ └──────────────────────────┘ │
└─────────────────────────────┬─────────────────────────────────┘
                              │
┌─────────────────────────────▼─────────────────────────────────┐
│                      SQLite 数据库                            │
│  phenomena | tickets | ticket_phenomena | root_causes | ...   │
└───────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| **CLI 框架** | Click + Rich | 命令行界面 + 美化输出 |
| **Web 框架** | FastAPI | 轻量、异步、自动文档 |
| **数据库** | SQLite | 零配置、单文件部署 |
| **LLM** | OpenAI 兼容 API | 支持多种模型 |
| **Embedding** | OpenAI 兼容 API | 向量生成 |
| **可视化** | pyvis | 知识图谱 HTML 可视化 |

### 2.3 目录结构

```
dbdiag/
├── dbdiag/                       # 核心业务逻辑
│   ├── __init__.py
│   ├── __main__.py               # CLI 入口
│   ├── api/                      # FastAPI 接口
│   │   ├── main.py
│   │   ├── chat.py
│   │   ├── session.py
│   │   └── websocket.py          # WebSocket 实时诊断
│   ├── web/                      # Web 前端
│   │   └── static/
│   │       ├── index.html        # Web 控制台页面
│   │       └── style.css         # CLI 风格样式
│   ├── cli/                      # 命令行界面
│   │   └── main.py               # CLI/GARCLI/HybCLI/RARCLI 类
│   ├── core/                     # 核心逻辑
│   │   ├── gar/                  # GAR（图谱增强推理）
│   │   │   ├── dialogue_manager.py
│   │   │   ├── hypothesis_tracker.py
│   │   │   ├── retriever.py
│   │   │   ├── recommender.py
│   │   │   └── response_generator.py
│   │   └── rar/                  # RAR（检索增强推理）
│   │       ├── dialogue_manager.py
│   │       └── retriever.py
│   ├── dao/                      # 数据访问层
│   │   ├── base.py
│   │   ├── phenomenon_dao.py
│   │   ├── ticket_dao.py
│   │   ├── root_cause_dao.py
│   │   ├── session_dao.py
│   │   ├── raw_anomaly_dao.py
│   │   ├── raw_ticket_dao.py
│   │   └── index_builder_dao.py
│   ├── models/                   # 数据模型
│   │   ├── common.py             # 共享领域模型
│   │   ├── gar.py                # GAR 会话模型
│   │   └── rar.py                # RAR 会话模型
│   ├── services/                 # 外部服务
│   │   ├── llm_service.py
│   │   ├── embedding_service.py
│   │   └── session_service.py
│   ├── scripts/                  # 脚本
│   │   ├── init_db.py
│   │   ├── import_raw_tickets.py
│   │   ├── rebuild_index.py
│   │   └── visualize_knowledge_graph.py
│   └── utils/
│       ├── config.py
│       └── vector_utils.py
├── tests/
│   ├── unit/
│   └── e2e/
├── data/                         # 运行时数据
│   └── tickets.db
├── docs/
│   └── design.md
├── config.yaml.example
├── requirements.txt
└── README.md
```

### 2.4 对话处理流程

以下是完整的对话处理流程，展示每轮对话如何从用户输入最终定位到根因：

```
┌───────────────────────────────────────────────────────────────────────────┐
│                          对话处理总流程                                   │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│ ┌───────────────────────────────────────────────────────────────────────┐ │
│ │                      第 1 轮：开始对话                                │ │
│ ├───────────────────────────────────────────────────────────────────────┤ │
│ │ 用户输入: "查询变慢，原来几秒现在要半分钟"                            │ │
│ │                         │                                             │ │
│ │                         ▼                                             │ │
│ │ ┌───────────────────────────────────────────────────────────────────┐ │ │
│ │ │ DialogueManager.start_conversation()                              │ │ │
│ │ │   1. 创建会话 (SessionDAO)                                        │ │ │
│ │ │   2. 提取事实 → confirmed_facts                                   │ │ │
│ │ │   3. 检索相关现象 (Retriever)                                     │ │ │
│ │ │   4. 生成初始假设 (HypothesisTracker)                             │ │ │
│ │ │   5. 推荐首批现象 (Recommender)                                   │ │ │
│ │ └───────────────────────────────────────────────────────────────────┘ │ │
│ │                         │                                             │ │
│ │                         ▼                                             │ │
│ │ 输出: 推荐 3 个现象 + 假设置信度列表                                  │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
│                             │                                             │
│                             ▼                                             │
│ ┌───────────────────────────────────────────────────────────────────────┐ │
│ │                    第 2-N 轮：继续对话                                │ │
│ ├───────────────────────────────────────────────────────────────────────┤ │
│ │ 用户输入: "1确认 2确认 3否定"                                         │ │
│ │                         │                                             │ │
│ │                         ▼                                             │ │
│ │ ┌───────────────────────────────────────────────────────────────────┐ │ │
│ │ │ DialogueManager.continue_conversation()                           │ │ │
│ │ │                                                                   │ │ │
│ │ │   1. 解析用户反馈                                                 │ │ │
│ │ │      └─> 更新 confirmed_phenomena / denied_phenomena              │ │ │
│ │ │                                                                   │ │ │
│ │ │   2. 重新计算假设置信度 (HypothesisTracker)                       │ │ │
│ │ │      ├─> 事实匹配度 (LLM 评估)        权重 50%                    │ │ │
│ │ │      ├─> 现象确认进度                 权重 30%                    │ │ │
│ │ │      ├─> 根因流行度                   权重 10%                    │ │ │
│ │ │      ├─> 问题描述相似度               权重 10%                    │ │ │
│ │ │      └─> 否定惩罚 (每个否定现象 -15%)                             │ │ │
│ │ │                                                                   │ │ │
│ │ │   3. 决策分支 (Recommender)                                       │ │ │
│ │ │      ├─> 置信度 > 85%: 确认根因 → 生成诊断总结                    │ │ │
│ │ │      └─> 置信度 < 85%: 推荐下一批区分性现象                       │ │ │
│ │ └───────────────────────────────────────────────────────────────────┘ │ │
│ │                         │                                             │ │
│ │                         ▼                                             │ │
│ │ 输出: 推荐更多现象 或 诊断结论                                        │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
│                             │                                             │
│                             ▼                                             │
│ ┌───────────────────────────────────────────────────────────────────────┐ │
│ │                      根因定位完成                                     │ │
│ ├───────────────────────────────────────────────────────────────────────┤ │
│ │ 当 top_hypothesis.confidence > 0.85 时:                               │ │
│ │                                                                       │ │
│ │ ResponseGenerator.generate_diagnosis_summary()                        │ │
│ │   ├─> 观察到的现象（confirmed_phenomena）                             │ │
│ │   ├─> 推理链路（LLM 生成）                                            │ │
│ │   ├─> 恢复措施（从 root_causes.solution）                             │ │
│ │   └─> 引用工单（supporting_ticket_ids）                               │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

**模块调用关系**：

```
DialogueManager (入口)
    │
    ├─> SessionDAO          # 会话持久化
    │
    ├─> Retriever           # 现象检索
    │       │
    │       ├─> EmbeddingService    # 生成查询向量
    │       └─> PhenomenonDAO       # 读取现象库
    │
    ├─> HypothesisTracker   # 假设管理
    │       │
    │       ├─> LLMService          # 评估事实支持度
    │       ├─> TicketDAO           # 获取支持工单
    │       └─> RootCauseDAO        # 获取根因信息
    │
    ├─> Recommender         # 推荐决策
    │       │
    │       └─> TicketPhenomenonDAO  # 获取现象-工单关联
    │
    └─> ResponseGenerator   # 生成响应
            │
            └─> LLMService          # 生成诊断总结
```

**关键决策点**：

| 阶段 | 条件 | 动作 |
|------|------|------|
| 初始 | 无假设 | 检索相关现象，生成初始假设 |
| 中间 | 置信度 < 85% | 推荐区分性现象，继续收集证据 |
| 结束 | 置信度 ≥ 85% | 确认根因，生成诊断总结 |

---

## 三、数据模型

### 3.1 数据库表设计

系统采用**原始数据与处理后数据分离**的设计：

```
原始工单数据（专家标注）
    │
    ▼ import
    │
原始数据表（raw_tickets, raw_anomalies）
    │
    ▼ rebuild-index（聚类 + LLM 标准化）
    │  ├─> raw_root_causes（从 raw_tickets 提取去重）
    │  ├─> phenomena（异常聚类标准化）
    │  └─> root_causes（根因聚类标准化）
    │
处理后数据表（phenomena, tickets, ticket_phenomena, root_causes, phenomenon_root_causes）
```

#### 3.1.1 原始数据表

**raw_tickets** - 原始工单：

| 字段 | 类型 | 说明 |
|------|------|------|
| ticket_id | TEXT PK | 工单 ID |
| metadata_json | TEXT | 元数据 JSON |
| description | TEXT | 问题描述 |
| root_cause | TEXT | 根因 |
| solution | TEXT | 解决方案 |

**raw_anomalies** - 原始异常：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | 格式: {ticket_id}_anomaly_{index} |
| ticket_id | TEXT FK | 关联工单 |
| anomaly_index | INTEGER | 序号 |
| description | TEXT | 异常描述 |
| observation_method | TEXT | 观察方法 |
| why_relevant | TEXT | 相关性解释 |

**raw_root_causes** - 原始根因（从 raw_tickets 提取去重）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | 格式: RRC-{序号} |
| description | TEXT | 原始根因描述 |
| solution | TEXT | 原始解决方案 |
| source_ticket_ids | TEXT | 来源工单 ID（JSON 数组） |
| ticket_count | INTEGER | 工单数量 |
| embedding | BLOB | 向量表示（用于聚类） |

#### 3.1.2 处理后数据表

**phenomena** - 标准现象库（核心表）：

| 字段 | 类型 | 说明 |
|------|------|------|
| phenomenon_id | TEXT PK | 格式: P-{序号} |
| description | TEXT | 标准化描述（LLM 生成） |
| observation_method | TEXT | 观察方法 |
| source_anomaly_ids | TEXT | 来源异常 ID（JSON 数组） |
| cluster_size | INTEGER | 聚类大小 |
| embedding | BLOB | 向量表示 |

**root_causes** - 根因表（聚类标准化后）：

| 字段 | 类型 | 说明 |
|------|------|------|
| root_cause_id | TEXT PK | 格式: RC-{序号} |
| description | TEXT | 标准化根因描述（LLM 生成） |
| solution | TEXT | 标准化解决方案（LLM 合并） |
| source_raw_root_cause_ids | TEXT | 来源原始根因 ID（JSON 数组） |
| cluster_size | INTEGER | 聚类大小 |
| key_phenomenon_ids | TEXT | 关键现象 ID（JSON） |
| related_ticket_ids | TEXT | 相关工单 ID（JSON） |
| ticket_count | INTEGER | 工单数量 |
| embedding | BLOB | 向量表示 |

**tickets** - 处理后工单表：

| 字段 | 类型 | 说明 |
|------|------|------|
| ticket_id | TEXT PK | 工单 ID |
| description | TEXT | 问题描述 |
| root_cause_id | TEXT FK | 关联根因 |
| root_cause | TEXT | 根因描述（冗余） |
| solution | TEXT | 解决方案 |

**ticket_phenomena** - 工单-现象关联表：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | 关联 ID |
| ticket_id | TEXT FK | 工单 ID |
| phenomenon_id | TEXT FK | 现象 ID |
| why_relevant | TEXT | 该工单上下文中的相关性 |
| raw_anomaly_id | TEXT FK | 原始异常 ID（溯源） |

**phenomenon_root_causes** - 现象-根因关联表：

| 字段 | 类型 | 说明 |
|------|------|------|
| phenomenon_id | TEXT PK | 现象 ID |
| root_cause_id | TEXT PK | 根因 ID |
| ticket_count | INTEGER | 关联工单数量 |

#### 3.1.3 数据关系图

```
┌───────────────────────────────────────────────────────────────┐
│                          tickets                              │
│                       (T-0001, ...)                           │
└─────────────────────────────┬─────────────────────────────────┘
                              │ 1:N
                              ▼
┌───────────────────────────────────────────────────────────────┐
│                     ticket_phenomena                          │
│           (ticket_id, phenomenon_id, why_relevant)            │
└─────────────────────────────┬─────────────────────────────────┘
                              │ N:1
                              ▼
┌───────────────────────────────────────────────────────────────┐
│                        phenomena                              │
│                       (P-0001, ...)                           │
└─────────────────────────────┬─────────────────────────────────┘
                              │ 1:N
                              ▼
┌───────────────────────────────────────────────────────────────┐
│                  phenomenon_root_causes                       │
│         (phenomenon_id, root_cause_id, ticket_count)          │
└─────────────────────────────┬─────────────────────────────────┘
                              │ N:1
                              ▼
┌───────────────────────────────────────────────────────────────┐
│                       root_causes                             │
│                       (RC-0001, ...)                          │
└───────────────────────────────────────────────────────────────┘
```

**关系说明**：
- 一个 `ticket` 观察到多个 `phenomena`（通过 `ticket_phenomena`，N:M）
- 一个 `phenomenon` 支持多个 `root_causes`（通过 `phenomenon_root_causes`，N:M）
- `phenomenon_root_causes.ticket_count` 记录该现象在多少工单中支持该根因

#### 3.1.4 数据示例

**原始数据**（2个工单，共享相似的异常现象）：

```yaml
# 工单 1
ticket_id: T-0001
description: "报表查询变慢"
root_cause: "索引膨胀导致 IO 瓶颈"
anomalies:
  - description: "wait_io 事件占比 65%"      # 相似 ─┐
  - description: "索引大小增长 6 倍"          #      │
                                              #      │
# 工单 2                                      #      │
ticket_id: T-0002                             #      │
description: "定时任务执行慢"                  #      │
root_cause: "索引膨胀导致 IO 瓶颈"            #      │
anomalies:                                    #      │
  - description: "wait_io 占比达 70%"         # 相似 ─┘（聚类到同一现象）
  - description: "表膨胀严重"
```

**rebuild-index 后生成**：

```
┌───────────────────────────────────────────────────────────────────────────┐
│                               tickets                                     │
├───────────────────────────────────────────────────────────────────────────┤
│  T-0001                              │  T-0002                            │
│  description: "Report query slow"    │  description: "Scheduled job slow" │
│  root_cause_id: RC-0001              │  root_cause_id: RC-0001            │
└──────────────────┬───────────────────┴──────────────────┬─────────────────┘
                   │                                      │
                   ▼                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                          ticket_phenomena                                 │
├───────────────────────────────────────────────────────────────────────────┤
│  T-0001 → P-0001 (wait_io)           │  T-0002 → P-0001 (wait_io)         │
│  T-0001 → P-0002 (index growth)      │  T-0002 → P-0003 (table bloat)     │
└──────────────────┬───────────────────┴──────────────────┬─────────────────┘
                   │                                      │
                   └─────────────────┬────────────────────┘
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                             phenomena                                     │
├───────────────────────────────────────────────────────────────────────────┤
│  P-0001: "wait_io ratio exceeds threshold"   ← Clustered from T-0001+0002 │
│          cluster_size: 2                                                  │
├───────────────────────────────────────────────────────────────────────────┤
│  P-0002: "Index size abnormal growth"        ← From T-0001 only           │
│          cluster_size: 1                                                  │
├───────────────────────────────────────────────────────────────────────────┤
│  P-0003: "Table bloat severe"                ← From T-0002 only           │
│          cluster_size: 1                                                  │
└───────────────────────────────────────┬───────────────────────────────────┘
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                        phenomenon_root_causes                             │
├───────────────────────────────────────────────────────────────────────────┤
│  P-0001 → RC-0001 (ticket_count: 2)                                       │
│  P-0002 → RC-0001 (ticket_count: 1)                                       │
│  P-0003 → RC-0001 (ticket_count: 1)                                       │
└───────────────────────────────────────┬───────────────────────────────────┘
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                             root_causes                                   │
├───────────────────────────────────────────────────────────────────────────┤
│  RC-0001: "Index bloat causing IO bottleneck"                             │
│           ticket_count: 2                                                 │
│           solution: "REINDEX, configure autovacuum"                       │
└───────────────────────────────────────────────────────────────────────────┘
```

**关键点**：
- 数据流向：`tickets → phenomena → root_causes`
- `P-0001` 由两个相似的异常聚类生成（`cluster_size: 2`）
- 两个工单共享 `P-0001`，体现"现象复用"
- `phenomenon_root_causes` 记录每个现象支持哪些根因

### 3.2 会话状态结构

会话状态存储在 `sessions` 表，核心字段以 JSON 格式保存：

```python
class SessionState:
    session_id: str                              # 会话 ID
    user_problem: str                            # 用户问题描述

    confirmed_facts: List[ConfirmedFact]         # 已确认事实
    confirmed_phenomena: List[ConfirmedPhenomenon]  # 已确认现象
    denied_phenomena: List[DeniedPhenomenon]     # 已否定现象
    recommended_phenomena: List[RecommendedPhenomenon]  # 已推荐现象

    active_hypotheses: List[Hypothesis]          # 活跃假设（Top-3）
    dialogue_history: List[DialogueMessage]      # 对话历史

class Hypothesis:
    root_cause_id: str                           # 根因 ID
    confidence: float                            # 置信度 0-1
    supporting_phenomenon_ids: List[str]         # 支持现象
    supporting_ticket_ids: List[str]             # 支持工单
    missing_phenomena: List[str]                 # 缺失现象描述
```

---

## 四、核心模块

### 4.1 检索器 (PhenomenonRetriever)

**文件**: `dbdiag/core/gar/retriever.py`

**职责**: 基于用户输入检索相关的标准现象。

**主要流程**:

```
用户输入
    │
    ▼
生成查询向量 (EmbeddingService)
    │
    ▼
向量相似度检索 (top_k=50)
    │
    ▼
关键词过滤（提高精确度）
    │
    ▼
多因素重排序
    │
    ▼
返回 Top-N 现象
```

**核心方法**:

```python
def retrieve(
    self,
    query: str,
    top_k: int = 10,
    excluded_phenomenon_ids: Set[str] = None,
) -> List[Tuple[Phenomenon, float]]:
    """
    检索相关现象

    Args:
        query: 查询文本
        top_k: 返回数量
        excluded_phenomenon_ids: 排除的现象 ID

    Returns:
        (现象, 得分) 列表
    """
```

**重排序评分公式**:

```
final_score = 0.5 * fact_coverage + 0.3 * vector_score + 0.2 * novelty
```

### 4.2 假设追踪器 (PhenomenonHypothesisTracker)

**文件**: `dbdiag/core/gar/hypothesis_tracker.py`

**职责**: 维护多个并行的根因假设，动态计算和更新置信度。

**主要流程**:

```
用户反馈（确认/否定现象）
    │
    ▼
更新 confirmed_phenomena / denied_phenomena
    │
    ▼
检索根因候选 (根据确认的现象)
    │
    ▼
对每个根因计算置信度
    │
    ▼
保留 Top-3 假设
```

**置信度计算公式**:

```python
def _compute_confidence(root_cause_id, supporting_phenomena, confirmed_phenomena, denied_phenomenon_ids):
    # 1. 现象确认进度（权重 60%）
    # 查询该根因关联的所有现象，计算确认的相关现象占比
    related_phenomenon_ids = get_phenomena_for_root_cause(root_cause_id)
    confirmed_relevant_count = len(confirmed_ids & related_phenomenon_ids)
    total_for_root_cause = max(len(related_phenomenon_ids), 1)
    progress = confirmed_relevant_count / total_for_root_cause

    # 2. 根因流行度（权重 20%）- 支持该根因的现象越多，流行度越高
    frequency_score = min(len(supporting_phenomena) / 5, 1.0)

    # 3. 基础相关性（权重 20%）- 当有确认时给满分
    relevance_score = 1.0 if confirmed_relevant_count > 0 else 0.5

    # 综合计算
    confidence = 0.6 * progress + 0.2 * frequency_score + 0.2 * relevance_score

    # 4. 否定惩罚：每个被否定的相关现象降低 15% 置信度
    denied_relevant_count = len(denied_phenomenon_ids & related_phenomenon_ids)
    if denied_relevant_count > 0:
        denial_penalty = denied_relevant_count * 0.15
        confidence = confidence * (1 - denial_penalty)

    return min(max(confidence, 0.0), 1.0)
```

### 4.3 推荐引擎 (PhenomenonRecommendationEngine)

**文件**: `dbdiag/core/gar/recommender.py`

**职责**: 根据当前假设状态，推荐下一波需要观察的现象。

#### 4.3.1 推荐流程

```
session.active_hypotheses（已在 hypothesis_tracker 中检索过）
    │
    ▼
1. 从活跃假设获取相关根因集合
    │
    ▼
2. 扩展：获取这些根因的所有关联现象 (candidate_phenomena)
    │
    ▼
3. 过滤：排除已确认/已否认的现象
    │
    ▼
4. 打分：计算每个现象的推荐得分
    │
    ▼
5. 返回 top-n 现象 (n=3)
```

#### 4.3.2 现象推荐得分公式

```python
def score(p):
    return (
        0.15 * popularity(p) +
        0.20 * specificity(p) +
        0.40 * hypothesis_priority(p) +
        0.25 * information_gain(p)
    )
```

#### 4.3.3 各因素计算

设现象 p 关联的根因集合为 `R_p`

**1. popularity(p) - 流行度**

现象关联的根因中，最高的流行度。流行度高的根因更可能是真正的原因。

```python
def popularity(p):
    """关联根因中最高的流行度"""
    return max(ticket_count(r) / max_ticket_count for r in R_p)
```

**2. specificity(p) - 特异性**

关联的根因越少，特异性越高。高特异性现象确认/否认后能更精确地定位根因。

```python
def specificity(p):
    """关联根因越少，特异性越高"""
    return 1 / len(R_p)
```

**3. hypothesis_priority(p) - 假设优先级**

关联根因的置信度，加权 ticket_count。票数越多支持越强。

```python
def hypothesis_priority(p):
    """关联根因的置信度，加权 ticket_count"""
    max_priority = 0.0
    for r in R_p:
        confidence = get_confidence(r)
        # 使用 sqrt 平滑，避免票数差异过大导致的极端影响
        ticket_count = get_ticket_count_for_phenomenon(p, r)
        support_weight = (ticket_count / max_ticket_count) ** 0.5
        # 综合得分 = 置信度 * 支持权重
        weighted_priority = confidence * (0.7 + 0.3 * support_weight)
        max_priority = max(max_priority, weighted_priority)
    return max_priority
```

**4. information_gain(p) - 信息增益**

综合确认收益和区分能力。

```python
def information_gain(p):
    """确认收益 + 区分能力"""
    return 0.6 * confirmation_gain(p) + 0.4 * discrimination_power(p)
```

**confirmation_gain(p) - 确认收益**

确认该现象对 top 假设的置信度提升空间。

```python
def confirmation_gain(p):
    """确认 p 对 top 假设的置信度提升空间"""
    if top_hypothesis.root_cause_id in R_p:
        total = len(all_phenomena_of(top_hypothesis))
        confirmed = len(confirmed_phenomena_of(top_hypothesis))
        return 1 - confirmed / total  # 还有多少增长空间
    return 0
```

**discrimination_power(p) - 区分能力**

该现象能否有效区分 top-1 和 top-2 假设。

```python
def discrimination_power(p):
    """p 能否区分 top-1 和 top-2 假设"""
    if len(active_hypotheses) < 2:
        return 0

    top1, top2 = active_hypotheses[0], active_hypotheses[1]
    top1_related = top1.root_cause_id in R_p
    top2_related = top2.root_cause_id in R_p

    if top1_related and not top2_related:
        return 1.0  # 只与 top1 相关，完美区分
    elif not top1_related and top2_related:
        return 0.8  # 只与 top2 相关，可排除
    elif top1_related and top2_related:
        return 0.2  # 都相关，区分度低
    else:
        return 0.1  # 都不相关
```

#### 4.3.4 决策逻辑

```python
def recommend_next_action(session):
    if not session.active_hypotheses:
        return ask_for_initial_info()

    top_hypothesis = session.active_hypotheses[0]

    # 高置信度 -> 确认根因
    if top_hypothesis.confidence >= 0.80:
        return generate_root_cause_confirmation(top_hypothesis)

    # 收集并推荐现象
    recommended = recommend_phenomena(session, n=3)
    if recommended:
        return generate_recommendation(recommended)

    # 中等置信度但无更多现象 -> 也确认根因
    if top_hypothesis.confidence >= 0.50:
        return generate_root_cause_confirmation(top_hypothesis)

    return ask_for_more_info()
```

#### 4.3.5 完整推荐流程伪代码

```python
def recommend_phenomena(session, n=3):
    # 1. 从活跃假设获取相关根因（已在 hypothesis_tracker 中检索过）
    relevant_root_causes = {h.root_cause_id for h in session.active_hypotheses}

    # 2. 扩展到所有关联现象
    candidates = set()
    for r in relevant_root_causes:
        candidates.update(get_phenomena_of(r))

    # 3. 排除已确认/已否认
    candidates -= confirmed_ids
    candidates -= denied_ids

    # 4. 计算得分，返回 top-n
    scored = [(p, score(p)) for p in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:n]
```

### 4.4 响应生成器 (ResponseGenerator)

**文件**: `dbdiag/core/gar/response_generator.py`

**职责**: 使用 LLM 生成用户可读的诊断响应。

**主要方法**:

```python
def generate_diagnosis_summary(
    root_cause: str,
    confirmed_phenomena: List[ConfirmedPhenomenon],
    solution: str,
    ticket_ids: List[str],
) -> str:
    """
    生成诊断总结

    包含：
    - 观察到的现象
    - 推理链路
    - 恢复措施
    - 引用工单
    """
```

**响应格式示例**:

```
**根因已定位：索引膨胀导致 IO 瓶颈** (置信度: 88%)

**观察到的现象：**
1. wait_io 事件占比 65%
2. 索引 test_idx 从 2GB 增长到 12GB

**推理链路：**
高 IO 等待通常由磁盘读写瓶颈导致...

**恢复措施：**
1. REINDEX INDEX CONCURRENTLY test_idx;
2. 配置 autovacuum 参数

**引用工单：** [T-0001] [T-0005]
```

### 4.5 对话管理

系统支持三种诊断方法，各有特点：

| 方法 | 文件 | 特点 |
|------|------|------|
| GAR（图谱增强推理） | `core/gar/dialogue_manager.py` | 确定性算法，可解释性强 |
| RAR（检索增强推理） | `core/rar/dialogue_manager.py` | LLM 端到端，灵活性高 |
| Hyb（混合增强推理） | `core/gar/dialogue_manager.py` (hybrid_mode=True) | GAR 架构 + RAR 能力 |

#### 4.5.1 图谱增强推理 (GAR)

**文件**: `dbdiag/core/gar/dialogue_manager.py`

**总览：GAR 流程**

```
┌─────────────────────────────────────────────────────────────────────────┐
│                               GAR Flow                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌────────────┐  ┌───────────┐  ┌───────────┐  ┌─────────────┐          │
│  │ User Input │→ │ Retriever │→ │ Hypothesis│→ │ Recommender │          │
│  └────────────┘  │(Phenomena)│  │  Tracker  │  │  (Decide)   │          │
│                  └───────────┘  └───────────┘  └─────────────┘          │
│                        ↓              ↓                                 │
│                  Vector Search   Confidence Calc                        │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Feedback: Keyword Matching ("1confirm 2deny", "confirm", etc.)  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**主要流程**:

```
start_conversation(user_problem)
    │
    ├─> 创建会话
    ├─> 检索相关现象 (Retriever)
    ├─> 初始化假设 (HypothesisTracker)
    └─> 返回首轮推荐 (Recommender)

continue_conversation(session_id, user_message)
    │
    ├─> 解析用户反馈（关键词匹配）
    ├─> 更新 confirmed_phenomena / denied_phenomena
    ├─> 重新计算假设置信度 (HypothesisTracker)
    ├─> 生成下一步推荐或诊断结论 (Recommender)
    └─> 返回响应
```

**核心方法**:

```python
class GARDialogueManager:
    def __init__(
        self, db_path, llm_service, embedding_service,
        hybrid_mode: bool = False  # 混合增强模式
    ):
        self.hypothesis_tracker = PhenomenonHypothesisTracker(...)
        self.recommender = PhenomenonRecommendationEngine(...)
        self.response_generator = ResponseGenerator(...)
        self.session_dao = SessionDAO(db_path)
        self.hybrid_mode = hybrid_mode

    def start_conversation(self, user_problem: str) -> Dict:
        """开始新对话"""

    def continue_conversation(self, session_id: str, user_message: str) -> Dict:
        """继续对话"""
```

**核心特点**：
- 基于预处理的 `phenomena`、`root_causes`、`phenomenon_root_causes` 表
- 确定性算法计算置信度（见 4.2 HypothesisTracker）
- 多因素打分推荐现象（见 4.3 Recommender）
- 用户反馈通过关键词匹配解析

#### 4.5.2 检索增强推理 (RAR)

**文件**: `dbdiag/core/rar/dialogue_manager.py`

**总览：RAR 流程**

```
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
│                                RAR Flow                                 │
├ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
│                                                                         │
│  ┌ ─ ─ ─ ─ ─ ─ ┐  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ┐  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐    │
│  │ User Input  │→ │  RAG Retrieval  │→ │ LLM End-to-End Reasoning  │    │
│  └ ─ ─ ─ ─ ─ ─ ┘  │ rar_raw_tickets │  │ Recommend / Diagnose      │    │
│                   └ ─ ─ ─ ─ ─ ─ ─ ─ ┘  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘    │
│                          ↓                          ↓                   │
│                   Vector Search            LLM Confidence Judge         │
│                                                     ↓                   │
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐    │
│  │ Feedback: LLM Free Understanding (No Structured Constraints)    │    │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘    │
│                                                                         │
└ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
```

**主要流程**:

```
process_message(user_message)
    │
    ├─> [Step 1] RAG 检索相关工单
    │       │   - 向量检索 rar_raw_tickets
    │       │   - 返回 Top-10 相似工单
    │
    ├─> [Step 2] 构建 LLM Prompt
    │       │   - 用户问题 + 当前状态 + 相关工单
    │       │   - Top 3 工单：完整内容
    │       │   - Top 4-10：精简摘要
    │
    ├─> [Step 3] LLM 推理
    │       │   - 输出 JSON: action + confidence + reasoning
    │       │   - action = "recommend" 或 "diagnose"
    │
    ├─> [Step 4] Guardrails 校验
    │       │   - 过滤已问过的观察（避免重复推荐）
    │       │   - 验证引用的工单确实存在
    │
    └─> [Step 5] 轮次检查
            │   - 超过 max_turns (5轮) 强制诊断
```

**LLM 输出格式**:

```json
// 推荐模式
{
  "action": "recommend",
  "confidence": 0.45,
  "reasoning": "用户描述了查询变慢，但缺少 IO、锁等关键观察...",
  "recommendations": [
    {
      "observation": "wait_io 事件占比",
      "method": "SELECT wait_event_type, count(*) FROM pg_stat_activity...",
      "why": "高 IO 等待通常与索引膨胀相关",
      "related_root_causes": ["索引膨胀", "磁盘 IO 瓶颈"]
    }
  ]
}

// 诊断模式
{
  "action": "diagnose",
  "confidence": 0.85,
  "root_cause": "索引膨胀导致 IO 瓶颈",
  "reasoning": "用户确认了 wait_io 高、索引增长异常...",
  "observed_phenomena": ["wait_io 占比 65%", "索引从 2GB 增长到 12GB"],
  "solution": "1. REINDEX INDEX CONCURRENTLY...",
  "cited_tickets": ["T-0001", "T-0018"]
}
```

**核心特点**：
- 直接使用 `rar_raw_tickets` 原始数据（无需预处理）
- LLM 端到端推理，自由组合信息
- 高度灵活但行为不可预测
- 需要 Guardrails 防止幻觉

#### 4.5.3 混合增强推理 (Hyb)

Hyb 结合了 GAR 的可靠性和 RAR 的灵活性。

**文件**: `dbdiag/core/gar/dialogue_manager.py` (hybrid_mode=True)

**总览：Hyb = GAR 架构 + RAR 能力**

```
┌──────────────────────────────────────────────────────────────────────────┐
│               Hyb Flow = GAR Architecture + RAR Capabilities             │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ╔════════════════════════════════════════════════════════════════════╗  │
│  ║ [From RAR] Initial Semantic Retrieval                              ║  │
│  ║   ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐    ║  │
│  ║   │ User Query → Search rar_raw_tickets → Extract → Add Pool  │    ║  │
│  ║   └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘    ║  │
│  ╚════════════════════════════════════════════════════════════════════╝  │
│                                     ↓                                    │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ [From GAR] Core Reasoning Flow                                     │  │
│  │                                                                    │  │
│  │  ┌────────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐       │  │
│  │  │ User Input │→ │ Retriever │→ │ Hypothesis│→ │Recommender│       │  │
│  │  └────────────┘  │(Phenomena)│  │  Tracker  │  │ (Decide)  │       │  │
│  │                  └───────────┘  └───────────┘  └───────────┘       │  │
│  │                        ↓              ↓                            │  │
│  │                  Vector Search   Confidence Calc                   │  │
│  │                                                                    │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                     ↓                                    │
│  ╔════════════════════════════════════════════════════════════════════╗  │
│  ║ [From RAR] Enhanced Feedback Understanding                         ║  │
│  ║                                                                    ║  │
│  ║  Simple Format ──→ Fast Path (Keyword Matching, from GAR)          ║  │
│  ║  ("1confirm 2deny")                                                ║  │
│  ║                  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐ ║  │
│  ║  Natural Lang ─→ │ LLM Structured Extraction (RAR Semantic)      │ ║  │
│  ║  ("IO normal,    │    ↓                                          │ ║  │
│  ║   index grew")   │ { feedback: {...}, new_observations: [...] }  │ ║  │
│  ║                  │                      ↓                        │ ║  │
│  ║                  │ If new_obs → Semantic Retrieval → Add Pool    │ ║  │
│  ║                  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘ ║  │
│  ╚════════════════════════════════════════════════════════════════════╝  │
│                                                                          │
│  Legend: ┌───┐ From GAR        ╔═══╗ Hyb Enhancement Layer               │
│          └───┘ (Deterministic) ╚═══╝                                     │
│          ┌ ─ ┐ From RAR                                                  │
│          └ ─ ┘ (Semantic/LLM)                                            │
└──────────────────────────────────────────────────────────────────────────┘
```

**初始轮：语义检索增强**

```
用户问题: "查询变慢，原来几秒现在要半分钟"
    │
    ▼
[Step 1] 语义检索相似工单 (search_by_ticket_description)
    │   - 使用 rar_raw_tickets 表的向量索引
    │   - 返回 Top-5 相似工单
    │
    ▼
[Step 2] 提取候选现象 (get_phenomena_by_ticket_ids)
    │   - 从相似工单关联的 ticket_phenomena 提取现象
    │   - 存入 session.hybrid_candidate_phenomenon_ids
    │
    ▼
[后续流程] 与标准 GAR 相同
```

**中间轮：LLM 反馈理解 + 动态检索**

当用户提供自然语言反馈（而非简单的 "1确认 2否定"）时：

```
用户反馈: "IO 正常，索引涨了 6 倍，另外发现很多慢查询"
    │
    ▼
[Step 1] LLM 结构化提取
    │   输出: {
    │     "feedback": {"P-0001": "denied", "P-0002": "confirmed", ...},
    │     "new_observations": ["发现很多慢查询"]
    │   }
    │
    ▼
[Step 2] 处理确认/否定
    │   - 更新 session.confirmed_phenomena
    │   - 更新 session.denied_phenomena
    │
    ▼
[Step 3] 若有 new_observations
    │   - 语义检索相似工单（基于新观察）
    │   - 提取候选现象，合并到 session.hybrid_candidate_phenomenon_ids
    │   - 记录到 session.new_observations
    │
    ▼
[后续流程] 更新假设 + 生成推荐
```

**会话状态扩展**:

```python
class SessionState(BaseModel):
    # ... 标准字段 ...

    # 混合模式：来自相似工单的候选现象 ID
    hybrid_candidate_phenomenon_ids: List[str] = []

    # 用户描述的新观察（不在待确认列表中的）
    new_observations: List[str] = []
```

**核心特点**：
- **继承 GAR**：多模块协作架构、确定性置信度计算
- **借鉴 RAR**：工单描述语义检索、LLM 语义理解能力
- **快速路径**：简单格式跳过 LLM，降低延迟和成本
- **动态发现**：中间轮可发现新线索，补充候选现象

#### 4.5.4 三种方法对比

| 维度 | GAR | RAR | Hyb |
|------|-----|-----|-----|
| **推理引擎** | 确定性算法 | LLM 端到端 | 确定性算法 |
| **数据依赖** | 预处理多表 | 原始单表 | 预处理多表 + 原始工单 |
| **反馈理解** | 关键词匹配 | LLM 自由理解 | 快速路径 + LLM 结构化 |
| **置信度** | 公式计算 | LLM 自主判断 | 公式计算 |
| **可解释性** | ✅ 高 | ⚠️ 中 | ✅ 高 |
| **幻觉风险** | ✅ 无 | ⚠️ 有 | ✅ 无 |
| **灵活性** | ⚠️ 低 | ✅ 高 | ✅ 中高 |
| **动态发现** | ❌ 否 | ✅ 是 | ✅ 是 |

### 4.6 CLI 架构

**文件**: `dbdiag/cli/main.py`

**职责**: 提供命令行交互界面，支持多种诊断模式。

#### 4.6.1 类继承结构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CLI Class Hierarchy                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│                        ┌─────────────┐                                  │
│                        │     CLI     │ (Abstract Base)                  │
│                        │  - console  │                                  │
│                        │  - config   │                                  │
│                        │  - run()    │                                  │
│                        └──────┬──────┘                                  │
│                               │                                         │
│              ┌────────────────┼────────────────┐                        │
│              │                │                │                        │
│              ▼                │                ▼                        │
│      ┌─────────────┐          │        ┌─────────────┐                  │
│      │   GARCLI    │          │        │   RARCLI    │                  │
│      │   (Graph)   │          │        │ (Retrieval) │                  │
│      └──────┬──────┘          │        └─────────────┘                  │
│             │                 │                                         │
│             ▼                 │                                         │
│      ┌─────────────┐          │                                         │
│      │   HybCLI    │          │                                         │
│      │  (Hybrid)   │          │                                         │
│      └─────────────┘          │                                         │
│                               │                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**CLI 抽象基类**:

```python
class CLI(ABC):
    """CLI 抽象基类"""

    def __init__(self):
        self.console = Console()  # Rich Console
        self.config = load_config()
        self.db_path = "data/tickets.db"
        self.llm_service = LLMService(self.config)
        self.embedding_service = EmbeddingService(self.config)

    def run(self):
        """运行 CLI 主循环"""

    @abstractmethod
    def _show_welcome(self) -> None: pass

    @abstractmethod
    def _handle_diagnosis(self, user_message: str) -> bool: pass

    # ... 其他抽象方法
```

**各 CLI 类职责**:

| CLI 类 | 职责 | 启动命令 |
|--------|------|----------|
| `GARCLI` | 图谱增强推理，使用知识图谱 | `python -m dbdiag cli` |
| `HybCLI` | 混合增强推理，GAR + 语义检索 | `python -m dbdiag cli --hyb` |
| `RARCLI` | 检索增强推理，RAG + LLM 端到端 | `python -m dbdiag cli --rar` |

**HybCLI 实现**:

```python
class HybCLI(GARCLI):
    """Hyb CLI（混合增强推理，实验性）"""

    def __init__(self):
        super().__init__()
        # 重新创建 dialogue_manager，启用 hybrid_mode
        self.dialogue_manager = GARDialogueManager(
            self.db_path, self.llm_service, self.embedding_service,
            hybrid_mode=True,  # 启用混合模式
        )
```

### 4.7 Web 服务

**文件**: `dbdiag/api/websocket.py`, `dbdiag/web/static/`

**职责**: 提供基于 WebSocket 的 Web 控制台，支持浏览器访问诊断功能。

#### 4.7.1 架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Web Console                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────┐       WebSocket        ┌───────────────────────────┐ │
│  │    Browser    │◄────────────────────►│     FastAPI Server        │ │
│  │  index.html   │   /ws/chat            │   WebChatSession          │ │
│  │  + style.css  │                       │   + DiagnosisRenderer     │ │
│  └───────────────┘                       └─────────────┬─────────────┘ │
│                                                        │               │
│                                          ┌─────────────▼─────────────┐ │
│                                          │   GARDialogueManager      │ │
│                                          │   (hybrid_mode=True/False)│ │
│                                          └───────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 4.7.2 WebChatSession

每个 WebSocket 连接对应一个独立的 `WebChatSession` 实例：

```python
class WebChatSession:
    def __init__(self, websocket: WebSocket, config: dict):
        self.websocket = websocket
        self.console = Console(record=True)  # 记录输出为 HTML
        self.renderer = DiagnosisRenderer(self.console)
        self.diagnosis_mode = config.get("web", {}).get("diagnosis_mode", "hyb")

    async def handle_message(self, msg: dict) -> dict:
        """处理消息，返回 HTML 响应"""

    def render_welcome(self) -> str:
        """渲染欢迎消息"""
```

#### 4.7.3 消息协议

**客户端 → 服务端**：

```json
{"type": "message", "content": "查询变慢"}
{"type": "command", "content": "/help"}
```

**服务端 → 客户端**：

```json
{"type": "output", "html": "<div>...</div>"}
{"type": "close", "html": "<div>再见！</div>"}
```

#### 4.7.4 启动方式

```bash
# 启动 Web 控制台（推荐）
python -m dbdiag web

# 指定端口
python -m dbdiag web --port 8080

# 允许外部访问
python -m dbdiag web --host 0.0.0.0 --port 8080
```

#### 4.7.5 配置

```yaml
# config.yaml
web:
  host: "127.0.0.1"      # 监听地址
  port: 8000             # 监听端口
  diagnosis_mode: hyb    # gar/hyb/rar
```

### 4.8 DAO 数据访问层

**文件**: `dbdiag/dao/`

**职责**: 集中管理数据库访问，提供统一接口。

**基类设计**:

```python
class BaseDAO:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or default_path

    @contextmanager
    def get_connection(self):
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def get_cursor(self):
        """获取游标（上下文管理器）"""
        with self.get_connection() as conn:
            yield conn, conn.cursor()
```

**DAO 类列表**:

| DAO 类 | 职责 |
|--------|------|
| `PhenomenonDAO` | phenomena 表访问 |
| `TicketDAO` | tickets 表访问 |
| `TicketPhenomenonDAO` | ticket_phenomena 表访问 |
| `PhenomenonRootCauseDAO` | phenomenon_root_causes 表访问 |
| `RootCauseDAO` | root_causes 表访问 |
| `SessionDAO` | sessions 表访问 |
| `RawTicketDAO` | raw_tickets 表访问 |
| `RawAnomalyDAO` | raw_anomalies 表访问 |
| `IndexBuilderDAO` | 索引重建批量操作 |

---

## 五、数据处理流程

### 5.1 数据导入 (import)

**脚本**: `dbdiag/scripts/import_raw_tickets.py`

**功能**: 从 JSON 文件导入工单数据到原始数据表。

**输入格式**:

```json
[
  {
    "ticket_id": "T-0001",
    "metadata": {"version": "PostgreSQL-14.5"},
    "description": "在线报表查询突然变慢",
    "root_cause": "索引膨胀导致 IO 瓶颈",
    "solution": "执行 REINDEX",
    "anomalies": [
      {
        "description": "wait_io 事件占比 65%",
        "observation_method": "SELECT event FROM pg_stat_activity",
        "why_relevant": "IO 等待高说明磁盘瓶颈"
      }
    ]
  }
]
```

**使用方法**:

```bash
python -m dbdiag import data/example_tickets.json
```

### 5.2 索引重建 (rebuild-index)

**脚本**: `dbdiag/scripts/rebuild_index.py`

**功能**: 将原始数据转换为可检索的标准化数据。

**处理流程**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           rebuild-index 流程                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [Step 1] 读取原始异常 (raw_anomalies)                                        │
│       │                                                                      │
│       ▼                                                                      │
│  [Step 2] 生成异常向量 (Embedding API)                                        │
│       │                                                                      │
│       ▼                                                                      │
│  [Step 3] 异常向量聚类 (相似度阈值 0.85)                                      │
│       │                                                                      │
│       ▼                                                                      │
│  [Step 4] LLM 生成标准现象描述                                                │
│       │   - 单项聚类：直接使用原始描述                                        │
│       │   - 多项聚类：LLM 合并生成标准化描述                                  │
│       │                                                                      │
│       ▼                                                                      │
│  [Step 5] 提取原始根因 (raw_root_causes)                                      │
│       │   - 从 raw_tickets 按 root_cause 文本去重                             │
│       │   - 生成根因向量 (Embedding API)                                      │
│       │                                                                      │
│       ▼                                                                      │
│  [Step 6] 根因向量聚类 + LLM 标准化                                           │
│       │   - 使用相同的 0.85 相似度阈值                                        │
│       │   - 单项聚类：直接使用原始描述                                        │
│       │   - 多项聚类：LLM 合并描述 + LLM 合并解决方案                         │
│       │                                                                      │
│       ▼                                                                      │
│  [Step 7] 保存到数据库                                                        │
│       ├─> raw_root_causes (原始根因)                                          │
│       ├─> phenomena (标准现象)                                                │
│       ├─> root_causes (标准根因)                                              │
│       ├─> ticket_phenomena (工单-现象关联)                                    │
│       ├─> tickets (处理后工单，含 root_cause_id)                              │
│       └─> phenomenon_root_causes (现象-根因关联)                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**聚类算法** (贪心聚类):

```python
def cluster_by_similarity(items, threshold=0.85):
    """
    基于向量相似度的贪心聚类算法

    对每个项：
    1. 计算与现有所有聚类中心的相似度
    2. 如果超过阈值，加入最相似的聚类
    3. 否则创建新聚类
    """
    clusters = []
    cluster_centers = []

    for item in items:
        embedding = item["embedding"]
        matched_cluster = None
        max_similarity = 0

        # 检查与现有聚类的相似度
        for idx, center in enumerate(cluster_centers):
            similarity = cosine_similarity(embedding, center)
            if similarity > threshold and similarity > max_similarity:
                matched_cluster = idx
                max_similarity = similarity

        if matched_cluster is not None:
            clusters[matched_cluster].append(item)
            # 更新聚类中心（增量平均）
            n = len(clusters[matched_cluster])
            cluster_centers[matched_cluster] = (
                (old_center * (n - 1) + embedding) / n
            )
        else:
            clusters.append([item])
            cluster_centers.append(embedding)

    return clusters
```

**数据转换示例**:

```
原始数据 (raw_tickets):
┌─────────────┬─────────────────────────────┬─────────────────────┐
│ ticket_id   │ root_cause                  │ solution            │
├─────────────┼─────────────────────────────┼─────────────────────┤
│ T-0001      │ 索引膨胀导致 IO 瓶颈         │ REINDEX + 优化      │
│ T-0002      │ 索引膨胀，查询走全表扫描     │ 重建索引            │
│ T-0003      │ 连接池配置不当               │ 调整连接池大小      │
└─────────────┴─────────────────────────────┴─────────────────────┘

Step 5: 提取去重 -> raw_root_causes:
┌───────────┬─────────────────────────────┬────────────┐
│ id        │ description                 │ ticket_ids │
├───────────┼─────────────────────────────┼────────────┤
│ RRC-0001  │ 索引膨胀导致 IO 瓶颈         │ [T-0001]   │
│ RRC-0002  │ 索引膨胀，查询走全表扫描     │ [T-0002]   │
│ RRC-0003  │ 连接池配置不当               │ [T-0003]   │
└───────────┴─────────────────────────────┴────────────┘

Step 6: 向量聚类 (RRC-0001 和 RRC-0002 相似度 > 0.85):
┌────────────┬─────────────────────────────────────────────────────┐
│ Cluster 1  │ RRC-0001, RRC-0002 → LLM 合并 → "索引膨胀导致性能问题" │
│ Cluster 2  │ RRC-0003 → 直接使用 → "连接池配置不当"                 │
└────────────┴─────────────────────────────────────────────────────┘

Step 7: 生成 root_causes:
┌───────────┬──────────────────────────┬───────────────────────────┐
│ id        │ description              │ source_raw_root_cause_ids │
├───────────┼──────────────────────────┼───────────────────────────┤
│ RC-0001   │ 索引膨胀导致性能问题      │ [RRC-0001, RRC-0002]      │
│ RC-0002   │ 连接池配置不当            │ [RRC-0003]                │
└───────────┴──────────────────────────┴───────────────────────────┘
```

**使用方法**:

```bash
python -m dbdiag rebuild-index
```

---

## 附录

### A. 对话示例

以下是一个典型的 GAR（图谱增强推理）诊断对话流程（3 轮定位根因）：

```
██████╗ ██████╗ ██████╗ ██╗ █████╗  ██████╗        ██████╗
██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗██╔════╝       ██╔════╝
██║  ██║██████╔╝██║  ██║██║███████║██║  ███╗█████╗██║  ███╗
██║  ██║██╔══██╗██║  ██║██║██╔══██║██║   ██║╚════╝██║   ██║
██████╔╝██████╔╝██████╔╝██║██║  ██║╚██████╔╝      ╚██████╔╝
╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝        ╚═════╝

可用命令: /help /status /reset /exit

请描述您遇到的数据库问题开始诊断。

> 查询变慢，原来几秒现在要半分钟

• 第 1 轮
  → 正在分析问题...
  → 检索相关现象...
  → 检索根因候选...
  → 评估假设 (3/3) 完成
  → 生成推荐...

  轮次 1  │  推荐 3  │  确认 0  │  否认 0

  1. ███░░░░░░░ 32% 索引膨胀导致 IO 瓶颈
  2. ██░░░░░░░░ 28% 频繁更新导致索引碎片化
  3. ██░░░░░░░░ 25% 统计信息过期

  建议确认以下 3 个现象：

  [1] P-0001
      wait_io 事件占比异常高
      观察方法:
      SELECT wait_event_type, wait_event, count(*)
      FROM pg_stat_activity WHERE state = 'active'
      GROUP BY 1, 2 ORDER BY 3 DESC;
      推荐原因: 与假设"索引膨胀导致 IO 瓶颈"相关

  [2] P-0002
      索引大小异常增长
      观察方法:
      SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid))
      FROM pg_indexes ORDER BY pg_relation_size(indexrelid) DESC LIMIT 10;
      推荐原因: 与假设"索引膨胀导致 IO 瓶颈"相关

  [3] P-0003
      索引碎片率异常高
      观察方法:
      SELECT schemaname, relname, n_dead_tup, n_live_tup
      FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;
      推荐原因: 与假设"频繁更新导致索引碎片化"相关

  请输入检查结果（如：1确认 2否定 3确认）。

> 1确认 2确认 3否定

• 第 2 轮
  → 正在处理反馈...
  → 识别用户反馈...
  → 更新假设置信度...
  → 检索根因候选...
  → 评估假设 (3/3) 完成
  → 生成推荐...

  轮次 2  │  推荐 5  │  确认 2  │  否认 1

  1. ██████░░░░ 58% 索引膨胀导致 IO 瓶颈
  2. ███░░░░░░░ 22% 频繁更新导致索引碎片化
  3. ██░░░░░░░░ 15% 统计信息过期

  建议确认以下 2 个现象：

  [1] P-0004
      n_dead_tup 数量异常高
      观察方法:
      SELECT relname, n_dead_tup, last_autovacuum
      FROM pg_stat_user_tables WHERE n_dead_tup > 10000;
      推荐原因: 与假设"索引膨胀导致 IO 瓶颈"相关

  [2] P-0005
      执行 REINDEX 后性能恢复
      观察方法:
      REINDEX INDEX CONCURRENTLY <index_name>;
      -- 对比重建前后的查询时间
      推荐原因: 可验证假设"索引膨胀导致 IO 瓶颈"

  请输入检查结果（如：1确认 2否定 3确认）。

> 1确认 2确认

• 第 3 轮
  → 正在处理反馈...
  → 识别用户反馈...
  → 更新假设置信度...
  → 检索根因候选...
  → 评估假设 (3/3) 完成
  → 生成推荐...

  轮次 3  │  推荐 5  │  确认 4  │  否认 1

  1. ████████░░ 85% 索引膨胀导致 IO 瓶颈
  2. ██░░░░░░░░ 12% 频繁更新导致索引碎片化
  3. █░░░░░░░░░ 3% 统计信息过期

  ╭─ ✓ 根因已定位 ───────────────────────────────────────────────╮
  │                                                              │
  │  根因: 索引膨胀导致 IO 瓶颈                                   │
  │                                                              │
  │  ### 观察到的现象                                             │
  │                                                              │
  │  1. wait_io 事件占比异常高                                    │
  │  2. 索引大小出现异常增长                                      │
  │  3. n_dead_tup 数量高，autovacuum 未及时清理                  │
  │  4. 执行 REINDEX 后查询性能明显恢复                           │
  │                                                              │
  │  ### 推理链路                                                 │
  │                                                              │
  │  高 IO 等待通常由磁盘读写瓶颈引起。结合索引异常增长和死元组   │
  │  堆积的现象，可以判断：频繁的数据更新产生了大量死元组，而     │
  │  autovacuum 未能及时清理，导致索引膨胀。                      │
  │                                                              │
  │  ### 恢复措施                                                 │
  │                                                              │
  │  1. REINDEX INDEX CONCURRENTLY <index_name>;                 │
  │  2. ALTER TABLE <table> SET (autovacuum_vacuum_scale_factor  │
  │     = 0.05);                                                 │
  │  3. 建立索引大小监控告警                                      │
  │                                                              │
  │  引用工单                                                     │
  │                                                              │
  │  [1] T-0001: 报表查询变慢，wait_io 高                         │
  │  [2] T-0018: 定时任务执行慢，索引膨胀                         │
  │                                                              │
  ╰──────────────────────────────────────────────────────────────╯

再见！
```

以下是 RAR（检索增强推理）方法的对话示例（实验性功能）：

```
██████╗ ██████╗ ██████╗ ██╗ █████╗  ██████╗       ██████╗
██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗██╔════╝       ██╔══██╗
██║  ██║██████╔╝██║  ██║██║███████║██║  ███╗█████╗██████╔╝
██║  ██║██╔══██╗██║  ██║██║██╔══██║██║   ██║╚════╝██╔══██╗
██████╔╝██████╔╝██████╔╝██║██║  ██║╚██████╔╝      ██║  ██║
╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝       ╚═╝  ╚═╝

检索增强推理方法（实验性）
可用命令: /help /reset /exit

请描述您遇到的数据库问题开始诊断。

> 查询变慢，原来几秒现在要半分钟

• 第 1 轮
  → 正在分析问题...

  置信度: 35%

  分析: 用户描述了查询变慢的现象，但缺少具体的性能指标和系统状态信息。
  需要进一步确认 IO、锁、索引等方面的观察。

  建议检查以下 3 个现象：

  [1] wait_io 事件占比
      方法: SELECT wait_event_type, count(*) FROM pg_stat_activity
            WHERE state = 'active' GROUP BY 1;
      原因: 高 IO 等待通常与索引膨胀或磁盘瓶颈相关
      可能根因: 索引膨胀, 磁盘 IO 瓶颈

  [2] 索引大小变化
      方法: SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid))
            FROM pg_indexes ORDER BY pg_relation_size(indexrelid) DESC;
      原因: 索引异常增长可能导致查询性能下降
      可能根因: 索引膨胀

  [3] 执行计划变化
      方法: EXPLAIN ANALYZE <your_query>;
      原因: 执行计划变化可能揭示优化器选择问题
      可能根因: 统计信息过期, 索引失效

  请检查上述现象并反馈结果（如：1确认 2否定）

> wait_io 占比 65%，索引从 2GB 涨到 12GB

• 第 2 轮
  → 正在处理反馈...

  置信度: 78%

  分析: 用户确认了高 IO 等待（65%）和索引异常增长（6倍），这与历史工单
  T-0001、T-0018 的模式高度匹配，指向索引膨胀问题。

  建议检查以下 1 个现象：

  [1] REINDEX 后性能恢复
      方法: REINDEX INDEX CONCURRENTLY <index_name>;
            -- 对比重建前后查询时间
      原因: 如果重建索引后性能恢复，可确认索引膨胀是根因
      可能根因: 索引膨胀

  请检查上述现象并反馈结果（如：1确认 2否定）

> REINDEX 后查询恢复到 3 秒

• 第 3 轮
  → 正在处理反馈...

  ╭─ ✓ 诊断结论 ─────────────────────────────────────────────────╮
  │                                                              │
  │  根因: 索引膨胀导致 IO 瓶颈                                   │
  │  置信度: 92%                                                  │
  │                                                              │
  │  分析:                                                        │
  │  用户确认了三个关键现象：(1) wait_io 占比 65%，(2) 索引从     │
  │  2GB 增长到 12GB，(3) REINDEX 后查询恢复正常。这与历史工单   │
  │  T-0001、T-0018 的诊断路径完全吻合，可以确认根因是索引膨胀。 │
  │                                                              │
  │  解决方案:                                                    │
  │  1. 对膨胀的索引执行 REINDEX INDEX CONCURRENTLY              │
  │  2. 调整 autovacuum 参数：                                    │
  │     ALTER TABLE <table> SET (autovacuum_vacuum_scale_factor  │
  │     = 0.05);                                                 │
  │  3. 建立索引大小监控，设置告警阈值                           │
  │                                                              │
  │  参考工单: T-0001, T-0018                                    │
  │                                                              │
  ╰──────────────────────────────────────────────────────────────╯

再见！
```

**GAR vs RAR vs Hyb 对比**：

| 特性 | GAR（图谱增强推理） | RAR（检索增强推理） | Hyb（混合增强推理） |
|------|---------------------|---------------------|---------------------|
| 推理方式 | 知识图谱 + 规则引擎 | RAG + LLM 端到端 | 知识图谱 + 语义检索 + LLM 反馈理解 |
| 现象管理 | 标准化现象库（phenomena 表） | 直接从工单检索 | 标准化现象库 + 工单语义检索 |
| 反馈理解 | 关键词匹配 | LLM 自主判断 | LLM 结构化提取 |
| 置信度计算 | 多因素公式计算 | LLM 自主判断 | 多因素公式计算 |
| 可解释性 | 高（每步可追溯） | 中（依赖 LLM 解释） | 高（每步可追溯） |
| 灵活性 | 需要预建索引 | 无需预处理 | 需要预建索引 |
| 初始推荐覆盖率 | 中（依赖现象向量检索） | 高（直接从工单） | 高（语义检索增强） |
| 中间轮动态发现 | 否 | 是 | 是（基于新观察检索） |
| 启动命令 | `python -m dbdiag cli` | `python -m dbdiag cli --rar` | `python -m dbdiag cli --hyb` |

### B. 配置说明

系统通过 `config.yaml` 进行配置：

```yaml
# LLM 配置
llm:
  api_base: "http://localhost:11434/v1"
  api_key: "sk-xxx"
  model: "Qwen/Qwen3-32B"
  temperature: 0.2
  max_tokens: 16384

# Embedding 模型配置
embedding_model:
  api_base: "http://localhost:11435/v1"
  api_key: "sk-xxx"
  model: "Qwen/Qwen3-Embedding-4B"
```

### C. CLI 命令

```bash
# 初始化数据库
python -m dbdiag init

# 导入工单数据
python -m dbdiag import data/example_tickets.json

# 重建索引
python -m dbdiag rebuild-index

# 启动 CLI 诊断（默认 GAR 模式）
python -m dbdiag cli

# 启动 CLI 诊断（RAR 模式，实验性）
python -m dbdiag cli --rar

# 启动 CLI 诊断（混合增强模式，实验性）
python -m dbdiag cli --hyb

# 启动 Web 控制台
python -m dbdiag web

# 启动 Web 控制台（指定端口）
python -m dbdiag web --port 8080

# 启动 Web 控制台（允许外部访问）
python -m dbdiag web --host 0.0.0.0 --port 8080

# 生成知识图谱可视化
python -m dbdiag visualize --layout hierarchical
```
