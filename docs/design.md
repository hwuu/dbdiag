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
diagnostic_steps:
  - observed_fact: "wait_io 事件占比 65%，远超日常 20% 水平"
    observation_method: "SELECT event, count FROM pg_stat_activity WHERE wait_event IS NOT NULL"
    analysis_result: "IO 等待高说明磁盘读写存在瓶颈，需进一步定位热点表或索引"
  - observed_fact: "索引 test_idx 大小从 2GB 增长到 12GB"
    observation_method: "SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid)) FROM pg_indexes"
    analysis_result: "索引膨胀导致扫描IO增加，确认为主要原因"
root_cause: "索引膨胀导致 IO 瓶颈"
solution: "执行 REINDEX INDEX CONCURRENTLY test_idx; 并配置定期 VACUUM"
```

---

## 二、核心设计理念

### 2.1 关键洞察

数据库问题诊断本质上是一个**决策树遍历过程**：
- 每一步根据当前已知信息选择下一个最有价值的观察动作
- 通过累积观察到的现象，逐步缩小根因可能性范围
- 最终在置信度足够高时给出根因判断和解决方案

### 2.2 设计原则

1. **步骤级检索**（Step-Level Retrieval）
   - 检索的最小单位是单个诊断步骤（diagnostic_step），而非整个工单
   - 支持从不同工单中提取相关步骤进行组合

2. **上下文累积**（Context Accumulation）
   - 每轮对话累积更多已确认的现象
   - 基于累积的上下文动态调整假设和推荐

3. **多路径并行**（Multi-Hypothesis Tracking）
   - 同时追踪 Top-N 个最可能的根因假设
   - 动态评估每个假设的置信度
   - 推荐能最大程度区分不同假设的诊断步骤

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
│  • tickets 表                          │
│  • diagnostic_steps 表 (展平)          │
│  • root_cause_patterns 表              │
│  • step_embeddings (向量索引)          │
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
| **前端 UI** | Gradio / Streamlit | 快速原型，可交互演示 |
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

### 4.1 存储层数据表

#### 4.1.1 工单表 (tickets)

存储原始工单数据：

```sql
CREATE TABLE tickets (
    ticket_id TEXT PRIMARY KEY,
    metadata_json TEXT,           -- JSON: {"version": "...", "module": "...", "severity": "..."}
    description TEXT,             -- 问题描述
    root_cause TEXT,              -- 根因
    solution TEXT,                -- 解决方案
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.2 诊断步骤表 (diagnostic_steps)

**核心表**，将每个工单的诊断步骤展平存储，作为检索的最小单元：

```sql
CREATE TABLE diagnostic_steps (
    step_id TEXT PRIMARY KEY,              -- 格式: {ticket_id}_step_{index}
    ticket_id TEXT,
    step_index INTEGER,                    -- 步骤在工单中的顺序

    -- 步骤内容
    observed_fact TEXT,                    -- 观察到的现象
    observation_method TEXT,               -- 具体操作（SQL、命令等）
    analysis_result TEXT,                  -- 推理结果

    -- 冗余字段（便于检索）
    ticket_description TEXT,               -- 冗余工单描述
    ticket_root_cause TEXT,                -- 冗余根因

    -- 向量字段
    fact_embedding BLOB,                   -- observed_fact 的向量表示
    method_embedding BLOB,                 -- observation_method 的向量表示

    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
);

-- 全文检索索引
CREATE VIRTUAL TABLE steps_fts USING fts5(
    observed_fact,
    observation_method,
    analysis_result,
    content=diagnostic_steps
);
```

**设计说明**：
- 每个 `diagnostic_step` 是独立的检索单元，支持跨工单组合
- `fact_embedding` 和 `method_embedding` 分别存储，因为用户可能只描述现象或只提供观察结果
- 全文检索索引用于关键词匹配

#### 4.1.3 根因模式表 (root_cause_patterns)

预聚合的根因模式，用于快速匹配和假设生成：

```sql
CREATE TABLE root_cause_patterns (
    pattern_id TEXT PRIMARY KEY,
    root_cause TEXT,                       -- 根因描述
    key_symptoms TEXT,                     -- 关键症状列表（JSON 数组）
    related_step_ids TEXT,                 -- 相关步骤 ID 列表（JSON 数组）
    ticket_count INTEGER,                  -- 支持该根因的工单数量
    embedding BLOB                         -- 根因的向量表示
);
```

#### 4.1.4 会话表 (sessions)

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

### 4.2 会话状态结构

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
      "step_id": null,
      "timestamp": "2025-11-25T10:05:00Z"
    },
    {
      "fact": "索引 test_idx 从 2GB 增长到 12GB",
      "from_user_input": false,
      "step_id": "TICKET-001_step_2",
      "observation_result": "pg_relation_size(test_idx) = 12GB",
      "timestamp": "2025-11-25T10:10:00Z"
    }
  ],

  "active_hypotheses": [
    {
      "root_cause": "索引膨胀导致 IO 瓶颈",
      "confidence": 0.88,
      "supporting_step_ids": [
        "TICKET-001_step_1",
        "TICKET-001_step_2",
        "TICKET-005_step_3"
      ],
      "missing_facts": [],
      "next_recommended_step_id": "TICKET-001_step_3"
    },
    {
      "root_cause": "统计信息过期导致执行计划错误",
      "confidence": 0.35,
      "supporting_step_ids": ["TICKET-010_step_1"],
      "missing_facts": ["统计信息更新时间"],
      "next_recommended_step_id": "TICKET-010_step_2"
    }
  ],

  "executed_steps": [
    {
      "step_id": "TICKET-001_step_1",
      "executed_at": "2025-11-25T10:05:00Z",
      "result_summary": "确认 wait_io 占比 65%"
    }
  ],

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

---

## 五、核心算法

### 5.1 步骤级检索算法

**目标**：基于当前会话状态，从知识库中检索最相关的诊断步骤。

**输入**：
- 当前会话状态（包含已确认事实、已执行步骤）
- 检索参数（top_k）

**输出**：
- 排序后的相关步骤列表

**算法流程**：

```python
def retrieve_relevant_steps(session, top_k=10):
    # 1. 构建查询上下文
    query_context = build_query_context(session)
    # 示例: "查询变慢 + wait_io高 + n_tup_ins剧增"

    # 2. 向量检索（语义相似）
    query_embedding = call_embedding_api(query_context)
    vector_candidates = vector_index.search(query_embedding, k=50)

    # 3. 关键词过滤（提高精确度）
    keywords = extract_keywords(session.confirmed_facts)
    # 示例: ["wait_io", "65%", "索引", "膨胀"]

    filtered_steps = []
    for step_id in vector_candidates:
        step = db.get_step(step_id)
        # 检查步骤是否包含关键词
        if contains_keywords(step, keywords):
            filtered_steps.append(step)

    # 4. 重排序（综合评分）
    scored_steps = []
    for step in filtered_steps:
        # 4.1 事实覆盖度（已确认事实与步骤的匹配程度）
        fact_coverage = compute_fact_coverage(step, session.confirmed_facts)

        # 4.2 向量相似度
        vector_score = cosine_similarity(query_embedding, step.fact_embedding)

        # 4.3 步骤新颖度（避免重复推荐已执行步骤）
        novelty = 1.0 if step.step_id not in session.executed_steps else 0.3

        # 综合评分
        final_score = 0.5 * fact_coverage + 0.3 * vector_score + 0.2 * novelty
        scored_steps.append((step, final_score))

    # 5. 排序并返回 Top-K
    scored_steps.sort(key=lambda x: x[1], reverse=True)
    return [step for step, score in scored_steps[:top_k]]
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
        # 2.1 找到支持该根因的所有步骤
        supporting_steps = get_steps_by_root_cause(rc_pattern.root_cause)

        # 2.2 计算置信度
        confidence = compute_confidence(
            root_cause_pattern=rc_pattern,
            supporting_steps=supporting_steps,
            confirmed_facts=session.confirmed_facts,
            executed_steps=session.executed_steps
        )

        # 2.3 识别缺失的关键事实
        missing_facts = identify_missing_facts(
            root_cause_pattern=rc_pattern,
            confirmed_facts=session.confirmed_facts
        )

        # 2.4 推荐下一步
        next_step = recommend_next_step_for_hypothesis(
            rc_pattern, supporting_steps, session.executed_steps
        )

        hypotheses.append({
            "root_cause": rc_pattern.root_cause,
            "confidence": confidence,
            "supporting_step_ids": [s.step_id for s in supporting_steps],
            "missing_facts": missing_facts,
            "next_recommended_step_id": next_step.step_id if next_step else None
        })

    # 3. 保留 Top-3 假设
    hypotheses.sort(key=lambda h: h['confidence'], reverse=True)
    session.active_hypotheses = hypotheses[:3]

    return session
```

**置信度计算公式**：

```python
def compute_confidence(root_cause_pattern, supporting_steps,
                      confirmed_facts, executed_steps):
    """
    多因素加权计算置信度
    """
    # 1. 事实匹配度（权重 50%）
    required_facts = extract_key_symptoms(root_cause_pattern)
    matched_count = count_matched_facts(required_facts, confirmed_facts)
    fact_coverage = matched_count / len(required_facts) if required_facts else 0

    # 2. 步骤执行进度（权重 30%）
    executed_count = count_executed_steps(supporting_steps, executed_steps)
    step_progress = executed_count / len(supporting_steps) if supporting_steps else 0

    # 3. 根因流行度（权重 10%）- 该根因在知识库中的频率
    frequency_score = min(root_cause_pattern.ticket_count / 10, 1.0)

    # 4. 问题描述相似度（权重 10%）
    desc_embedding = call_embedding_api(session.user_problem)
    desc_similarity = cosine_similarity(desc_embedding, root_cause_pattern.embedding)

    # 综合计算
    confidence = (
        0.5 * fact_coverage +
        0.3 * step_progress +
        0.1 * frequency_score +
        0.1 * desc_similarity
    )

    return confidence
```

### 5.3 下一步推荐引擎

**目标**：根据当前假设状态，决定下一步应该采取的行动。

**决策逻辑**：

```python
def recommend_next_action(session):
    """
    三阶段决策：确认根因 / 推荐步骤 / 询问信息
    """
    if not session.active_hypotheses:
        return ask_for_initial_info(session)

    top_hypothesis = session.active_hypotheses[0]

    # 阶段 1: 高置信度 -> 确认根因
    if top_hypothesis['confidence'] > 0.85:
        return generate_root_cause_confirmation(session, top_hypothesis)

    # 阶段 2: 中置信度 -> 推荐验证步骤
    if top_hypothesis['confidence'] > 0.50:
        # 找到能区分 Top1 和 Top2 假设的步骤
        next_step = find_discriminating_step(
            session.active_hypotheses[0],
            session.active_hypotheses[1] if len(session.active_hypotheses) > 1 else None,
            session.executed_steps
        )

        if next_step:
            return generate_step_recommendation(session, next_step)

    # 阶段 3: 低置信度 -> 多假设投票或主动询问
    common_steps = find_common_recommended_steps(
        session.active_hypotheses[:3],
        session.executed_steps
    )

    if common_steps:
        # 多个假设都推荐的步骤（高价值）
        return generate_step_recommendation(session, common_steps[0])

    # 兜底：询问关键信息
    return ask_for_key_symptom(session, top_hypothesis)
```

**区分性步骤识别**：

```python
def find_discriminating_step(hypothesis1, hypothesis2, executed_steps):
    """
    找到能最大程度区分两个假设的步骤
    """
    if not hypothesis2:
        # 只有一个假设，沿着该路径继续
        return get_next_unexecuted_step(hypothesis1, executed_steps)

    # 找到 hypothesis1 独有的步骤
    unique_steps_h1 = set(hypothesis1['supporting_step_ids']) - \
                      set(hypothesis2['supporting_step_ids'])

    # 选择还未执行的步骤
    for step_id in unique_steps_h1:
        if step_id not in [s['step_id'] for s in executed_steps]:
            return db.get_step(step_id)

    # 如果没有独有步骤，返回 hypothesis1 的下一步
    return get_next_unexecuted_step(hypothesis1, executed_steps)
```

**多假设投票机制**：

```python
def find_common_recommended_steps(hypotheses, executed_steps):
    """
    从多个假设中找到共同推荐的步骤（投票）
    """
    step_votes = {}

    for hyp in hypotheses:
        next_step = get_next_unexecuted_step(hyp, executed_steps)
        if not next_step:
            continue

        # 语义聚类：相似的步骤归为一组
        step_key = get_semantic_cluster_key(next_step.observation_method)

        if step_key not in step_votes:
            step_votes[step_key] = {
                'step': next_step,
                'weighted_votes': 0,
                'supporting_hypotheses': []
            }

        # 加权投票（按假设置信度加权）
        step_votes[step_key]['weighted_votes'] += hyp['confidence']
        step_votes[step_key]['supporting_hypotheses'].append(hyp['root_cause'])

    # 按投票数排序
    ranked = sorted(step_votes.values(),
                   key=lambda x: x['weighted_votes'],
                   reverse=True)

    return [v['step'] for v in ranked]
```

### 5.4 响应生成与引用构建

**目标**：生成用户可读的响应，并附带工单引用。

**响应结构**：

```python
def generate_step_recommendation(session, step):
    """
    生成步骤推荐响应（带引用）
    """
    # 1. 查找推荐该步骤的相关工单
    related_tickets = db.query("""
        SELECT DISTINCT t.ticket_id, t.description, t.root_cause
        FROM tickets t
        JOIN diagnostic_steps ds ON t.ticket_id = ds.ticket_id
        WHERE ds.step_id = ?
           OR ds.observation_method LIKE ?
        LIMIT 5
    """, step.step_id, f"%{extract_key_operation(step.observation_method)}%")

    # 2. 构建响应对象
    response = {
        "action": "recommend_step",
        "step": {
            "description": step.observed_fact,
            "method": step.observation_method,
            "purpose": step.analysis_result
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
        "message": format_message_with_citations(step, related_tickets)
    }

    return response


def format_message_with_citations(step, tickets):
    """
    格式化带引用的消息
    """
    citation_markers = " ".join([f"[{i+1}]" for i in range(len(tickets))])

    message = f"""
基于 {{len(tickets)}} 个相似案例，建议您执行以下操作：

**检查目标：** {{step.observed_fact}}

**具体操作：**
\`\`\`sql
{{step.observation_method}}
\`\`\`

**诊断目的：** {{step.analysis_result}}

**引用工单：** {{citation_markers}}

---
"""

    for i, ticket in enumerate(tickets, 1):
        message += f"\n[{i}] **Ticket {ticket.ticket_id}**: {ticket.description}"
        message += f"\n    根因: {ticket.root_cause}\n"

    return message
```

---

## 六、对话流程示例

### 6.1 完整对话流程

````
[第 1 轮]
用户: "生产环境查询突然变慢，原来 5 秒现在要 30 秒"

系统处理:
  1. 创建新会话，初始化状态
  2. 对 "查询变慢" 进行向量检索
  3. 召回 20 个相关步骤
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

系统处理:
  1. 更新 confirmed_facts += ["wait_io 占比 65%"]
  2. 重新计算置信度:
     - 假设1: 索引膨胀 (0.35 → 0.72) ↑
     - 假设2: 统计信息过期 (0.30 → 0.38)
     - 假设3: 锁等待 (0.25 → 0.10) ↓ (排除)
  3. 找区分性步骤: "检查索引大小"

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

系统处理:
  1. 更新 confirmed_facts += ["索引 test_idx 从 2GB 增长到 12GB"]
  2. 置信度: 假设1 = 0.88 (> 0.85 阈值)
  3. 触发根因确认流程

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

### 6.2 未见问题处理示例

```
场景：用户遇到的问题是 "wait_io 高 + 表膨胀"（而非索引膨胀）

历史知识库：
  - Ticket A: wait_io 高 → 索引膨胀
  - Ticket B: n_dead_tup 剧增 → 表膨胀
  - 无完全匹配的案例

系统处理（跨案例组合）：
  1. 第 1 步推荐: "检查 wait_io" (来自 Ticket A 的 step_1)
  2. 用户反馈: "wait_io 65%"
  3. 第 2 步推荐: "检查索引大小" (来自 Ticket A 的 step_2)
  4. 用户反馈: "索引正常，但 n_dead_tup 很高"
  5. 系统切换到 Ticket B 的路径
  6. 第 3 步推荐: "检查表膨胀" (来自 Ticket B 的 step_2)
  7. 最终定位: 表膨胀导致 IO 瓶颈

引用构建:
  [1] Ticket A (提供了 wait_io 诊断方法)
  [2] Ticket B (提供了表膨胀诊断方法)
```

---

## 七、实现计划

### 7.1 项目目录结构

```
dbdiag/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 主服务
│   ├── api/
│   │   ├── __init__.py
│   │   ├── chat.py                # 对话接口
│   │   └── session.py             # 会话管理接口
│   ├── core/
│   │   ├── __init__.py
│   │   ├── dialogue_manager.py    # 对话管理器
│   │   ├── hypothesis_tracker.py  # 多假设追踪器
│   │   ├── retriever.py           # 检索引擎
│   │   ├── recommender.py         # 下一步推荐引擎
│   │   └── response_generator.py  # 响应生成器
│   ├── models/
│   │   ├── __init__.py
│   │   ├── session.py             # 会话数据模型
│   │   ├── ticket.py              # 工单数据模型
│   │   └── step.py                # 步骤数据模型
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_service.py         # LLM API 调用
│   │   ├── embedding_service.py   # Embedding API 调用
│   │   └── db_service.py          # 数据库操作
│   └── utils/
│       ├── __init__.py
│       ├── config.py              # 配置加载
│       └── vector_utils.py        # 向量计算工具
├── data/
│   └── example_tickets.json       # 示例工单数据（用于演示和测试）
├── scripts/
│   ├── import_tickets.py          # 数据导入脚本
│   ├── build_embeddings.py        # 构建向量索引
│   └── init_db.py                 # 初始化数据库
├── ui/
│   ├── gradio_app.py              # Gradio UI
│   └── streamlit_app.py           # Streamlit UI（可选）
├── tests/
│   ├── __init__.py
│   ├── test_retriever.py
│   ├── test_hypothesis_tracker.py
│   └── test_e2e.py                # 端到端测试
├── docs/
│   ├── design.md                  # 本设计文档
│   └── api.md                     # API 文档
├── .gitignore
├── config.yaml.example            # 配置示例
├── requirements.txt
├── Dockerfile
└── README.md

注意：运行时生成的文件（如 data/tickets.db、data/sessions/ 等）不会提交到 git 中
```

### 7.2 开发阶段

**Phase 1: 数据层与存储 (Week 1)**
- [ ] 设计并实现 SQLite 数据库 schema
- [ ] 实现数据导入脚本（YAML → SQLite）
- [ ] 集成 sqlite-vec 插件
- [ ] 调用 Embedding API 生成向量并存储
- [ ] 构建全文检索索引

**Phase 2: 检索与推理核心 (Week 2)**
- [ ] 实现步骤级检索算法
- [ ] 实现多假设追踪器
- [ ] 实现置信度计算逻辑
- [ ] 实现下一步推荐引擎
- [ ] 单元测试

**Phase 3: 对话管理与 API (Week 3)**
- [ ] 实现会话状态管理
- [ ] 实现对话管理器（状态机）
- [ ] 实现响应生成器（含引用构建）
- [ ] 开发 FastAPI 接口
- [ ] 集成 LLM API（用于自然语言生成）

**Phase 4: UI 与端到端测试 (Week 4)**
- [ ] 开发 Gradio 交互界面
- [ ] 准备演示数据集（20-30 个工单）
- [ ] 端到端测试与调优
- [ ] 编写部署文档

---

## 八、关键技术细节

### 8.1 向量检索实现

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

### 8.2 LLM API 调用

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

### 8.3 Embedding API 调用

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

### 8.4 会话持久化策略

**简单方案（MVP）**：
- 每次更新会话时，将整个 `state_json` 序列化并更新到 SQLite
- 会话读取时反序列化

**优化方案（可选）**：
- 使用 JSON 文件存储活跃会话（更快的读写）
- 定期或会话结束时同步到 SQLite（持久化备份）

---

## 九、MVP 验证指标

### 9.1 功能指标

| 指标 | 目标值 | 验证方式 |
|------|--------|----------|
| **首轮相关性** | ≥ 70% | 准备 20 个测试问题，首轮推荐步骤的相关性人工评估 |
| **平均对话轮次** | ≤ 4 轮 | 从问题描述到根因确认的平均轮数 |
| **引用准确率** | 100% | 每个推荐/结论必须有有效的工单引用 |
| **未见问题支持率** | ≥ 50% | 构造 10 个知识库中不存在的组合问题，评估系统能否给出合理建议 |

### 9.2 性能指标

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

### 9.3 质量指标

| 指标 | 目标值 | 验证方式 |
|------|--------|----------|
| **根因准确率** | ≥ 80% | 在测试集上，最终给出的根因判断是否正确 |
| **步骤有效性** | ≥ 85% | 推荐的诊断步骤是否确实有助于缩小问题范围 |
| **引用相关性** | ≥ 90% | 引用的工单与当前问题的相关程度 |

---

## 十、风险与应对

### 10.1 技术风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **向量检索召回率低** | 无法找到相关步骤 | 1. 结合全文检索（FTS5）<br>2. 调整检索参数（top_k）<br>3. 优化 embedding 模型选择 |
| **LLM API 不稳定** | 响应超时或失败 | 1. 实现重试机制<br>2. 降级方案（模板化响应）<br>3. 缓存常见响应 |
| **置信度计算不准确** | 错误的根因判断 | 1. 收集反馈数据调优权重<br>2. 人工标注验证集<br>3. 增加置信度阈值 |
| **SQLite 性能瓶颈** | 大规模数据时查询慢 | 1. 优化索引<br>2. 迁移到 PostgreSQL<br>3. 向量索引独立部署 |

### 10.2 数据风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **标注数据质量差** | 检索和推理效果差 | 1. 制定标注规范<br>2. 数据验证脚本<br>3. 迭代优化标注 |
| **知识库覆盖不足** | 无法处理新问题 | 1. 持续补充工单数据<br>2. 记录未覆盖问题<br>3. 专家规则补充 |
| **步骤描述不一致** | 语义聚类失败 | 1. 标注时统一术语<br>2. 数据清洗<br>3. LLM 辅助归一化 |

### 10.3 产品风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **用户输入不明确** | 无法有效检索 | 1. 主动引导用户描述<br>2. 提供问题模板<br>3. 澄清问询机制 |
| **对话轮次过多** | 用户体验差 | 1. 优化置信度阈值<br>2. 改进区分性步骤识别<br>3. 支持跳过步骤 |
| **引用过于生硬** | 可读性差 | 1. LLM 生成自然语言<br>2. 优化响应模板<br>3. 用户反馈迭代 |

---

## 十一、扩展路径

### 11.1 近期优化（MVP 后 1-2 个月）

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

### 11.2 中期增强（3-6 个月）

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

### 11.3 长期演进（6+ 个月）

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

## 十二、总结

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
