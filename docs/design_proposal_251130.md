# 设计提案：基于 RAG + LLM 的简化诊断方案

**日期**: 2025-11-30
**状态**: 提案阶段

---

## 一、背景

当前 V2 架构采用多模块协作的方式进行诊断：

```
用户输入 → Retriever → HypothesisTracker → Recommender → ResponseGenerator
              ↓              ↓                  ↓
         检索现象      追踪假设置信度      多因素打分推荐
```

这种架构虽然可控性强、可解释性好，但复杂度较高，维护成本大。

本提案探讨一种 **naive 但实用** 的替代方案：直接用 RAG 检索相关工单，让 LLM 端到端完成推理和决策。

---

## 二、方案概述

### 2.1 核心思路

每轮对话：
1. **RAG 检索**：根据用户输入 + 对话历史，检索相关的 `raw_tickets`
2. **LLM 决策**：LLM 根据检索到的工单和上下文，决定：
   - **继续收集信息**：推荐用户检查 1-3 个现象
   - **给出诊断结论**：输出根因分析报告

### 2.2 架构对比

| 维度 | 现有 V2 架构 | 本提案 |
|------|-------------|--------|
| 核心模块 | Retriever + HypothesisTracker + Recommender + ResponseGenerator | RAG + LLM |
| 数据依赖 | phenomena, root_causes, phenomenon_root_causes 等多表 | raw_tickets（单表） |
| 决策方式 | 规则 + 打分公式 | LLM 端到端推理 |
| 代码复杂度 | 高 | 低 |
| 可解释性 | 高（量化置信度、打分依据） | 中（依赖 LLM 输出） |

---

## 三、优缺点分析

### 3.1 优点

1. **架构大幅简化**
   - 去掉 phenomenon 聚类、hypothesis tracking、recommender 打分等复杂模块
   - 核心逻辑可能只需 100-200 行代码

2. **灵活性高**
   - LLM 可以自由组合不同工单的信息
   - 不受预定义 phenomenon 的限制
   - 能理解用户自然语言描述的微妙差异

3. **无需预处理**
   - 不需要 rebuild-index 生成 phenomena/root_causes
   - 直接使用原始工单数据

4. **易于迭代**
   - 改进主要通过调整 prompt 实现
   - 不需要修改复杂的算法逻辑

### 3.2 缺点与风险

| 问题 | 风险等级 | 说明 | 缓解措施 |
|------|----------|------|----------|
| **RAG 召回质量** | 高 | 用户描述模糊时检索不准 | 多阶段检索、query 扩展 |
| **上下文长度限制** | 中 | 工单多时超出 context window | 截断、摘要、分批处理 |
| **一致性问题** | 中 | 重复推荐已问过的现象 | 结构化状态追踪 + guardrails |
| **判断时机不当** | 高 | 过早给结论或过晚收敛 | prompt 工程 + 置信度阈值 |
| **可解释性下降** | 中 | 推理过程是黑盒 | 要求 LLM 输出 reasoning |
| **Hallucination** | 高 | 编造不存在的现象或方案 | 引用校验 + 结构化输出 |
| **成本问题** | 低 | 每轮调用 LLM | 可接受，按需优化 |

---

## 四、详细设计

### 4.1 数据流

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              每轮对话流程                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  用户输入                                                                     │
│      │                                                                       │
│      ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 1. 构建检索 Query                                                    │    │
│  │    - 当前用户输入                                                    │    │
│  │    - 累积状态摘要（已确认/已否定现象）                                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│      │                                                                       │
│      ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 2. RAG 检索 raw_tickets                                              │    │
│  │    - 向量相似度检索 top-K 工单                                       │    │
│  │    - 可选：LLM rerank 精排                                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│      │                                                                       │
│      ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 3. LLM 推理与决策                                                    │    │
│  │    输入：                                                            │    │
│  │      - 检索到的 raw_tickets（含 anomalies, root_cause, solution）    │    │
│  │      - 累积状态（已确认/已否定现象）                                  │    │
│  │      - 用户问题描述                                                  │    │
│  │    输出（结构化 JSON）：                                              │    │
│  │      - action: "recommend" | "diagnose"                              │    │
│  │      - confidence: 0-1                                               │    │
│  │      - content: 推荐现象列表 或 诊断报告                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│      │                                                                       │
│      ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 4. 后处理 & Guardrails                                               │    │
│  │    - 检查推荐现象是否已问过                                          │    │
│  │    - 验证引用的工单确实存在                                          │    │
│  │    - 更新累积状态                                                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│      │                                                                       │
│      ▼                                                                       │
│  渲染输出                                                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 累积状态结构

每轮对话维护一个结构化的累积状态，避免对话历史过长：

```python
@dataclass
class NaiveSessionState:
    """简化版会话状态"""
    session_id: str
    user_problem: str                    # 用户原始问题

    confirmed_observations: List[str]    # 已确认的观察（用户反馈"确认"）
    denied_observations: List[str]       # 已否定的观察（用户反馈"否定"）
    asked_observations: List[str]        # 已问过的观察（避免重复推荐）

    relevant_ticket_ids: Set[str]        # 曾检索到的相关工单 ID

    dialogue_turns: int                  # 对话轮次
```

### 4.3 LLM Prompt 设计

#### 4.3.1 系统 Prompt

```
你是一个数据库运维问题诊断助手。你的任务是根据用户描述的问题和历史工单数据，
帮助用户定位问题的根本原因。

## 工作模式

你有两种输出模式：
1. **推荐模式 (recommend)**：当证据不足时，推荐用户检查 1-3 个可能相关的现象
2. **诊断模式 (diagnose)**：当证据充足时，给出根因分析报告

## 判断标准

选择"诊断模式"的条件（满足任一）：
- 用户确认的现象与某个根因高度匹配（≥3 个关键现象）
- 检索到的工单中有明确匹配用户场景的案例
- 已经进行了 3 轮以上的现象确认，且有明显倾向

选择"推荐模式"的条件：
- 信息不足以确定根因
- 存在多个可能的根因需要区分

## 输出格式

必须输出有效的 JSON，格式如下：

推荐模式：
{
  "action": "recommend",
  "confidence": 0.45,
  "reasoning": "用户描述了查询变慢，但缺少 IO、锁、索引等关键观察...",
  "recommendations": [
    {
      "observation": "wait_io 事件占比",
      "method": "SELECT wait_event_type, count(*) FROM pg_stat_activity...",
      "why": "高 IO 等待通常与索引膨胀或磁盘瓶颈相关",
      "related_root_causes": ["索引膨胀", "磁盘 IO 瓶颈"]
    }
  ]
}

诊断模式：
{
  "action": "diagnose",
  "confidence": 0.85,
  "root_cause": "索引膨胀导致 IO 瓶颈",
  "reasoning": "用户确认了 wait_io 高、索引增长异常、REINDEX 后恢复...",
  "observed_phenomena": ["wait_io 占比 65%", "索引从 2GB 增长到 12GB"],
  "solution": "1. REINDEX INDEX CONCURRENTLY...\n2. 配置 autovacuum...",
  "cited_tickets": ["T-0001", "T-0018"]
}
```

#### 4.3.2 用户 Prompt 模板

```
## 用户问题
{user_problem}

## 当前状态
- 已确认的观察：{confirmed_observations}
- 已否定的观察：{denied_observations}
- 对话轮次：{dialogue_turns}

## 用户本轮输入
{user_message}

## 相关历史工单
{formatted_tickets}

请根据以上信息，决定是推荐用户检查更多现象，还是给出诊断结论。
```

### 4.4 RAG 检索策略

#### 4.4.1 检索 Query 构建

```python
def build_search_query(state: NaiveSessionState, user_message: str) -> str:
    """构建检索 query"""
    parts = [state.user_problem]

    # 加入已确认的观察
    if state.confirmed_observations:
        parts.append("确认现象: " + ", ".join(state.confirmed_observations))

    # 加入当前用户输入（如果不是简单的确认/否定）
    if not is_simple_feedback(user_message):
        parts.append(user_message)

    return " ".join(parts)
```

#### 4.4.2 检索流程

```python
def retrieve_tickets(query: str, top_k: int = 10) -> List[RawTicket]:
    """检索相关工单"""
    # 1. 向量检索
    query_embedding = embedding_service.encode(query)
    candidates = vector_search(query_embedding, top_k=top_k * 2)

    # 2. 可选：LLM rerank
    if len(candidates) > top_k:
        candidates = llm_rerank(query, candidates, top_k=top_k)

    return candidates
```

### 4.5 Guardrails 设计

```python
def apply_guardrails(
    llm_output: dict,
    state: NaiveSessionState,
    retrieved_tickets: List[RawTicket],
) -> dict:
    """后处理检查"""

    if llm_output["action"] == "recommend":
        # 1. 过滤已问过的观察
        recommendations = llm_output["recommendations"]
        filtered = [
            r for r in recommendations
            if r["observation"] not in state.asked_observations
        ]

        # 2. 如果全被过滤，强制进入诊断模式
        if not filtered and llm_output["confidence"] > 0.5:
            return force_diagnose(llm_output, state, retrieved_tickets)

        llm_output["recommendations"] = filtered[:3]

    elif llm_output["action"] == "diagnose":
        # 验证引用的工单确实存在
        valid_ticket_ids = {t.ticket_id for t in retrieved_tickets}
        cited = llm_output.get("cited_tickets", [])
        llm_output["cited_tickets"] = [
            tid for tid in cited if tid in valid_ticket_ids
        ]

    return llm_output
```

---

## 五、实现计划

### 5.1 文件结构

```
dbdiag/
├── core/
│   ├── naive_dialogue_manager.py  # 新增：简化版对话管理器
│   └── ...                        # 现有文件不变
├── cli/
│   └── main.py                    # 可选：添加 --naive 开关
└── ...
```

### 5.2 实现步骤

| 步骤 | 内容 | 预计工作量 |
|------|------|-----------|
| 1 | 实现 `NaiveSessionState` 数据结构 | 小 |
| 2 | 实现 RAG 检索（复用现有 EmbeddingService） | 小 |
| 3 | 设计并调试 LLM Prompt | 中 |
| 4 | 实现 Guardrails | 小 |
| 5 | 集成到 CLI（添加 `--naive` 开关或新命令） | 小 |
| 6 | 测试与对比评估 | 中 |

### 5.3 评估指标

与现有 V2 方案对比：

- **定位准确率**：最终给出的根因是否正确
- **平均对话轮次**：多少轮能定位到根因
- **用户体验**：推荐的现象是否有意义、是否重复
- **代码复杂度**：代码行数、模块数量

---

## 六、开放问题与解决方案

### 6.1 RAG 检索粒度

**问题**：检索整个工单还是工单的 anomalies？

| 方案 | 优点 | 缺点 |
|------|------|------|
| 检索整个工单 | 上下文完整（有 root_cause、solution）| 粒度粗，可能召回不精确 |
| 检索 anomalies | 粒度细，匹配更精确 | 丢失上下文，需要再查工单 |

**建议方案：检索整个工单，但用 anomalies 增强检索质量**

```python
def build_ticket_embedding(ticket: RawTicket) -> List[float]:
    """构建工单的检索向量"""
    # 拼接 description + 所有 anomalies 描述
    text_parts = [ticket.description]
    for anomaly in ticket.anomalies:
        text_parts.append(anomaly.description)

    combined_text = " ".join(text_parts)
    return embedding_service.encode(combined_text)
```

这样既保证检索精度，又保留完整上下文供 LLM 推理。

---

### 6.2 上下文长度管理

**问题**：工单很多时如何截断或摘要？

**建议方案：分层截断**

```
优先级从高到低：
┌─────────────────────────────────────────────────────────────┐
│ 1. 用户问题 + 累积状态（必须保留）                            │
├─────────────────────────────────────────────────────────────┤
│ 2. Top-3 最相关工单（完整保留，含所有 anomalies）             │
├─────────────────────────────────────────────────────────────┤
│ 3. Top-4~10 工单（只保留 description + root_cause）          │
├─────────────────────────────────────────────────────────────┤
│ 4. 其余工单（只列 ticket_id + 一句话描述）                    │
└─────────────────────────────────────────────────────────────┘
```

**实现示例**：

```python
def format_tickets_for_context(
    tickets: List[RawTicket],
    max_tokens: int = 4000,
) -> str:
    """格式化工单，控制上下文长度"""
    parts = []

    # Top 3: 完整内容
    for t in tickets[:3]:
        parts.append(format_ticket_full(t))

    # Top 4-10: 精简内容
    for t in tickets[3:10]:
        parts.append(format_ticket_brief(t))

    # 其余: 仅列表
    if len(tickets) > 10:
        remaining = [t.ticket_id for t in tickets[10:]]
        parts.append(f"其他相关工单: {', '.join(remaining)}")

    return "\n\n".join(parts)
```

**备选方案：增量摘要**

每轮对话后让 LLM 生成"当前诊断状态摘要"，下一轮只用摘要 + 新检索的工单，不累积原始历史。

---

### 6.3 多轮收敛策略

**问题**：如何避免"死循环"（一直问不收敛）？

**建议方案：硬性兜底 + 软性引导 + 无进展检测**

#### 6.3.1 硬性兜底

```python
MAX_TURNS = 5

def check_force_diagnose(state: NaiveSessionState) -> bool:
    """检查是否需要强制诊断"""
    if state.dialogue_turns >= MAX_TURNS:
        return True
    return False
```

#### 6.3.2 软性引导（Prompt 中）

```
当前已进行 {turns} 轮对话。

诊断建议：
- 1-2 轮：可以继续收集信息
- 3-4 轮：应倾向于给出诊断结论
- 5 轮及以上：必须给出结论（即使置信度较低，也要说明不确定性）
```

#### 6.3.3 无进展检测

```python
def detect_no_progress(state: NaiveSessionState) -> bool:
    """检测是否无进展（连续 2 轮用户否定所有推荐）"""
    if len(state.recent_feedbacks) < 2:
        return False

    last_two = state.recent_feedbacks[-2:]
    return all(fb.all_denied for fb in last_two)

# 如果无进展，尝试换方向或给出当前最佳猜测
if detect_no_progress(state):
    # 方案 A: 扩大检索范围，尝试其他方向
    # 方案 B: 降低置信度阈值，给出当前最可能的根因
```

---

### 6.4 与现有方案的切换

**问题**：是否支持运行时切换？

**建议方案：独立实现，通过 CLI 参数切换**

```bash
# 现有 V2 方案（默认）
python -m dbdiag cli

# Naive 方案（实验性）
python -m dbdiag cli --naive
```

**实现方式**：

```python
# cli/main.py
import click

@click.command()
@click.option('--naive', is_flag=True, help='使用简化版 RAG+LLM 诊断')
def chat(naive: bool):
    if naive:
        from dbdiag.core.naive_dialogue_manager import NaiveDialogueManager
        manager = NaiveDialogueManager(db_path, llm_service, embedding_service)
    else:
        from dbdiag.core.dialogue_manager import PhenomenonDialogueManager
        manager = PhenomenonDialogueManager(db_path, llm_service, embedding_service)

    cli = RichCLI(manager)
    cli.run()
```

**优势**：
- 两套代码完全独立，互不影响
- 方便 A/B 对比测试
- 如果 naive 效果好，未来可以替换默认方案

---

## 七、结论

本提案的 naive 方案适合：
- 快速验证 RAG + LLM 端到端诊断的可行性
- 作为现有复杂架构的简化备选方案
- 小规模工单数据场景

建议先实现 prototype，与现有 V2 方案进行 A/B 对比，再决定是否正式采用。
