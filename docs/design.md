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
┌─────────────────────────────────────────────────────────────┐
│                     用户交互层                               │
│  CLI (Click)  |  Web API (FastAPI)                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    对话管理器                                │
│                 (DialogueManager)                            │
│                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌───────────────┐  │
│  │ HypothesisTracker│  │  Recommender   │  │ResponseGenerator│
│  │   假设追踪器    │  │   推荐引擎     │  │  响应生成器   │  │
│  └───────┬────────┘  └───────┬────────┘  └───────┬───────┘  │
│          │                   │                   │           │
│  ┌───────▼───────────────────▼───────────────────▼───────┐  │
│  │                    Retriever 检索器                    │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      服务层                                  │
│  ┌────────────────┐  ┌────────────────┐                     │
│  │  LLMService    │  │EmbeddingService│                     │
│  │   LLM 服务     │  │  向量服务      │                     │
│  └────────────────┘  └────────────────┘                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    DAO 数据访问层                            │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────────────────┐│
│  │PhenomenonDAO│ │  TicketDAO   │ │ RootCauseDAO | Session ││
│  └─────────────┘ └──────────────┘ └────────────────────────┘│
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   SQLite 数据库                              │
│  phenomena | tickets | ticket_anomalies | root_causes | ... │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| **CLI 框架** | Click | 命令行界面 |
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
│   │   └── session.py
│   ├── cli/                      # 命令行界面
│   │   ├── main.py
│   │   └── formatter.py
│   ├── core/                     # 核心逻辑
│   │   ├── dialogue_manager.py
│   │   ├── hypothesis_tracker.py
│   │   ├── retriever.py
│   │   ├── recommender.py
│   │   └── response_generator.py
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
│   │   ├── session.py
│   │   ├── ticket.py
│   │   └── phenomenon.py
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
┌─────────────────────────────────────────────────────────────────────────┐
│                           对话处理总流程                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     第 1 轮：开始对话                            │   │
│  ├─────────────────────────────────────────────────────────────────┤   │
│  │  用户输入: "查询变慢，原来几秒现在要半分钟"                       │   │
│  │                          │                                       │   │
│  │                          ▼                                       │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │ DialogueManager.start_conversation()                     │    │   │
│  │  │   1. 创建会话 (SessionDAO)                               │    │   │
│  │  │   2. 提取事实 → confirmed_facts                          │    │   │
│  │  │   3. 检索相关现象 (Retriever)                            │    │   │
│  │  │   4. 生成初始假设 (HypothesisTracker)                    │    │   │
│  │  │   5. 推荐首批现象 (Recommender)                          │    │   │
│  │  └─────────────────────────────────────────────────────────┘    │   │
│  │                          │                                       │   │
│  │                          ▼                                       │   │
│  │  输出: 推荐 3 个现象 + 假设置信度列表                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │                                         │
│                              ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                   第 2-N 轮：继续对话                            │   │
│  ├─────────────────────────────────────────────────────────────────┤   │
│  │  用户输入: "1确认 2确认 3否定"                                   │   │
│  │                          │                                       │   │
│  │                          ▼                                       │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │ DialogueManager.continue_conversation()                  │    │   │
│  │  │                                                          │    │   │
│  │  │   1. 解析用户反馈                                        │    │   │
│  │  │      └─> 更新 confirmed_phenomena / denied_phenomena     │    │   │
│  │  │                                                          │    │   │
│  │  │   2. 重新计算假设置信度 (HypothesisTracker)              │    │   │
│  │  │      ├─> 事实匹配度 (LLM 评估)        权重 50%           │    │   │
│  │  │      ├─> 现象确认进度                 权重 30%           │    │   │
│  │  │      ├─> 根因流行度                   权重 10%           │    │   │
│  │  │      ├─> 问题描述相似度               权重 10%           │    │   │
│  │  │      └─> 否定惩罚 (每个否定现象 -15%)                    │    │   │
│  │  │                                                          │    │   │
│  │  │   3. 决策分支 (Recommender)                              │    │   │
│  │  │      ├─> 置信度 > 85%: 确认根因 → 生成诊断总结           │    │   │
│  │  │      └─> 置信度 < 85%: 推荐下一批区分性现象              │    │   │
│  │  └─────────────────────────────────────────────────────────┘    │   │
│  │                          │                                       │   │
│  │                          ▼                                       │   │
│  │  输出: 推荐更多现象 或 诊断结论                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │                                         │
│                              ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     根因定位完成                                 │   │
│  ├─────────────────────────────────────────────────────────────────┤   │
│  │  当 top_hypothesis.confidence > 0.85 时:                        │   │
│  │                                                                  │   │
│  │  ResponseGenerator.generate_diagnosis_summary()                  │   │
│  │    ├─> 观察到的现象（confirmed_phenomena）                       │   │
│  │    ├─> 推理链路（LLM 生成）                                     │   │
│  │    ├─> 恢复措施（从 root_causes.solution）                      │   │
│  │    └─> 引用工单（supporting_ticket_ids）                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
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
    │       └─> TicketAnomalyDAO    # 获取现象-工单关联
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
原始数据表（raw_tickets, raw_anomalies）
    │
    ▼ rebuild-index（聚类 + LLM 标准化）
处理后数据表（phenomena, tickets, ticket_anomalies, root_causes）
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

**root_causes** - 根因表：

| 字段 | 类型 | 说明 |
|------|------|------|
| root_cause_id | TEXT PK | 格式: RC-{序号} |
| description | TEXT | 根因描述 |
| solution | TEXT | 解决方案 |
| key_phenomenon_ids | TEXT | 关键现象 ID（JSON） |
| related_ticket_ids | TEXT | 相关工单 ID（JSON） |
| ticket_count | INTEGER | 工单数量 |

**tickets** - 处理后工单表：

| 字段 | 类型 | 说明 |
|------|------|------|
| ticket_id | TEXT PK | 工单 ID |
| description | TEXT | 问题描述 |
| root_cause_id | TEXT FK | 关联根因 |
| root_cause | TEXT | 根因描述（冗余） |
| solution | TEXT | 解决方案 |

**ticket_anomalies** - 工单-现象关联表：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | 关联 ID |
| ticket_id | TEXT FK | 工单 ID |
| phenomenon_id | TEXT FK | 现象 ID |
| why_relevant | TEXT | 该工单上下文中的相关性 |
| raw_anomaly_id | TEXT FK | 原始异常 ID（溯源） |

#### 3.1.3 数据关系图

```
                              ┌─────────────────┐
                              │   root_causes   │
                              │  (RC-0001...)   │
                              └────────┬────────┘
                                       │ 1
                                       │
                                       │ N
                              ┌────────▼────────┐
                              │     tickets     │
                              │  (TICKET-001)   │
                              └────────┬────────┘
                                       │ 1
                                       │
                                       │ N
                            ┌──────────▼──────────┐
                            │  ticket_anomalies   │
                            │   (关联表)          │
                            └──────────┬──────────┘
                                       │ N
                                       │
                                       │ 1
                              ┌────────▼────────┐
                              │   phenomena     │
                              │   (P-0001...)   │
                              └─────────────────┘
```

**关系说明**：
- 一个 `root_cause` 对应多个 `tickets`（1:N）
- 一个 `ticket` 关联多个 `phenomena`（通过 `ticket_anomalies`）
- 一个 `phenomenon` 可被多个 `tickets` 共享（N:M）

#### 3.1.4 数据示例

**原始数据**（2个工单，共享相似的异常现象）：

```yaml
# 工单 1
ticket_id: TICKET-001
description: "报表查询变慢"
root_cause: "索引膨胀导致 IO 瓶颈"
anomalies:
  - description: "wait_io 事件占比 65%"      # 相似 ─┐
  - description: "索引大小增长 6 倍"          #      │
                                              #      │
# 工单 2                                      #      │
ticket_id: TICKET-002                         #      │
description: "定时任务执行慢"                  #      │
root_cause: "索引膨胀导致 IO 瓶颈"            #      │
anomalies:                                    #      │
  - description: "wait_io 占比达 70%"         # 相似 ─┘（聚类到同一现象）
  - description: "表膨胀严重"
```

**rebuild-index 后生成**：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            root_causes                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  RC-0001: "索引膨胀导致 IO 瓶颈"                                        │
│           ticket_count: 2                                               │
│           related_ticket_ids: ["TICKET-001", "TICKET-002"]              │
│           key_phenomenon_ids: ["P-0001", "P-0002", "P-0003"]            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│          tickets                │  │          tickets                │
├─────────────────────────────────┤  ├─────────────────────────────────┤
│  TICKET-001                     │  │  TICKET-002                     │
│  root_cause_id: RC-0001         │  │  root_cause_id: RC-0001         │
└───────────────┬─────────────────┘  └───────────────┬─────────────────┘
                │                                    │
        ┌───────┴───────┐                    ┌───────┴───────┐
        ▼               ▼                    ▼               ▼
┌─────────────┐ ┌─────────────┐      ┌─────────────┐ ┌─────────────┐
│ticket_anomaly│ │ticket_anomaly│     │ticket_anomaly│ │ticket_anomaly│
│  → P-0001   │ │  → P-0002   │      │  → P-0001   │ │  → P-0003   │
└──────┬──────┘ └──────┬──────┘      └──────┬──────┘ └──────┬──────┘
       │               │                    │               │
       └───────┬───────┘                    └───────┬───────┘
               ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            phenomena                                     │
├─────────────────────────────────────────────────────────────────────────┤
│  P-0001: "wait_io 事件占比超过阈值"     ← 聚类自 TICKET-001 + TICKET-002 │
│          cluster_size: 2                                                │
│          source_anomaly_ids: ["TICKET-001_anomaly_1", "TICKET-002_..."] │
├─────────────────────────────────────────────────────────────────────────┤
│  P-0002: "索引大小异常增长"             ← 仅来自 TICKET-001             │
│          cluster_size: 1                                                │
├─────────────────────────────────────────────────────────────────────────┤
│  P-0003: "表膨胀严重"                   ← 仅来自 TICKET-002             │
│          cluster_size: 1                                                │
└─────────────────────────────────────────────────────────────────────────┘
```

**关键点**：
- `P-0001` 由两个相似的异常聚类生成（`cluster_size: 2`）
- 两个工单共享 `P-0001`，体现"现象复用"
- `RC-0001` 关联了所有相关现象和工单

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

**文件**: `dbdiag/core/retriever.py`

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

**文件**: `dbdiag/core/hypothesis_tracker.py`

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
def compute_confidence(root_cause, confirmed_facts, confirmed_phenomena, denied_phenomena):
    # 1. 事实匹配度（权重 50%）- LLM 评估事实对假设的支持程度
    fact_score = evaluate_facts_for_hypothesis(root_cause, confirmed_facts)

    # 2. 现象确认进度（权重 30%）
    phenomenon_progress = confirmed_count / total_phenomena

    # 3. 根因流行度（权重 10%）
    frequency_score = min(ticket_count / 10, 1.0)

    # 4. 问题描述相似度（权重 10%）
    desc_similarity = cosine_similarity(user_problem, root_cause)

    # 综合计算
    confidence = 0.5 * fact_score + 0.3 * phenomenon_progress + 0.1 * frequency_score + 0.1 * desc_similarity

    # 5. 否定惩罚：每个被否定的相关现象降低 15% 置信度
    if denied_relevant_count > 0:
        confidence *= (1 - denied_relevant_count * 0.15)

    return confidence
```

### 4.3 推荐引擎 (PhenomenonRecommendationEngine)

**文件**: `dbdiag/core/recommender.py`

**职责**: 根据当前假设状态，推荐下一波需要观察的现象。

**决策逻辑**:

```python
def recommend_next_action(session):
    if not session.active_hypotheses:
        return ask_for_initial_info()

    top_hypothesis = session.active_hypotheses[0]

    # 高置信度 -> 确认根因
    if top_hypothesis.confidence > 0.85:
        return generate_root_cause_confirmation(top_hypothesis)

    # 中低置信度 -> 推荐区分性现象
    recommended = recommend_discriminating_phenomena(session, top_k=3)
    return generate_recommendation(recommended)
```

**现象选择策略**:

1. 从 Top-N 候选工单中收集未确认的现象
2. 计算每个现象的"区分能力"（能区分多少假设）
3. 综合评分：`0.6 * coverage_score + 0.4 * uniqueness_score`

### 4.4 响应生成器 (ResponseGenerator)

**文件**: `dbdiag/core/response_generator.py`

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

**引用工单：** [T-001] [T-005]
```

### 4.5 对话管理器 (PhenomenonDialogueManager)

**文件**: `dbdiag/core/dialogue_manager.py`

**职责**: 整合所有组件，管理对话流程。

**主要流程**:

```
start_conversation(user_problem)
    │
    ├─> 创建会话
    ├─> 初始化假设
    └─> 返回首轮推荐

continue_conversation(session_id, user_message)
    │
    ├─> 解析用户反馈（确认/否定现象）
    ├─> 更新会话状态
    ├─> 重新计算假设置信度
    ├─> 生成下一步推荐或诊断结论
    └─> 返回响应
```

**核心方法**:

```python
class PhenomenonDialogueManager:
    def __init__(self, db_path, llm_service, embedding_service):
        self.hypothesis_tracker = PhenomenonHypothesisTracker(...)
        self.recommender = PhenomenonRecommendationEngine(...)
        self.response_generator = ResponseGenerator(...)
        self.session_dao = SessionDAO(db_path)

    def start_conversation(self, user_problem: str) -> Dict:
        """开始新对话"""

    def continue_conversation(self, session_id: str, user_message: str) -> Dict:
        """继续对话"""
```

### 4.6 DAO 数据访问层

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
| `TicketAnomalyDAO` | ticket_anomalies 表访问 |
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
    "ticket_id": "TICKET-001",
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
python -m dbdiag import data/tickets.json
```

### 5.2 索引重建 (rebuild-index)

**脚本**: `dbdiag/scripts/rebuild_index.py`

**功能**: 将原始数据转换为可检索的标准化数据。

**处理流程**:

```
1. 读取原始异常 (raw_anomalies)
       │
       ▼
2. 生成向量 (Embedding API)
       │
       ▼
3. 向量聚类 (相似度阈值 0.85)
       │
       ▼
4. LLM 生成标准描述
       │
       ▼
5. 保存 phenomena + ticket_anomalies
       │
       ▼
6. 生成 root_causes + tickets
```

**聚类算法** (贪心聚类):

```python
def cluster_by_similarity(items, threshold=0.85):
    clusters = []
    cluster_centers = []

    for item in items:
        embedding = item["embedding"]
        matched_cluster = None

        # 检查与现有聚类的相似度
        for idx, center in enumerate(cluster_centers):
            if cosine_similarity(embedding, center) > threshold:
                matched_cluster = idx
                break

        if matched_cluster is not None:
            clusters[matched_cluster].append(item)
            # 更新聚类中心（增量平均）
        else:
            clusters.append([item])
            cluster_centers.append(embedding)

    return clusters
```

**使用方法**:

```bash
python -m dbdiag rebuild-index
```

---

## 附录

### A. 对话示例

以下是一个典型的诊断对话流程（3-4 轮定位根因）：

```
[第 1 轮]
用户: 查询变慢，原来几秒现在要半分钟

系统: 建议确认以下 3 个现象：

  1. [P-0001] wait_io 事件占比异常高
     观察方法:
     SELECT wait_event_type, wait_event, count(*)
     FROM pg_stat_activity WHERE state = 'active'
     GROUP BY 1, 2 ORDER BY 3 DESC;

  2. [P-0002] 索引大小异常增长
     观察方法:
     SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid))
     FROM pg_indexes ORDER BY pg_relation_size(indexrelid) DESC LIMIT 10;

  3. [P-0003] 索引碎片率异常高
     观察方法:
     SELECT schemaname, relname, n_dead_tup, n_live_tup
     FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;

请检查并反馈结果（如：1确认 2确认 3否定）

假设置信度:
  1. [███░░░░░░░] 32% 索引膨胀导致 IO 瓶颈
  2. [██░░░░░░░░] 28% 频繁更新导致索引碎片化
  3. [██░░░░░░░░] 25% 统计信息过期

---

[第 2 轮]
用户: 1确认 2确认 3否定

系统: 建议确认以下 2 个现象：

  1. [P-0004] n_dead_tup 数量异常高
     观察方法:
     SELECT relname, n_dead_tup, last_autovacuum
     FROM pg_stat_user_tables WHERE n_dead_tup > 10000;

  2. [P-0005] 执行 REINDEX 后性能恢复
     观察方法:
     REINDEX INDEX CONCURRENTLY <index_name>;
     -- 对比重建前后的查询时间

假设置信度:
  1. [██████░░░░] 58% 索引膨胀导致 IO 瓶颈
  2. [███░░░░░░░] 22% 频繁更新导致索引碎片化

---

[第 3 轮]
用户: 1确认 2确认

系统:
══════════════════════════════════════════════════
  根因已定位：索引膨胀导致 IO 瓶颈
  置信度: 82%
══════════════════════════════════════════════════

【诊断总结】

**观察到的现象：**
1. wait_io 事件占比异常高
2. 索引大小出现异常增长
3. n_dead_tup 数量高，autovacuum 未及时清理
4. 执行 REINDEX 后查询性能明显恢复

**推理链路：**
高 IO 等待通常由磁盘读写瓶颈引起。结合索引异常增长和死元组
堆积的现象，可以判断：频繁的数据更新产生了大量死元组，而
autovacuum 未能及时清理，导致索引膨胀。

**恢复措施：**
1. REINDEX INDEX CONCURRENTLY <index_name>;
2. ALTER TABLE <table> SET (autovacuum_vacuum_scale_factor = 0.05);
3. 建立索引大小监控告警

引用工单: [DB-001] [DB-018]
```

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
python -m dbdiag import data/tickets.json

# 重建索引
python -m dbdiag rebuild-index

# 启动 CLI 诊断
python -m dbdiag chat

# 生成知识图谱可视化
python -m dbdiag visualize --layout hierarchical
```
