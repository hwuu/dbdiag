# 数据库运维问题诊断助手设计文档

## 一、项目概述

### 1.1 项目目标

基于专家标注的数据库运维工单（tickets）数据，构建一个支持多轮自然语言交互的辅助根因定位问答助手，帮助用户快速定位数据库问题的根本原因。

### 1.2 核心特性

1. **多轮交互式诊断**：通过多轮对话逐步收集现象，缩小根因范围
2. **可溯源推理**：每个结论和操作建议必须引用具体的历史工单
3. **跨案例组合能力**：支持从多个历史案例中组合诊断步骤，应对未见过的新问题
4. **动态假设追踪**：并行追踪多个可能的根因假设，动态评估和排序
5. **简洁架构**：易部署、易演示、易扩展

### 1.3 输入数据结构

每个工单（ticket）包含以下结构化信息：

```yaml
ticket_id: TICKET-001
metadata:
  version: "PostgreSQL-14.5"
  module: "query_optimizer"
  severity: "high"
description: "在线报表查询突然变慢，从5秒增加到30秒"
anomalies:
  - description: "wait_io 事件占比 65%，远超日常 20% 水平"
    observation_method: "SELECT event, count FROM pg_stat_activity WHERE wait_event IS NOT NULL"
    why_relevant: "IO 等待高说明磁盘读写存在瓶颈，是查询变慢的直接原因"
  - description: "索引 test_idx 大小从 2GB 增长到 12GB"
    observation_method: "SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid)) FROM pg_indexes"
    why_relevant: "索引膨胀导致 B-tree 层级增加，扫描时逻辑读放大"
root_cause: "索引膨胀导致 IO 瓶颈"
solution: "执行 REINDEX INDEX CONCURRENTLY test_idx; 并配置定期 VACUUM"
```

**字段说明**：
- `anomalies`：观察到的异常现象列表（无序集合，非线性流程）
- `description`：异常现象描述，应包含量化指标
- `observation_method`：观察该现象的具体操作（SQL/命令/工具）
- `why_relevant`：该异常现象为什么与当前故障相关

---

## 二、核心设计理念

### 2.1 关键洞察

数据库问题诊断本质上是一个**模式匹配过程**：
- DBA 看到异常现象后，联想到历史案例中类似的现象组合
- 通过累积观察到的现象，逐步缩小根因可能性范围
- 最终在置信度足够高时给出根因判断和解决方案

**核心认知**：诊断是联想式、集合式的，而非严格线性流程。

### 2.2 设计原则

1. **现象级检索**（Phenomenon-Level Retrieval）
   - 检索的最小单位是标准化的现象（phenomenon），而非整个工单
   - 支持从不同工单中提取相关现象进行组合
   - 异常现象是无序集合，不强制顺序

2. **上下文累积**（Context Accumulation）
   - 每轮对话累积更多已确认的现象
   - 基于累积的上下文动态调整假设和推荐

3. **多路径并行**（Multi-Hypothesis Tracking）
   - 同时追踪 Top-N 个最可能的根因假设
   - 动态评估每个假设的置信度
   - 推荐能最大程度区分不同假设的观察步骤

4. **轻量级优先**（Lightweight First）
   - MVP 阶段使用简单有效的算法
   - 避免过度工程化
   - 预留扩展接口

---

## 三、系统架构

### 3.1 整体架构

```
┌─────────────────────────────────────────┐
│       用户交互层 (FastAPI + Web UI)      │
│  - POST /chat: 对话接口                  │
│  - GET /session/{id}: 会话查询           │
│  - POST /session/new: 创建新会话         │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│          对话管理器 (核心逻辑)           │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │   会话状态管理                   │   │
│  │   - 已确认事实列表               │   │
│  │   - 活跃假设列表 (Top-3)         │   │
│  │   - 已执行步骤历史               │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │   多假设追踪器                   │   │
│  │   - 根因候选检索                 │   │
│  │   - 置信度动态计算               │   │
│  │   - 假设排序与更新               │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │   下一步推荐引擎                 │   │
│  │   - 区分性步骤识别               │   │
│  │   - 多假设投票机制               │   │
│  │   - 响应生成与引用构建           │   │
│  └─────────────────────────────────┘   │
└────┬─────────────────────┬──────────────┘
     │                     │
┌────▼─────────┐   ┌───────▼──────────────┐
│  检索层       │   │   LLM 服务层          │
│              │   │                       │
│ • 步骤检索   │   │ • 结果解释生成        │
│ • 根因匹配   │   │ • 自然语言理解        │
│ • 向量检索   │   │ • 响应格式化          │
│              │   │                       │
│ (本地逻辑)   │   │ (API 调用)            │
└────┬─────────┘   └───────────────────────┘
     │
┌────▼──────────────────────────────────┐
│      存储层 (SQLite + 向量索引)        │
│                                        │
│  原始数据层：                          │
│  • raw_tickets 表                      │
│  • raw_anomalies 表                    │
│                                        │
│  处理后数据层：                        │
│  • phenomena 表（标准现象库）          │
│  • tickets 表                          │
│  • ticket_anomalies 表                 │
│  • phenomenon_embeddings (向量索引)   │
│  • sessions 表/文件                    │
└────────────────────────────────────────┘
```

### 3.2 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| **Web 框架** | FastAPI | 轻量、异步、自动文档生成 |
| **数据库** | SQLite | 零配置、单文件部署 |
| **向量存储** | sqlite-vec 插件 | 集成在 SQLite 中，无需独立服务 |
| **LLM** | API（配置化） | 支持 OpenAI API 兼容接口 |
| **Embedding** | API（配置化） | 支持 OpenAI Embedding API 兼容接口 |
| **CLI** | Click | 命令行界面框架 |
| **可视化** | pyvis | 知识图谱交互式 HTML 可视化 |
| **会话存储** | SQLite 或 JSON 文件 | 简单持久化，无需 Redis |

### 3.3 配置管理

系统通过 `config.yaml` 进行配置（基于 `config.yaml.example`）：

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

---

## 四、核心数据模型

### 4.1 数据层设计理念

系统采用**原始数据与处理后数据分离**的设计：

```
原始工单数据（专家手工整理）
    │
    ▼ import
    │
原始数据表（raw_tickets, raw_anomalies）
    │
    ▼ rebuild-index（聚类 + LLM 标准化）
    │
处理后数据表（phenomena, tickets, ticket_anomalies）
    │
    ▼
向量索引（用于检索）
```

**设计优势**：
- 原始数据保留，可追溯，支持重新处理
- 处理后数据标准化，便于检索和推荐
- 标准现象库（phenomena）支持去重和复用

### 4.2 原始数据表

#### 4.2.1 原始工单表 (raw_tickets)

存储专家标注的原始工单数据：

```sql
CREATE TABLE raw_tickets (
    ticket_id TEXT PRIMARY KEY,
    metadata_json TEXT,           -- JSON: {"version": "...", "module": "...", "severity": "..."}
    description TEXT,             -- 问题描述
    root_cause TEXT,              -- 根因
    solution TEXT,                -- 解决方案
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.2.2 原始异常表 (raw_anomalies)

存储专家标注的原始异常描述：

```sql
CREATE TABLE raw_anomalies (
    id TEXT PRIMARY KEY,                   -- 格式: {ticket_id}_anomaly_{index}
    ticket_id TEXT,
    anomaly_index INTEGER,                 -- 异常在工单中的序号
    description TEXT,                      -- 原始异常描述
    observation_method TEXT,               -- 原始观察方法
    why_relevant TEXT,                     -- 原始相关性解释
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES raw_tickets(ticket_id)
);
```

### 4.3 处理后数据表

#### 4.3.1 标准现象表 (phenomena)

**核心表**，存储聚类去重后的标准化现象：

```sql
CREATE TABLE phenomena (
    phenomenon_id TEXT PRIMARY KEY,        -- 格式: P-{序号}，如 P-0001
    description TEXT,                      -- 标准化描述（LLM 生成）
    observation_method TEXT,               -- 标准观察方法（选最佳）
    source_anomaly_ids TEXT,               -- 来源的原始 anomaly IDs（JSON 数组）
    cluster_size INTEGER,                  -- 聚类中的异常数量
    embedding BLOB,                        -- 向量表示
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**设计说明**：
- 每个 phenomenon 是聚类后的标准现象，可能来自多个原始 anomaly
- `description` 由 LLM 生成标准化描述
- `observation_method` 从聚类中选择最完整/最佳的方法
- `source_anomaly_ids` 记录来源，支持溯源

#### 4.3.2 处理后工单表 (tickets)

```sql
CREATE TABLE tickets (
    ticket_id TEXT PRIMARY KEY,
    metadata_json TEXT,
    description TEXT,
    root_cause_id TEXT,                    -- 关联根因（外键）
    root_cause TEXT,                       -- 根因描述（冗余，便于查询）
    solution TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (root_cause_id) REFERENCES root_causes(root_cause_id)
);
```

#### 4.3.3 工单-现象关联表 (ticket_anomalies)

```sql
CREATE TABLE ticket_anomalies (
    id TEXT PRIMARY KEY,                   -- 格式: {ticket_id}_anomaly_{index}
    ticket_id TEXT,
    phenomenon_id TEXT,                    -- 关联标准现象
    why_relevant TEXT,                     -- 该工单上下文中的相关性解释
    raw_anomaly_id TEXT,                   -- 关联原始异常（可选，用于溯源）
    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id),
    FOREIGN KEY (phenomenon_id) REFERENCES phenomena(phenomenon_id),
    FOREIGN KEY (raw_anomaly_id) REFERENCES raw_anomalies(id)
);
```

**设计说明**：
- 同一 phenomenon 在不同工单中可能有不同的 `why_relevant`
- 例如：P-0001（wait_io 高）在索引膨胀工单和磁盘故障工单中相关性解释不同

#### 4.3.4 根因表 (root_causes)

存储聚合后的根因信息，由 `rebuild-index` 从 `raw_tickets` 生成：

```sql
CREATE TABLE root_causes (
    root_cause_id TEXT PRIMARY KEY,        -- 格式: RC-{序号}，如 RC-0001
    description TEXT NOT NULL,             -- 根因描述文本
    solution TEXT,                         -- 通用解决方案
    key_phenomenon_ids TEXT,               -- 关键现象 ID 列表（JSON 数组）
    related_ticket_ids TEXT,               -- 相关工单 ID 列表（JSON 数组）
    ticket_count INTEGER NOT NULL DEFAULT 0, -- 支持该根因的工单数量
    embedding BLOB                         -- 根因的向量表示（可选）
);
```

**设计说明**：
- 每个唯一的 `root_cause` 文本生成一个 `root_cause_id`
- `tickets.root_cause_id` 是指向此表的外键
- 运行时代码通过 `root_cause_id` 关联，不再直接访问 `raw_tickets`

#### 4.3.5 会话表 (sessions)

存储用户会话状态：

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_problem TEXT,                     -- 用户初始问题描述
    state_json TEXT,                       -- 会话状态（JSON）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.4 会话状态结构

会话状态以 JSON 格式存储在 `sessions.state_json` 字段中：

```json
{
  "session_id": "sess_20251125_001",
  "user_problem": "查询突然变慢，从5秒变成30秒",
  "created_at": "2025-11-25T10:00:00Z",

  "confirmed_facts": [
    {
      "fact": "wait_io 事件占比 65%",
      "from_user_input": true,
      "phenomenon_id": "P-0001",
      "timestamp": "2025-11-25T10:05:00Z"
    },
    {
      "fact": "索引 test_idx 从 2GB 增长到 12GB",
      "from_user_input": false,
      "phenomenon_id": "P-0002",
      "observation_result": "pg_relation_size(test_idx) = 12GB",
      "timestamp": "2025-11-25T10:10:00Z"
    }
  ],

  "active_hypotheses": [
    {
      "root_cause": "索引膨胀导致 IO 瓶颈",
      "confidence": 0.88,
      "supporting_phenomenon_ids": ["P-0001", "P-0002"],
      "supporting_ticket_ids": ["TICKET-001", "TICKET-005"],
      "missing_phenomena": [],
      "next_recommended_phenomenon_id": "P-0003"
    },
    {
      "root_cause": "统计信息过期导致执行计划错误",
      "confidence": 0.35,
      "supporting_phenomenon_ids": ["P-0001"],
      "supporting_ticket_ids": ["TICKET-010"],
      "missing_phenomena": ["统计信息更新时间"],
      "next_recommended_phenomenon_id": "P-0010"
    }
  ],

  "confirmed_phenomena": [
    {
      "phenomenon_id": "P-0001",
      "confirmed_at": "2025-11-25T10:05:00Z",
      "result_summary": "确认 wait_io 占比 65%"
    }
  ],

  "recommended_phenomenon_ids": ["P-0001", "P-0002"],

  "dialogue_history": [
    {
      "role": "user",
      "content": "查询突然变慢",
      "timestamp": "2025-11-25T10:00:00Z"
    },
    {
      "role": "assistant",
      "content": "请检查等待事件分布...",
      "timestamp": "2025-11-25T10:02:00Z"
    }
  ]
}
```

**字段说明**：
- `confirmed_facts`：用户确认的事实列表，关联到标准现象 ID
- `active_hypotheses`：活跃的根因假设，关联现象 ID 和工单 ID
- `confirmed_phenomena`：已确认的标准现象（用户执行了观察并反馈结果）
- `recommended_phenomenon_ids`：已推荐过的现象 ID 列表

### 4.5 数据处理流程（rebuild-index）

rebuild-index 是将原始数据转换为可检索数据的核心流程：

```
┌─────────────────────────────────────────────────────────────┐
│                    rebuild-index 流程                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 读取原始数据                                            │
│     raw_tickets + raw_anomalies                             │
│                    │                                        │
│                    ▼                                        │
│  2. 生成向量                                                │
│     对每个 raw_anomaly.description 调用 Embedding API       │
│                    │                                        │
│                    ▼                                        │
│  3. 向量聚类                                                │
│     相似度 > 阈值（如 0.85）的异常归为同一聚类              │
│                    │                                        │
│                    ▼                                        │
│  4. 生成标准现象（LLM）                                     │
│     每个聚类 → 一个 phenomenon                              │
│     - LLM 生成标准化 description                            │
│     - 选择最完整的 observation_method                       │
│                    │                                        │
│                    ▼                                        │
│  5. 关联映射                                                │
│     raw_anomaly → phenomenon_id                             │
│     生成 ticket_anomalies 表                                │
│                    │                                        │
│                    ▼                                        │
│  6. 构建向量索引                                            │
│     phenomena.embedding → 向量索引                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**核心算法**：

```python
def rebuild_index():
    """重建索引的完整流程"""

    # 1. 读取原始数据
    raw_anomalies = db.query("SELECT * FROM raw_anomalies")

    # 2. 生成向量
    for anomaly in raw_anomalies:
        anomaly.embedding = embedding_service.encode(anomaly.description)

    # 3. 向量聚类
    clusters = cluster_by_similarity(
        items=raw_anomalies,
        similarity_threshold=0.85
    )

    # 4. 为每个聚类生成标准现象
    phenomena = []
    for cluster_id, cluster_anomalies in clusters.items():
        phenomenon = generate_standard_phenomenon(cluster_anomalies)
        phenomena.append(phenomenon)

    # 5. 保存 phenomena 并建立关联
    for phenomenon in phenomena:
        db.insert_phenomenon(phenomenon)

        # 关联原始异常到现象
        for raw_anomaly_id in phenomenon.source_anomaly_ids:
            raw_anomaly = db.get_raw_anomaly(raw_anomaly_id)
            db.insert_ticket_anomaly(
                ticket_id=raw_anomaly.ticket_id,
                phenomenon_id=phenomenon.phenomenon_id,
                why_relevant=raw_anomaly.why_relevant,
                raw_anomaly_id=raw_anomaly_id
            )

    # 6. 构建向量索引
    build_vector_index(phenomena)


def generate_standard_phenomenon(cluster_anomalies: list) -> Phenomenon:
    """
    使用 LLM 为聚类生成标准现象
    """
    # 收集聚类中所有描述
    descriptions = [a.description for a in cluster_anomalies]
    methods = [a.observation_method for a in cluster_anomalies]

    # LLM 生成标准化描述
    prompt = f"""
以下是多个相似的数据库异常现象描述：
{chr(10).join(f'- {d}' for d in descriptions)}

请生成一个标准化的异常现象描述，要求：
1. 保留关键指标名称
2. 使用通用的阈值表述（如"超过阈值"而非具体数字）
3. 简洁明确

只输出标准化描述，不要其他内容。
"""
    standard_description = llm_service.generate(prompt)

    # 选择最完整的观察方法
    best_method = max(methods, key=lambda m: len(m) if m else 0)

    # 计算聚类中心向量
    embeddings = [a.embedding for a in cluster_anomalies]
    center_embedding = np.mean(embeddings, axis=0)

    return Phenomenon(
        phenomenon_id=generate_phenomenon_id(),
        description=standard_description,
        observation_method=best_method,
        source_anomaly_ids=[a.id for a in cluster_anomalies],
        cluster_size=len(cluster_anomalies),
        embedding=center_embedding
    )


def cluster_by_similarity(items: list, similarity_threshold: float) -> dict:
    """
    基于向量相似度的聚类算法

    使用简单的贪心聚类：
    1. 按顺序遍历所有项
    2. 对每个项，检查是否与现有聚类中心相似
    3. 如果相似，加入该聚类；否则创建新聚类
    """
    clusters = {}  # cluster_id -> list of items
    cluster_centers = {}  # cluster_id -> center embedding

    for item in items:
        matched_cluster = None
        max_similarity = 0

        # 检查与现有聚类的相似度
        for cluster_id, center in cluster_centers.items():
            similarity = cosine_similarity(item.embedding, center)
            if similarity > similarity_threshold and similarity > max_similarity:
                matched_cluster = cluster_id
                max_similarity = similarity

        if matched_cluster:
            # 加入现有聚类
            clusters[matched_cluster].append(item)
            # 更新聚类中心（增量平均）
            n = len(clusters[matched_cluster])
            cluster_centers[matched_cluster] = (
                cluster_centers[matched_cluster] * (n - 1) + item.embedding
            ) / n
        else:
            # 创建新聚类
            new_cluster_id = len(clusters)
            clusters[new_cluster_id] = [item]
            cluster_centers[new_cluster_id] = item.embedding

    return clusters
```

**粒度处理策略**（保守方案）：

当用户输入粒度较粗时，系统采用追问细化策略：

```python
def process_user_input(user_input: str, session: Session):
    """保守策略：粗粒度输入时用 LLM 追问"""

    # 1. 尝试精确匹配
    matches = vector_search(user_input, threshold=0.8)
    if matches:
        return handle_matches(matches, session)

    # 2. 用 LLM 判断输入粒度并引导
    return llm_guided_clarification(user_input, session)


def llm_guided_clarification(user_input: str, session: Session):
    """LLM 引导用户细化描述"""
    prompt = f"""
用户描述了一个数据库问题："{user_input}"

这个描述比较模糊，请生成 2-3 个追问选项帮助用户细化：
1. 每个选项应该是具体的现象或指标
2. 附带一个简单的观察命令（SQL 或 shell）

输出 JSON 格式：
{{"options": ["选项1", "选项2", ...], "observation_sql": "..."}}
"""
    response = llm_service.generate(prompt)
    return parse_clarification_response(response)
```

---

## 五、核心算法

### 5.1 现象级检索算法

**目标**：基于当前会话状态，从知识库中检索最相关的标准现象。

**输入**：
- 当前会话状态（包含已确认事实、已确认现象）
- 检索参数（top_k）

**输出**：
- 排序后的相关现象列表

**算法流程**：

```python
def retrieve_relevant_phenomena(session, top_k=10):
    # 1. 构建查询上下文
    query_context = build_query_context(session)
    # 示例: "查询变慢 + wait_io高 + n_tup_ins剧增"

    # 2. 向量检索（语义相似）
    query_embedding = call_embedding_api(query_context)
    vector_candidates = vector_index.search(query_embedding, k=50)

    # 3. 关键词过滤（提高精确度）
    keywords = extract_keywords(session.confirmed_facts)
    # 示例: ["wait_io", "65%", "索引", "膨胀"]

    filtered_phenomena = []
    for phenomenon_id in vector_candidates:
        phenomenon = db.get_phenomenon(phenomenon_id)
        # 检查现象是否包含关键词
        if contains_keywords(phenomenon, keywords):
            filtered_phenomena.append(phenomenon)

    # 4. 重排序（综合评分）
    scored_phenomena = []
    for phenomenon in filtered_phenomena:
        # 4.1 事实覆盖度（已确认事实与现象的匹配程度）
        fact_coverage = compute_fact_coverage(phenomenon, session.confirmed_facts)

        # 4.2 向量相似度
        vector_score = cosine_similarity(query_embedding, phenomenon.embedding)

        # 4.3 现象新颖度（避免重复推荐已确认现象）
        novelty = 1.0 if phenomenon.phenomenon_id not in session.confirmed_phenomena else 0.3

        # 综合评分
        final_score = 0.5 * fact_coverage + 0.3 * vector_score + 0.2 * novelty
        scored_phenomena.append((phenomenon, final_score))

    # 5. 排序并返回 Top-K
    scored_phenomena.sort(key=lambda x: x[1], reverse=True)
    return [p for p, score in scored_phenomena[:top_k]]
```

**关键点**：
- 向量检索召回 50 个候选（高召回）
- 关键词过滤提高精确度
- 多因素重排序平衡语义相似和事实匹配

### 5.2 多假设追踪与置信度计算

**目标**：维护多个并行的根因假设，动态计算和更新置信度。

**算法流程**：

```python
def update_hypotheses(session, new_facts):
    # 1. 检索可能的根因模式
    root_cause_candidates = retrieve_root_cause_patterns(session)

    # 2. 为每个根因构建假设
    hypotheses = []
    for rc_pattern in root_cause_candidates:
        # 2.1 找到支持该根因的所有现象
        supporting_phenomena = get_phenomena_by_root_cause(rc_pattern.root_cause)

        # 2.2 计算置信度
        confidence = compute_confidence(
            root_cause_pattern=rc_pattern,
            supporting_phenomena=supporting_phenomena,
            confirmed_facts=session.confirmed_facts,
            confirmed_phenomena=session.confirmed_phenomena
        )

        # 2.3 识别缺失的关键现象
        missing_phenomena = identify_missing_phenomena(
            root_cause_pattern=rc_pattern,
            confirmed_phenomena=session.confirmed_phenomena
        )

        # 2.4 推荐下一个观察现象
        next_phenomenon = recommend_next_phenomenon_for_hypothesis(
            rc_pattern, supporting_phenomena, session.confirmed_phenomena
        )

        hypotheses.append({
            "root_cause": rc_pattern.root_cause,
            "confidence": confidence,
            "supporting_phenomenon_ids": [p.phenomenon_id for p in supporting_phenomena],
            "missing_phenomena": missing_phenomena,
            "next_recommended_phenomenon_id": next_phenomenon.phenomenon_id if next_phenomenon else None
        })

    # 3. 保留 Top-3 假设
    hypotheses.sort(key=lambda h: h['confidence'], reverse=True)
    session.active_hypotheses = hypotheses[:3]

    return session
```

**置信度计算公式**：

```python
def compute_confidence(root_cause_pattern, supporting_phenomena,
                      confirmed_facts, confirmed_phenomena, denied_phenomenon_ids):
    """
    多因素加权计算置信度（2025-11-27 更新：增加否定惩罚）
    """
    # 1. 事实匹配度（权重 50%）- 使用 LLM 智能评估
    fact_score = evaluate_facts_for_hypothesis(
        root_cause_pattern.root_cause,
        supporting_phenomena,
        confirmed_facts
    )

    # 2. 现象确认进度（权重 30%）
    confirmed_count = count_confirmed_phenomena(supporting_phenomena, confirmed_phenomena)
    phenomenon_progress = confirmed_count / len(supporting_phenomena) if supporting_phenomena else 0

    # 3. 根因流行度（权重 10%）- 该根因在知识库中的频率
    frequency_score = min(root_cause_pattern.ticket_count / 10, 1.0)

    # 4. 问题描述相似度（权重 10%）
    desc_embedding = call_embedding_api(session.user_problem)
    desc_similarity = cosine_similarity(desc_embedding, root_cause_pattern.embedding)

    # 综合计算
    confidence = (
        0.5 * fact_score +
        0.3 * phenomenon_progress +
        0.1 * frequency_score +
        0.1 * desc_similarity
    )

    # 5. 否定惩罚：每个被否定的相关现象降低 15% 置信度（2025-11-27 新增）
    related_phenomenon_ids = get_phenomena_for_root_cause(root_cause_pattern.root_cause_id)
    denied_relevant_count = len(denied_phenomenon_ids & related_phenomenon_ids)
    if denied_relevant_count > 0:
        denial_penalty = denied_relevant_count * 0.15
        confidence = confidence * (1 - denial_penalty)

    return min(max(confidence, 0.0), 1.0)


def evaluate_facts_for_hypothesis(root_cause, supporting_phenomena, confirmed_facts):
    """
    使用 LLM 智能评估已确认事实对假设的支持程度（2025-11-26 更新）

    Returns:
        float: 事实评分 0-1
            > 0.5: 事实支持该假设
            < 0.5: 事实反对该假设
            = 0.5: 事实中性
    """
    if not confirmed_facts:
        return 0.5

    # 使用 LLM 评估每个事实
    fact_scores = []
    for fact in confirmed_facts:
        prompt = f'''
根因假设: {root_cause}
支持现象: {[p.description for p in supporting_phenomena[:3]]}
已确认事实: {fact.fact}

这个事实是否支持该假设？
- 正面支持（0.6-1.0）：事实表明该根因可能存在
- 负面反对（0.0-0.4）：事实表明该根因不太可能
- 中性无关（0.5）：事实与该根因无关

只输出数字（0.0-1.0）
'''
        try:
            score = float(llm_service.generate_simple(prompt))
            fact_scores.append(min(max(score, 0.0), 1.0))
        except:
            fact_scores.append(0.5)  # 失败时默认中性

    # 综合评分：如果有任何负面事实（<0.5），大幅降低整体评分
    if any(s < 0.5 for s in fact_scores):
        # 负面事实的影响：取最低分
        return min(fact_scores)
    else:
        # 全是支持或中性：取平均分
        return sum(fact_scores) / len(fact_scores)
```

**关键改进**（2025-11-26）：
- ✅ 使用 LLM 智能评估事实对假设的支持/反对程度
- ✅ 负面事实（如"IO 正常"）能有效降低相关假设的置信度
- ✅ 避免了简单关键词匹配的局限性

**关键改进**（2025-11-27）：
- ✅ 增加否定现象惩罚机制：每个被否定的相关现象降低 15% 置信度
- ✅ 修复 `recommended_phenomenon_ids` 和 `denied_phenomenon_ids` 属性问题（property → 实际列表操作）
- ✅ 正确使用 `RecommendedPhenomenon` 和 `DeniedPhenomenon` 模型记录状态

### 5.3 下一步推荐引擎

**目标**：根据当前假设状态，推荐下一波需要观察的现象（集合）。

**核心流程**：

```
┌─────────────────────────────────────────────────────────────┐
│                      对话循环                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  用户输入（现象描述）                                        │
│         │                                                   │
│         ▼                                                   │
│  1. 匹配 phenomena                                          │
│     - 向量检索 + 关键词匹配                                  │
│     - 粗粒度输入 → 追问细化                                  │
│         │                                                   │
│         ▼                                                   │
│  2. 更新 confirmed_facts                                    │
│     - 记录用户确认的现象                                     │
│         │                                                   │
│         ▼                                                   │
│  3. 计算工单置信度                                          │
│     - 置信度 = 已匹配现象数 / 工单总现象数                   │
│     - 考虑 why_relevant 的支持/反对                         │
│         │                                                   │
│         ▼                                                   │
│  4. 判断是否达到阈值                                        │
│         │                                                   │
│    ┌────┴────┐                                             │
│    │ > 0.85  │ ──→ 输出根因 + 解决方案 + 引用               │
│    └────┬────┘                                             │
│         │ < 0.85                                           │
│         ▼                                                   │
│  5. 推荐下一波现象（集合）                                   │
│     - 从 Top-N 工单中选取未确认的关键现象                    │
│     - 优先选能区分假设的现象                                 │
│         │                                                   │
│         ▼                                                   │
│  返回步骤 1（等待用户反馈）                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**决策逻辑**：

```python
def recommend_next_action(session):
    """
    两阶段决策：确认根因 / 推荐一波观察现象
    """
    if not session.active_hypotheses:
        return ask_for_initial_info(session)

    top_hypothesis = session.active_hypotheses[0]

    # 阶段 1: 高置信度 -> 确认根因
    if top_hypothesis['confidence'] > 0.85:
        return generate_root_cause_confirmation(session, top_hypothesis)

    # 阶段 2: 推荐一波现象（集合）
    recommended_phenomena = recommend_next_phenomena(
        session,
        top_k=3  # 每次推荐 3 个现象
    )

    if recommended_phenomena:
        return generate_batch_recommendation(session, recommended_phenomena)

    # 兜底：询问关键信息
    return ask_for_key_symptom(session, top_hypothesis)


def recommend_next_phenomena(session, top_k=3):
    """
    推荐下一波需要观察的现象（集合）

    策略：
    1. 从 Top-N 候选工单中收集未确认的现象
    2. 计算每个现象的"区分能力"（能区分多少假设）
    3. 返回高价值现象集合
    """
    confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}

    # 1. 获取 Top-N 候选工单
    candidate_tickets = get_top_tickets_by_confidence(session, n=5)

    # 2. 收集所有未确认的现象，并记录来源工单
    phenomenon_sources = {}  # phenomenon_id -> set of ticket_ids
    for ticket in candidate_tickets:
        for phenomenon_id in ticket.phenomenon_ids:
            if phenomenon_id not in confirmed_ids:
                if phenomenon_id not in phenomenon_sources:
                    phenomenon_sources[phenomenon_id] = set()
                phenomenon_sources[phenomenon_id].add(ticket.ticket_id)

    # 3. 计算每个现象的价值分数
    scored_phenomena = []
    for phenomenon_id, ticket_ids in phenomenon_sources.items():
        phenomenon = db.get_phenomenon(phenomenon_id)

        # 区分能力：被多少候选工单共同需要
        coverage_score = len(ticket_ids) / len(candidate_tickets)

        # 唯一性：如果只被一个工单需要，能有效区分假设
        uniqueness_score = 1.0 if len(ticket_ids) == 1 else 0.5

        # 综合分数：平衡"共同需要"和"能区分假设"
        final_score = 0.6 * coverage_score + 0.4 * uniqueness_score

        scored_phenomena.append({
            "phenomenon": phenomenon,
            "ticket_ids": ticket_ids,
            "score": final_score
        })

    # 4. 排序并返回 Top-K
    scored_phenomena.sort(key=lambda x: x["score"], reverse=True)
    return [item["phenomenon"] for item in scored_phenomena[:top_k]]


def generate_batch_recommendation(session, phenomena):
    """
    生成批量现象推荐响应
    """
    # 收集相关工单
    all_ticket_ids = set()
    for p in phenomena:
        ticket_ids = db.get_tickets_by_phenomenon(p.phenomenon_id)
        all_ticket_ids.update(ticket_ids)

    related_tickets = [db.get_ticket(tid) for tid in list(all_ticket_ids)[:5]]

    return {
        "action": "recommend_batch_observation",
        "phenomena": [
            {
                "id": p.phenomenon_id,
                "description": p.description,
                "method": p.observation_method
            }
            for p in phenomena
        ],
        "citations": [
            {
                "index": i + 1,
                "ticket_id": t.ticket_id,
                "description": truncate(t.description, 100),
                "root_cause": t.root_cause
            }
            for i, t in enumerate(related_tickets[:3])
        ],
        "message": format_batch_message(phenomena, related_tickets)
    }


def format_batch_message(phenomena, tickets):
    """
    格式化批量推荐消息
    """
    citation_markers = " ".join([f"[{i+1}]" for i in range(len(tickets))])

    message = f"为了进一步定位问题，建议您同时检查以下现象：\n\n"

    for i, p in enumerate(phenomena, 1):
        message += f"**{i}. {p.description}** [P-{p.phenomenon_id}]\n"
        message += f"```sql\n{p.observation_method}\n```\n\n"

    message += f"**引用工单：** {citation_markers}\n\n---\n"

    for i, ticket in enumerate(tickets, 1):
        message += f"\n[{i}] **Ticket {ticket.ticket_id}**: {ticket.description}"
        message += f"\n    根因: {ticket.root_cause}\n"

    message += "\n请反馈您观察到的结果。"

    return message
```

**设计优势**：
- ✅ 批量推荐：一次推荐多个现象，提高诊断效率
- ✅ 简化状态追踪：只追踪"已确认"和"未确认"，无步骤顺序
- ✅ 集合匹配：置信度 = 已匹配现象数 / 工单总现象数
- ✅ 智能选择：平衡"多工单共同需要"和"能区分假设"

**智能反馈识别**（2025-11-26 更新）：

```python
def mark_confirmed_phenomena_from_feedback(user_message, session):
    """
    从用户反馈中智能识别已确认的现象

    当用户反馈结果时（如"io 正常"），说明用户执行了最近推荐的观察。
    使用 LLM 自动识别执行反馈并标记现象为已确认。

    Args:
        user_message: 用户消息
        session: 会话状态
    """
    # 找到最近推荐的现象（还未标记为确认的）
    last_recommended_phenomenon_id = None
    if session.recommended_phenomenon_ids:
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}
        for phenomenon_id in reversed(session.recommended_phenomenon_ids):
            if phenomenon_id not in confirmed_ids:
                last_recommended_phenomenon_id = phenomenon_id
                break

    if not last_recommended_phenomenon_id:
        return  # 没有待确认的推荐现象

    # 使用 LLM 判断用户是否提供了观察反馈
    system_prompt = """你是对话分析助手。判断用户的消息是否包含对诊断观察的反馈。

执行反馈的特征：
1. 报告了观察结果（如"CPU 使用率 95%"、"IO 正常"）
2. 回答了诊断问题（如"是的"、"确认"）
3. 提供了检查结果（如"查询时间 30 秒"）

非执行反馈：
1. 单纯的问题（如"怎么检查？"）
2. 闲聊或其他话题

输出格式: 只输出 "yes" 或 "no" """

    user_prompt = f"用户消息: {user_message}\n\n这是否包含诊断观察的反馈？"

    try:
        response = llm_service.generate_simple(user_prompt, system_prompt)
        is_feedback = response.strip().lower() in ["yes", "是"]

        if is_feedback:
            # 标记为已确认
            session.confirmed_phenomena.append(
                ConfirmedPhenomenon(
                    phenomenon_id=last_recommended_phenomenon_id,
                    result_summary=user_message,
                )
            )
    except Exception:
        # LLM 调用失败时使用简单规则作为回退
        feedback_keywords = ["正常", "异常", "%", "占比", "发现", "显示", "是", "确认"]
        if any(keyword in user_message.lower() for keyword in feedback_keywords):
            session.confirmed_phenomena.append(
                ConfirmedPhenomenon(
                    phenomenon_id=last_recommended_phenomenon_id,
                    result_summary=user_message,
                )
            )
```

**关键改进**（2025-11-26）：
- ✅ 推荐引擎只排除 `confirmed_phenomena`，允许重复推荐未确认的现象（保守策略）
- ✅ 使用 LLM 自动识别用户反馈中的观察信号
- ✅ 区分"仅推荐"和"已确认"，避免误判

**区分性现象识别**：

```python
def find_discriminating_phenomenon(hypothesis1, hypothesis2, confirmed_phenomena):
    """
    找到能最大程度区分两个假设的现象
    """
    if not hypothesis2:
        # 只有一个假设，沿着该路径继续
        return get_next_unconfirmed_phenomenon(hypothesis1, confirmed_phenomena)

    # 找到 hypothesis1 独有的现象
    unique_phenomena_h1 = set(hypothesis1['supporting_phenomenon_ids']) - \
                          set(hypothesis2['supporting_phenomenon_ids'])

    # 选择还未确认的现象
    for phenomenon_id in unique_phenomena_h1:
        if phenomenon_id not in [p.phenomenon_id for p in confirmed_phenomena]:
            return db.get_phenomenon(phenomenon_id)

    # 如果没有独有现象，返回 hypothesis1 的下一个现象
    return get_next_unconfirmed_phenomenon(hypothesis1, confirmed_phenomena)
```

**多假设投票机制**：

```python
def find_common_recommended_phenomena(hypotheses, confirmed_phenomena):
    """
    从多个假设中找到共同推荐的现象（投票）
    """
    phenomenon_votes = {}

    for hyp in hypotheses:
        next_phenomenon = get_next_unconfirmed_phenomenon(hyp, confirmed_phenomena)
        if not next_phenomenon:
            continue

        # 语义聚类：相似的现象归为一组
        phenomenon_key = get_semantic_cluster_key(next_phenomenon.observation_method)

        if phenomenon_key not in phenomenon_votes:
            phenomenon_votes[phenomenon_key] = {
                'phenomenon': next_phenomenon,
                'weighted_votes': 0,
                'supporting_hypotheses': []
            }

        # 加权投票（按假设置信度加权）
        phenomenon_votes[phenomenon_key]['weighted_votes'] += hyp['confidence']
        phenomenon_votes[phenomenon_key]['supporting_hypotheses'].append(hyp['root_cause'])

    # 按投票数排序
    ranked = sorted(phenomenon_votes.values(),
                   key=lambda x: x['weighted_votes'],
                   reverse=True)

    return [v['phenomenon'] for v in ranked]
```

### 5.4 响应生成与引用构建

**目标**：生成用户可读的响应，并附带工单引用。

**响应结构**：

```python
def generate_phenomenon_recommendation(session, phenomenon):
    """
    生成现象观察推荐响应（带引用）
    """
    # 1. 查找包含该现象的相关工单
    related_tickets = db.query("""
        SELECT DISTINCT t.ticket_id, t.description, t.root_cause
        FROM tickets t
        JOIN ticket_anomalies ta ON t.ticket_id = ta.ticket_id
        WHERE ta.phenomenon_id = ?
        LIMIT 5
    """, phenomenon.phenomenon_id)

    # 2. 构建响应对象
    response = {
        "action": "recommend_observation",
        "phenomenon": {
            "id": phenomenon.phenomenon_id,
            "description": phenomenon.description,
            "method": phenomenon.observation_method
        },
        "citations": [
            {
                "index": i + 1,
                "ticket_id": t.ticket_id,
                "description": truncate(t.description, 100),
                "root_cause": t.root_cause,
                "url": f"/tickets/{t.ticket_id}"
            }
            for i, t in enumerate(related_tickets[:3])
        ],
        "message": format_message_with_citations(phenomenon, related_tickets)
    }

    return response


def format_message_with_citations(phenomenon, tickets):
    """
    格式化带引用的消息
    """
    citation_markers = " ".join([f"[{i+1}]" for i in range(len(tickets))])

    message = f"""
基于 {{len(tickets)}} 个相似案例，建议您观察以下现象：

**检查目标：** {{phenomenon.description}}

**具体操作：**
\`\`\`sql
{{phenomenon.observation_method}}
\`\`\`

**引用工单：** {{citation_markers}}

---
"""

    for i, ticket in enumerate(tickets, 1):
        message += f"\n[{i}] **Ticket {ticket.ticket_id}**: {ticket.description}"
        message += f"\n    根因: {ticket.root_cause}\n"

    return message
```

---

## 六、用户意图识别与复杂输入处理

### 6.1 设计背景

真实诊断场景中，用户可能会：
- 同时陈述多个事实
- 向系统提问（"检查了什么？"、"有什么结论？"）
- 建议诊断方向（"会不会是磁盘问题？"）
- 推翻之前的检查结果（"之前说错了，实际是..."）
- 在一句话中混合多种意图

为了提升用户体验和诊断效率，系统需要智能识别用户意图并做出相应处理。

### 6.2 意图分类体系

详细的意图分类和处理方案参见 [`design_proposal_251125.md`](./design_proposal_251125.md)。

**核心意图**（Phase 1，重要且阻塞）：
- **I-101: feedback** - 诊断反馈 ✅ 已实现
- **I-102: query** - 系统查询（询问诊断进展）
- **I-103: clarification_request** - 请求澄清（不懂怎么操作）
- **I-104: unable_to_execute** - 无法执行（遇到障碍）
- **I-105: correction** - 修正陈述（更正之前说的）
- **I-901: mixed** - 混合意图

**重要但非阻塞**（Phase 2）：
- **I-201: suggestion** - 方向建议
- **I-202: hypothesis_rejection** - 假设拒绝
- **I-203: partial_feedback** - 部分反馈
- **I-204: confirmation** - 确认/否定

**增强体验/高级对话**（Phase 3）：
- **I-301: urgency_expression** - 表达紧急性
- **I-302: context_reference** - 上下文引用
- **I-303: multi_issue** - 多问题报告
- **I-304: seek_explanation** - 寻求解释
- **I-305: chit_chat** - 闲聊/礼貌用语

### 6.3 实施计划

**Phase 1**（3-4天，已规划）：
- 实现 I-102（query）、I-103（clarification_request）、I-104（unable_to_execute）、I-105（correction）
- 基础混合意图处理（I-901）
- E2E 测试覆盖所有 Phase 1 意图

**Phase 2**（2-3天）：
- 实现用户建议临时加成、假设拒绝、部分反馈、确认转化

**Phase 3**（3-5天）：
- 实现上下文引用解析、紧急情况快速诊断、多问题识别、教育性内容生成

详细设计参见 `docs/design_proposal_251125.md`。

---

## 七、对话流程示例

### 7.1 V1 对话流程（步骤级，deprecated）

> **注意**：V1 架构基于 `diagnostic_steps` 表进行步骤级检索，已标记为 deprecated。

````
[第 1 轮]
用户: "生产环境查询突然变慢，原来 5 秒现在要 30 秒"

系统处理（V1 - StepRetriever）:
  1. 创建新会话，初始化状态
  2. 对 "查询变慢" 进行向量检索
  3. 召回 20 个相关步骤（from diagnostic_steps）
  4. 提取初始假设:
     - 假设1: 索引膨胀 (confidence=0.35)
     - 假设2: 统计信息过期 (confidence=0.30)
     - 假设3: 锁等待 (confidence=0.25)
  5. 3 个假设共同推荐: "检查等待事件分布"

系统响应:
  "您好！为了快速定位问题，建议先检查数据库的等待事件分布：

  **具体操作：**
  ```sql
  SELECT wait_event_type, wait_event, COUNT(*)
  FROM pg_stat_activity
  WHERE wait_event IS NOT NULL
  GROUP BY wait_event_type, wait_event
  ORDER BY COUNT(*) DESC;
  ```

  **诊断目的：** 确定是 IO、锁还是 CPU 瓶颈

  **引用工单：** [1] [2] [3]

  ---
  [1] **Ticket DB-001**: 报表查询慢，最终定位为索引膨胀
      根因: 索引膨胀导致 IO 瓶颈

  [2] **Ticket DB-005**: 高峰期查询变慢
      根因: 统计信息过期导致执行计划错误

  [3] **Ticket DB-012**: 在线交易查询超时
      根因: 长事务持锁导致等待
  "

---

[第 2 轮]
用户: "执行了，wait_io 占比 65%，平时只有 20%"

系统处理（V1 - HypothesisTracker）:
  1. 更新 confirmed_facts += ["wait_io 占比 65%"]
  2. 标记 executed_steps += [step_id]
  3. 重新计算置信度:
     - 假设1: 索引膨胀 (0.35 → 0.72) ↑
     - 假设2: 统计信息过期 (0.30 → 0.38)
     - 假设3: 锁等待 (0.25 → 0.10) ↓ (排除)
  4. 找区分性步骤: "检查索引大小"

系统响应:
  "wait_io 占比异常高说明存在磁盘 IO 瓶颈。请检查索引大小是否有异常增长：

  **具体操作：**
  ```sql
  SELECT
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
  FROM pg_indexes
  WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  ORDER BY pg_relation_size(indexrelid) DESC
  LIMIT 20;
  ```

  **诊断目的：** 确认是否存在索引膨胀问题

  **引用工单：** [1] [4]

  ---
  [1] **Ticket DB-001**: 报表查询慢，索引从 2GB 膨胀到 15GB
      根因: 索引膨胀导致 IO 瓶颈

  [4] **Ticket DB-018**: 定时任务执行变慢
      根因: 频繁更新导致索引碎片化
  "

---

[第 3 轮]
用户: "检查了，test_idx 从 2GB 涨到 12GB，增长太快了"

系统处理（V1 - RecommendationEngine）:
  1. 更新 confirmed_facts += ["索引 test_idx 从 2GB 增长到 12GB"]
  2. 标记 executed_steps += [step_id]
  3. 置信度: 假设1 = 0.88 (> 0.85 阈值)
  4. 触发根因确认流程

系统响应:
  "**根因已定位：索引膨胀导致 IO 瓶颈** (置信度: 88%)

  **诊断链路：**
  1. ✓ wait_io 占比 65% (正常 20%) → 确认磁盘 IO 瓶颈 [1][2]
  2. ✓ 索引 test_idx 异常增长 (2GB → 12GB) → 确认索引膨胀 [1]

  **建议解决方案：**

  **立即措施：**
  ```sql
  -- 在线重建索引（不阻塞业务）
  REINDEX INDEX CONCURRENTLY test_idx;
  ```

  **长期优化：**
  1. 配置定期 VACUUM:
     ```sql
     ALTER TABLE your_table SET (autovacuum_vacuum_scale_factor = 0.05);
     ```
  2. 监控索引膨胀率，设置告警阈值

  **引用工单：** [1] [4] [5]

  ---
  [1] **Ticket DB-001**: 报表查询慢，索引膨胀 7.5 倍
      根因: 索引膨胀导致 IO 瓶颈
      解决: REINDEX + 调整 autovacuum 参数

  [4] **Ticket DB-018**: 定时任务执行变慢
      根因: 频繁更新导致索引碎片化
      解决: 定期 REINDEX + 优化更新策略

  [5] **Ticket DB-023**: 索引维护最佳实践
      建议: 配置 autovacuum 参数，定期监控
  "
````

### 7.2 V1 未见问题处理示例

> **注意**：V1 架构基于步骤级检索，跨案例组合通过 `diagnostic_steps` 实现。

```
场景：用户遇到的问题是 "wait_io 高 + 表膨胀"（而非索引膨胀）

历史知识库：
  - Ticket A: wait_io 高 → 索引膨胀
  - Ticket B: n_dead_tup 剧增 → 表膨胀
  - 无完全匹配的案例

系统处理（V1 - 跨案例步骤组合）：
  1. 第 1 步推荐: "检查 wait_io" (来自 Ticket A 的 step_1)
  2. 用户反馈: "wait_io 65%"
  3. 标记 executed_steps += [step_1]
  4. 第 2 步推荐: "检查索引大小" (来自 Ticket A 的 step_2)
  5. 用户反馈: "索引正常，但 n_dead_tup 很高"
  6. 系统切换到 Ticket B 的路径
  7. 第 3 步推荐: "检查表膨胀" (来自 Ticket B 的 step_2)
  8. 最终定位: 表膨胀导致 IO 瓶颈

引用构建:
  [1] Ticket A (提供了 wait_io 诊断方法)
  [2] Ticket B (提供了表膨胀诊断方法)
```

### 7.3 V2 对话流程（现象级，推荐）

> **V2 架构**：基于 `phenomena` 和 `ticket_anomalies` 表进行现象级检索，支持更好的去重和复用。

````
[第 1 轮]
用户: "生产环境查询突然变慢，原来 5 秒现在要 30 秒"

系统处理（V2 - PhenomenonRetriever）:
  1. 创建新会话，初始化状态
  2. 对 "查询变慢" 进行向量检索
  3. 召回相关现象（from phenomena 表）
  4. 通过 ticket_anomalies 关联到根因，生成初始假设:
     - 假设1: 索引膨胀 (confidence=0.35)
       - supporting_phenomenon_ids: ["P-0001", "P-0002"]
       - supporting_ticket_ids: ["T-001", "T-005"]
     - 假设2: 统计信息过期 (confidence=0.30)
       - supporting_phenomenon_ids: ["P-0001", "P-0010"]
       - supporting_ticket_ids: ["T-010"]
  5. 推荐共同现象: P-0001 "wait_io 事件占比异常高"

系统响应:
  "您好！为了快速定位问题，建议先确认以下现象：

  **现象描述：** wait_io 事件占比异常高

  **观察方法：**
  ```sql
  SELECT wait_event_type, wait_event, COUNT(*)
  FROM pg_stat_activity
  WHERE wait_event IS NOT NULL
  GROUP BY wait_event_type, wait_event
  ORDER BY COUNT(*) DESC;
  ```

  **引用工单：** [1] [2] [3]

  ---
  [1] **Ticket T-001**: 报表查询慢，最终定位为索引膨胀
  [2] **Ticket T-005**: 高峰期查询变慢
  [3] **Ticket T-010**: 统计信息过期导致慢查询
  "

会话状态更新:
  - recommended_phenomenon_ids: ["P-0001"]

---

[第 2 轮]
用户: "执行了，wait_io 占比 65%，平时只有 20%"

系统处理（V2 - PhenomenonHypothesisTracker）:
  1. 更新 confirmed_facts += ["wait_io 占比 65%"]
  2. 标记 confirmed_phenomena += [P-0001]（用户确认了该现象）
  3. 使用 LLM 评估事实对假设的支持度
  4. 重新计算置信度:
     - 假设1: 索引膨胀 (0.35 → 0.72) ↑ 事实支持
     - 假设2: 统计信息过期 (0.30 → 0.38)
  5. 找区分性现象: P-0002 "索引大小异常增长"

系统响应:
  "wait_io 占比异常高说明存在磁盘 IO 瓶颈。请确认以下现象：

  **现象描述：** 索引大小异常增长

  **观察方法：**
  ```sql
  SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
  FROM pg_indexes
  WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  ORDER BY pg_relation_size(indexrelid) DESC
  LIMIT 20;
  ```

  **引用工单：** [1] [4]
  "

会话状态更新:
  - confirmed_phenomena: [P-0001]
  - recommended_phenomenon_ids: ["P-0001", "P-0002"]

---

[第 3 轮]
用户: "检查了，test_idx 从 2GB 涨到 12GB，增长太快了"

系统处理（V2 - PhenomenonRecommendationEngine）:
  1. 更新 confirmed_facts += ["索引 test_idx 从 2GB 增长到 12GB"]
  2. 标记 confirmed_phenomena += [P-0002]
  3. 置信度: 假设1 = 0.88 (> 0.85 阈值)
  4. 触发根因确认流程

系统响应:
  "**根因已定位：索引膨胀导致 IO 瓶颈** (置信度: 88%)

  **观察到的现象：**
  诊断过程中确认了两个关键现象：wait_io 占比达到 65%（正常水平约 20%），以及索引 test_idx 从 2GB 增长到 12GB。这些现象表明系统存在明显的 IO 等待问题。

  **推理链路：**
  高 IO 等待通常由磁盘读写瓶颈导致。结合索引异常增长的现象，可以判断索引膨胀导致 B-tree 层级增加，每次查询需要更多的磁盘 IO 操作，从而引发 IO 瓶颈。历史案例 T-001 和 T-005 也出现过类似的现象组合。

  **恢复措施：**
  1. 立即执行在线索引重建：`REINDEX INDEX CONCURRENTLY test_idx;`
  2. 配置 autovacuum 参数防止索引再次膨胀
  3. 建立索引大小监控告警

  **引用工单：** [1] [2]

  ---
  [1] **Ticket T-001**: 报表查询慢，索引膨胀 7.5 倍
      根因: 索引膨胀导致 IO 瓶颈
      解决: REINDEX + 调整 autovacuum 参数

  [2] **Ticket T-005**: 定时任务执行变慢
      根因: 频繁更新导致索引碎片化
      解决: 定期 REINDEX + 优化更新策略
  "

会话状态更新:
  - confirmed_phenomena: [P-0001, P-0002]
  - active_hypotheses[0].confidence: 0.88
````

### 7.4 V2 未见问题处理示例

> **V2 架构优势**：现象级检索天然支持跨案例组合，通过 `phenomena` 表的去重复用实现。

```
场景：用户遇到的问题是 "wait_io 高 + 表膨胀"（而非索引膨胀）

知识库结构（V2）：
  phenomena 表:
    - P-0001: "wait_io 事件占比异常高"
    - P-0002: "索引大小异常增长"
    - P-0003: "n_dead_tup 剧增"
    - P-0004: "表大小异常增长"

  ticket_anomalies 关联:
    - T-001 (索引膨胀): P-0001, P-0002
    - T-002 (表膨胀): P-0001, P-0003, P-0004

系统处理（V2 - 现象级跨案例组合）：
  1. 推荐现象 P-0001: "wait_io 事件占比异常高"
     （被 T-001 和 T-002 共同关联）
  2. 用户反馈: "wait_io 65%"
  3. 标记 confirmed_phenomena += [P-0001]
  4. 推荐现象 P-0002: "索引大小异常增长"
     （区分 T-001 vs T-002）
  5. 用户反馈: "索引正常"
  6. 事实评估: "索引正常" 反对假设"索引膨胀"，置信度下降
  7. 自动切换到 T-002 路径
  8. 推荐现象 P-0003: "n_dead_tup 剧增"
  9. 用户反馈: "n_dead_tup 确实很高"
  10. 标记 confirmed_phenomena += [P-0003]
  11. 最终定位: 表膨胀导致 IO 瓶颈

V2 优势体现:
  - P-0001 被多个工单复用，无需重复定义
  - 现象确认状态独立追踪（confirmed_phenomena）
  - LLM 智能评估负面事实（"索引正常"降低索引膨胀假设置信度）

引用构建:
  [1] Ticket T-001 (提供了 P-0001 现象)
  [2] Ticket T-002 (提供了 P-0003, P-0004 现象)
```

### 7.5 CLI 交互演示示例

以下是一个真实可运行的 CLI 交互示例（约 3-4 轮定位根因）：

```
$ python -m cli.main

╔══════════════════════════════════════════════════════════════╗
║          数据库问题诊断助手 (V2 - 现象级诊断)                ║
╠══════════════════════════════════════════════════════════════╣
║  输入问题描述开始诊断，支持以下命令：                        ║
║    /help   - 查看帮助                                        ║
║    /status - 查看当前诊断状态                                ║
║    /reset  - 重置会话                                        ║
║    /exit   - 退出程序                                        ║
╚══════════════════════════════════════════════════════════════╝

> 查询变慢，原来几秒现在要半分钟

──────────────────────────────────────────────────
[第 1 轮] 正在分析问题...
  → 检索相关现象...
  → 检索根因候选...
  → 评估假设 (1/3): 索引膨胀导致 IO 瓶颈...
  → 评估假设 (2/3): 频繁更新导致索引碎片化...
  → 评估假设 (3/3): 统计信息过期导致执行...
  → 生成推荐...

建议确认以下 3 个现象

  1. [P-0001] wait_io 事件占比异常高
     推荐原因: 可能与「索引膨胀导致 IO 瓶颈」相关
     观察方法:
     SELECT wait_event_type, wait_event, count(*)
     FROM pg_stat_activity WHERE state = 'active'
     GROUP BY 1, 2 ORDER BY 3 DESC;

  2. [P-0002] 索引大小异常增长
     推荐原因: 可能与「索引膨胀导致 IO 瓶颈」相关
     观察方法:
     SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid))
     FROM pg_indexes ORDER BY pg_relation_size(indexrelid) DESC LIMIT 10;

  3. [P-0047] 索引碎片率异常高
     推荐原因: 可能与「频繁更新导致索引碎片化」相关
     观察方法:
     SELECT schemaname, relname, n_dead_tup, n_live_tup
     FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;

请检查上述现象并反馈结果（如：1确认 2确认 3否定）

──────────────────────────────────────────────────
[Summary] 第 1 轮完成
  已确认现象: 0
  假设置信度:
    1. [███░░░░░░░] 32% 索引膨胀导致 IO 瓶颈...
    2. [██░░░░░░░░] 28% 频繁更新导致索引碎片化...
    3. [██░░░░░░░░] 25% 统计信息过期导致执行...

> 1确认 2确认 3否定

──────────────────────────────────────────────────
[第 2 轮] 正在处理反馈...
  → 识别用户反馈...
  → 更新假设置信度...
  → 检索根因候选...
  → 评估假设 (1/3): 索引膨胀导致 IO 瓶颈...
  → 评估假设 (2/3): 频繁更新导致索引碎片化...
  → 评估假设 (3/3): 统计信息过期导致执行...
  → 生成推荐...

建议确认以下 2 个现象

  1. [P-0003] n_dead_tup 数量异常高，autovacuum 未及时清理
     推荐原因: 可能与「索引膨胀导致 IO 瓶颈」相关
     观察方法:
     SELECT relname, n_dead_tup, last_autovacuum
     FROM pg_stat_user_tables WHERE n_dead_tup > 10000;

  2. [P-0048] 执行 REINDEX 后性能恢复
     推荐原因: 可能与「索引膨胀导致 IO 瓶颈」相关
     观察方法:
     REINDEX INDEX CONCURRENTLY <index_name>;
     -- 对比重建前后的查询时间

请检查上述现象并反馈结果

──────────────────────────────────────────────────
[Summary] 第 2 轮完成
  已确认现象: 2
  假设置信度:
    1. [██████░░░░] 58% 索引膨胀导致 IO 瓶颈...
    2. [███░░░░░░░] 22% 频繁更新导致索引碎片化...
    3. [██░░░░░░░░] 18% 统计信息过期导致执行...

> 1确认 2确认

──────────────────────────────────────────────────
[第 3 轮] 正在处理反馈...
  → 识别用户反馈...
  → 更新假设置信度...
  → 检索根因候选...
  → 评估假设 (1/2): 索引膨胀导致 IO 瓶颈...
  → 评估假设 (2/2): 频繁更新导致索引碎片化...
  → 生成推荐...

══════════════════════════════════════════════════
  根因已定位：索引膨胀导致 IO 瓶颈
  置信度: 82%
══════════════════════════════════════════════════

【诊断总结】

**观察到的现象：**
诊断过程中确认了以下关键现象：
1. wait_io 事件占比异常高，表明存在 IO 等待问题
2. 索引大小出现异常增长
3. n_dead_tup 数量高，autovacuum 未及时清理死元组
4. 执行 REINDEX 后查询性能明显恢复

**推理链路：**
高 IO 等待通常由磁盘读写瓶颈引起。结合索引异常增长和死元组
堆积的现象，可以判断：频繁的数据更新产生了大量死元组，而
autovacuum 未能及时清理，导致索引膨胀。膨胀的索引增加了
B-tree 层级，每次查询需要更多的磁盘 IO，最终引发 IO 瓶颈。
REINDEX 后性能恢复进一步验证了这一判断。

**恢复措施：**
1. 立即执行在线索引重建：
   REINDEX INDEX CONCURRENTLY <index_name>;
2. 调整 autovacuum 参数，加快死元组清理：
   ALTER TABLE <table> SET (autovacuum_vacuum_scale_factor = 0.05);
3. 建立索引大小监控告警，防止再次膨胀

引用工单: [DB-001] [DB-018]

──────────────────────────────────────────────────
[Summary] 第 3 轮完成
  已确认现象: 4
  假设置信度:
    1. [████████░░] 82% 索引膨胀导致 IO 瓶颈...
    2. [██░░░░░░░░] 15% 频繁更新导致索引碎片化...

诊断完成，再见！
```

**演示要点**：

1. **第 1 轮**：用户描述问题 → 系统推荐 3 个现象（来自多个假设）
2. **第 2 轮**：用户批量确认/否定 → 假设置信度更新，高置信度假设优先
3. **第 3 轮**：置信度达到阈值 → 输出 LLM 生成的诊断总结

**用户输入格式**：
- `确认` / `是` / `看到了` - 确认所有待确认现象
- `1确认 2否定 3确认` - 批量确认/否定
- `全否定` / `都不是` - 否定所有待确认现象

---

## 八、实施计划

### 8.1 项目目录结构

```
dbdiag/
├── dbdiag/                       # 核心业务逻辑（领域层）
│   ├── __init__.py
│   ├── __main__.py               # CLI 入口
│   ├── api/                      # FastAPI 接口
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI 主服务
│   │   ├── chat.py               # 对话接口
│   │   └── session.py            # 会话管理接口
│   ├── core/                     # 核心逻辑
│   │   ├── __init__.py
│   │   ├── dialogue_manager.py   # 对话管理器
│   │   ├── hypothesis_tracker.py # 多假设追踪器
│   │   ├── retriever.py          # 现象检索引擎
│   │   ├── recommender.py        # 下一步推荐引擎
│   │   └── response_generator.py # 响应生成器
│   ├── models/                   # 数据模型
│   │   ├── __init__.py
│   │   ├── session.py            # 会话数据模型
│   │   ├── ticket.py             # 工单数据模型
│   │   └── phenomenon.py         # 现象数据模型
│   ├── services/                 # 服务层
│   │   ├── __init__.py
│   │   ├── llm_service.py        # LLM API 调用
│   │   ├── embedding_service.py  # Embedding API 调用
│   │   └── session_service.py    # 会话持久化
│   └── utils/                    # 工具函数
│       ├── __init__.py
│       ├── config.py             # 配置加载
│       └── vector_utils.py       # 向量计算工具
│   ├── cli/                      # 命令行界面
│   │   ├── __init__.py
│   │   ├── main.py               # CLI 主程序
│   │   └── formatter.py          # 输出格式化
├── scripts/                      # 初始化脚本
│   ├── init_db.py                # 初始化数据库
│   ├── import_tickets.py         # 数据导入脚本
│   ├── rebuild_index.py          # 重建索引（phenomena、root_causes）
│   └── visualize_knowledge_graph.py  # 知识图谱可视化
├── tests/                        # 测试
│   ├── unit/                     # 单元测试
│   └── e2e/                      # 端到端测试
├── data/                         # 数据存储（运行时生成）
│   ├── tickets.db                # SQLite 数据库
│   └── knowledge_graph.html      # 知识图谱可视化
├── docs/
│   └── design.md                 # 本设计文档
├── .gitignore
├── config.yaml.example           # 配置示例
├── requirements.txt
└── README.md
```

### 8.2 开发阶段

**Phase 1: 数据层与存储**
- [x] 设计并实现 SQLite 数据库 schema
- [x] 实现数据导入脚本（JSON → SQLite）
- [x] 调用 Embedding API 生成向量并存储
- [x] 构建全文检索索引

**Phase 2: 检索与推理核心**
- [x] 实现现象级检索算法
- [x] 实现多假设追踪器
- [x] 实现置信度计算逻辑
- [x] 实现下一步推荐引擎
- [x] 单元测试

**Phase 3: 对话管理与 API**
- [x] 实现会话状态管理
- [x] 实现对话管理器
- [x] 实现响应生成器（含引用构建）
- [x] 开发 FastAPI 接口
- [x] 集成 LLM API（用于自然语言生成）

**Phase 4: CLI 与端到端测试**
- [x] 开发命令行交互界面
- [x] 准备演示数据集（25 个工单）
- [x] 端到端测试与调优
- [x] 知识图谱可视化工具

---

## 九、关键技术细节

### 9.1 向量检索实现

使用 `sqlite-vec` 扩展在 SQLite 中存储和检索向量：

```sql
-- 创建向量索引
CREATE VIRTUAL TABLE step_embeddings_idx USING vec0(
    step_id TEXT PRIMARY KEY,
    embedding FLOAT[1024]  -- 假设 embedding 维度为 1024
);

-- 向量相似度检索
SELECT step_id, distance
FROM step_embeddings_idx
WHERE embedding MATCH ?
  AND k = 50
ORDER BY distance;
```

### 9.2 LLM API 调用

统一封装 LLM API 调用，支持 OpenAI 兼容接口：

```python
class LLMService:
    def __init__(self, config):
        self.api_base = config.llm.api_base
        self.api_key = config.llm.api_key
        self.model = config.llm.model
        self.temperature = config.llm.temperature

    def generate(self, prompt, system_prompt=None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = openai.ChatCompletion.create(
            api_base=self.api_base,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            temperature=self.temperature
        )

        return response.choices[0].message.content
```

### 9.3 Embedding API 调用

```python
class EmbeddingService:
    def __init__(self, config):
        self.api_base = config.embedding_model.api_base
        self.api_key = config.embedding_model.api_key
        self.model = config.embedding_model.model

    def encode(self, text):
        response = openai.Embedding.create(
            api_base=self.api_base,
            api_key=self.api_key,
            model=self.model,
            input=text
        )
        return response.data[0].embedding

    def encode_batch(self, texts):
        response = openai.Embedding.create(
            api_base=self.api_base,
            api_key=self.api_key,
            model=self.model,
            input=texts
        )
        return [item.embedding for item in response.data]
```

### 9.4 会话持久化策略

**简单方案（MVP）**：
- 每次更新会话时，将整个 `state_json` 序列化并更新到 SQLite
- 会话读取时反序列化

**优化方案（可选）**：
- 使用 JSON 文件存储活跃会话（更快的读写）
- 定期或会话结束时同步到 SQLite（持久化备份）

---

## 十、MVP 验证指标

### 10.1 功能指标

| 指标 | 目标值 | 验证方式 |
|------|--------|----------|
| **首轮相关性** | ≥ 70% | 准备 20 个测试问题，首轮推荐步骤的相关性人工评估 |
| **平均对话轮次** | ≤ 4 轮 | 从问题描述到根因确认的平均轮数 |
| **引用准确率** | 100% | 每个推荐/结论必须有有效的工单引用 |
| **未见问题支持率** | ≥ 50% | 构造 10 个知识库中不存在的组合问题，评估系统能否给出合理建议 |

### 10.2 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| **检索延迟** | < 200ms | 向量检索 + 重排序的总时间 |
| **置信度计算延迟** | < 100ms | 更新假设和计算置信度的时间 |
| **响应生成延迟** | < 10s | 包含 LLM API 调用的端到端响应时间 |
| **系统总响应时间** | < 12s | 从用户输入到返回完整响应的时间 |

**说明**：
- LLM API 调用通常需要 5-8 秒（取决于模型和负载）
- 总响应时间目标设为 < 12 秒，为 LLM 调用和其他处理留出余量
- 检索和计算部分尽量优化到 < 500ms，确保响应时间主要取决于 LLM

### 10.3 质量指标

| 指标 | 目标值 | 验证方式 |
|------|--------|----------|
| **根因准确率** | ≥ 80% | 在测试集上，最终给出的根因判断是否正确 |
| **步骤有效性** | ≥ 85% | 推荐的诊断步骤是否确实有助于缩小问题范围 |
| **引用相关性** | ≥ 90% | 引用的工单与当前问题的相关程度 |

---

## 十一、风险与应对

### 11.1 技术风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **向量检索召回率低** | 无法找到相关步骤 | 1. 结合全文检索（FTS5）<br>2. 调整检索参数（top_k）<br>3. 优化 embedding 模型选择 |
| **LLM API 不稳定** | 响应超时或失败 | 1. 实现重试机制<br>2. 降级方案（模板化响应）<br>3. 缓存常见响应 |
| **置信度计算不准确** | 错误的根因判断 | 1. 收集反馈数据调优权重<br>2. 人工标注验证集<br>3. 增加置信度阈值 |
| **SQLite 性能瓶颈** | 大规模数据时查询慢 | 1. 优化索引<br>2. 迁移到 PostgreSQL<br>3. 向量索引独立部署 |

### 11.2 数据风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **标注数据质量差** | 检索和推理效果差 | 1. 制定标注规范<br>2. 数据验证脚本<br>3. 迭代优化标注 |
| **知识库覆盖不足** | 无法处理新问题 | 1. 持续补充工单数据<br>2. 记录未覆盖问题<br>3. 专家规则补充 |
| **步骤描述不一致** | 语义聚类失败 | 1. 标注时统一术语<br>2. 数据清洗<br>3. LLM 辅助归一化 |

### 11.3 产品风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **用户输入不明确** | 无法有效检索 | 1. 主动引导用户描述<br>2. 提供问题模板<br>3. 澄清问询机制 |
| **对话轮次过多** | 用户体验差 | 1. 优化置信度阈值<br>2. 改进区分性步骤识别<br>3. 支持跳过步骤 |
| **引用过于生硬** | 可读性差 | 1. LLM 生成自然语言<br>2. 优化响应模板<br>3. 用户反馈迭代 |

---

## 十二、扩展路径

### 12.1 近期优化（MVP 后 1-2 个月）

1. **步骤转移关系学习**
   - 统计历史对话中的步骤转移模式
   - 构建 `step_transitions` 表
   - 利用共现关系优化推荐

2. **用户反馈学习**
   - 记录用户采纳/拒绝的推荐
   - 基于反馈调整置信度权重
   - A/B 测试不同策略

3. **LLM 辅助步骤组装**
   - Prompt Engineering 优化
   - 让 LLM 基于多个案例生成组合步骤
   - Few-shot learning

### 12.2 中期增强（3-6 个月）

1. **图数据库集成**
   - 使用 Neo4j 存储现象-步骤-根因关系图
   - 基于图的路径规划
   - 支持复杂的推理链

2. **多模态输入支持**
   - 上传日志文件
   - 识别截图中的错误信息
   - 时间序列数据分析

3. **主动监控集成**
   - 接入数据库监控系统
   - 自动获取实时指标
   - 减少手动操作步骤

### 12.3 长期演进（6+ 个月）

1. **生产级部署**
   - 迁移到 PostgreSQL + pgvector
   - 分布式向量索引（Milvus）
   - 高可用架构

2. **领域模型微调**
   - 基于标注数据微调 Embedding 模型
   - 微调 LLM 用于生成
   - 持续学习机制

3. **专家协作模式**
   - 专家审核推荐
   - 专家标注新案例
   - 知识库管理工具

---

## 十三、总结

本设计方案基于**步骤级检索**和**多假设追踪**的核心理念，构建了一个轻量级、可扩展的数据库问题诊断助手系统。

**核心优势**：
1. ✅ **天然支持跨案例组合**：从一开始就按步骤检索，无需架构改造
2. ✅ **多假设并行追踪**：容错性强，适应不确定性
3. ✅ **强制引用溯源**：每个推荐都有明确出处，可信度高
4. ✅ **轻量级部署**：SQLite + API 调用，无需复杂依赖
5. ✅ **平滑扩展路径**：可逐步引入图数据库、微调模型等增强

**适用场景**：
- ✅ MVP 快速验证
- ✅ 小团队部署演示
- ✅ 数据驱动的专家系统
- ✅ 持续学习和迭代

通过本方案，可以在 **4 周内交付可演示的 MVP**，并为后续生产化和智能化升级奠定坚实基础。

---

## 十四、V2 代码架构（2025-11-26）

### 14.1 架构升级概述

V2 架构将系统从"步骤级检索"升级为"现象级检索"，核心变更：

| V1 组件 | V2 组件 | 变更说明 |
|---------|---------|----------|
| `DiagnosticStep` | `Phenomenon` | 检索单位从步骤变为标准现象 |
| `StepRetriever` | `PhenomenonRetriever` | 从 `diagnostic_steps` 表检索变为从 `phenomena` 表 |
| `HypothesisTracker` | `PhenomenonHypothesisTracker` | 假设追踪基于现象而非步骤 |
| `RecommendationEngine` | `PhenomenonRecommendationEngine` | 推荐现象而非步骤 |
| `DialogueManager` | `PhenomenonDialogueManager` | 整合所有 V2 组件 |

### 14.2 向后兼容性

V1 组件保留但标记为 **deprecated**，使用时会触发警告：

```python
# V1 使用方式（deprecated，会触发 DeprecationWarning）
from dbdiag.core.retriever import StepRetriever
retriever = StepRetriever(db_path, embedding_service)

# V2 使用方式（推荐）
from dbdiag.core.retriever import PhenomenonRetriever
retriever = PhenomenonRetriever(db_path, embedding_service)
```

### 14.3 V2 核心类

#### 14.3.1 PhenomenonRetriever

```python
class PhenomenonRetriever:
    """现象检索器 (V2)"""

    def __init__(self, db_path: str, embedding_service: EmbeddingService = None):
        ...

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        vector_candidates: int = 50,
        keywords: Optional[List[str]] = None,
        excluded_phenomenon_ids: Optional[Set[str]] = None,
    ) -> List[tuple[Phenomenon, float]]:
        """
        检索相关的标准现象

        Returns:
            (现象, 得分) 列表，按得分降序排列
        """
        ...
```

#### 14.3.2 PhenomenonHypothesisTracker

```python
class PhenomenonHypothesisTracker:
    """基于现象的假设追踪器 (V2)"""

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService = None,
    ):
        ...

    def update_hypotheses(
        self,
        session: SessionState,
        new_facts: List[ConfirmedFact] = None,
    ) -> SessionState:
        """
        更新会话的假设列表

        假设包含 V2 字段：
        - supporting_phenomenon_ids: 支持该假设的现象 ID 列表
        - supporting_ticket_ids: 相关工单 ID 列表
        - next_recommended_phenomenon_id: 推荐的下一个现象
        """
        ...
```

#### 14.3.3 PhenomenonRecommendationEngine

```python
class PhenomenonRecommendationEngine:
    """基于现象的推荐引擎 (V2)"""

    def __init__(self, db_path: str, llm_service: LLMService):
        ...

    def recommend_next_action(self, session: SessionState) -> Dict[str, any]:
        """
        推荐下一步行动

        返回动作类型：
        - ask_initial_info: 询问初始信息
        - confirm_root_cause: 确认根因（高置信度）
        - recommend_phenomenon: 推荐验证现象（中置信度）
        - ask_symptom: 询问关键症状（低置信度）
        """
        ...
```

#### 14.3.4 PhenomenonDialogueManager

```python
class PhenomenonDialogueManager:
    """基于现象的对话管理器 (V2)"""

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: Optional["EmbeddingService"] = None,
    ):
        # 初始化 V2 组件
        self.hypothesis_tracker = PhenomenonHypothesisTracker(...)
        self.recommender = PhenomenonRecommendationEngine(...)
        ...

    def start_conversation(self, user_problem: str) -> Dict[str, Any]:
        """开始新对话"""
        ...

    def continue_conversation(
        self, session_id: str, user_message: str
    ) -> Dict[str, Any]:
        """继续对话，支持确认现象反馈"""
        ...
```

### 14.4 会话状态 V2 字段

`SessionState` 新增字段支持现象级追踪：

```python
class SessionState(BaseModel):
    # ... V1 字段 ...

    # V2 新增字段
    confirmed_phenomena: List[ConfirmedPhenomenon] = []  # 已确认的现象
    recommended_phenomenon_ids: List[str] = []           # 已推荐的现象 ID


class Hypothesis(BaseModel):
    root_cause_id: str                                        # 根因 ID（外键关联 root_causes）
    confidence: float                                          # 置信度 0-1
    missing_phenomena: List[str] = []                          # 缺失的关键现象描述

    # V2 新增字段
    supporting_phenomenon_ids: List[str] = []            # 支持该假设的现象
    supporting_ticket_ids: List[str] = []                # 相关工单
    next_recommended_phenomenon_id: Optional[str] = None # 推荐的下一个现象
```

### 14.5 数据表使用

V2 组件在运行时使用以下数据表（不直接访问 `raw_*` 表）：

| 表名 | 用途 |
|------|------|
| `phenomena` | 标准现象库，V2 检索的主表 |
| `ticket_anomalies` | 现象与工单的关联，用于获取 root_cause_id |
| `tickets` | 处理后的工单信息，包含 root_cause_id 外键 |
| `root_causes` | 根因信息表，包含描述和解决方案 |
| `sessions` | 会话状态持久化（支持 V2 字段） |

**说明**：`raw_tickets` 和 `raw_anomalies` 仅在 `rebuild-index` 阶段使用，运行时代码通过 `tickets` + `root_causes` 获取数据。

### 14.6 单元测试覆盖

V2 架构新增单元测试文件：

| 测试文件 | 覆盖内容 |
|----------|----------|
| `tests/unit/test_retriever.py` | PhenomenonRetriever + StepRetriever deprecation |
| `tests/unit/test_hypothesis_tracker.py` | PhenomenonHypothesisTracker + deprecation |
| `tests/unit/test_recommender.py` | PhenomenonRecommendationEngine + deprecation |
| `tests/unit/test_dialogue_manager.py` | PhenomenonDialogueManager + deprecation |

**测试统计**：107 个单元测试全部通过。
