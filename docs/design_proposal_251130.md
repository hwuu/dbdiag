# 设计提案：检索增强推理方法（实验性探索）

**日期**: 2025-11-30
**状态**: 实验性探索

---

## 一、背景与目标

### 1.1 探索动机

本项目当前使用 **图谱增强推理方法（GAR）** 进行诊断，该方法在可靠性、可解释性等方面表现优秀，但也存在一些局限性（如预处理依赖、灵活性受限等）。

本提案探索另一种思路：**检索增强推理方法（RAR）**，通过 RAG 检索 + LLM 端到端推理，验证能否弥补图谱方法的不足。

> ⚠️ 本提案是实验性探索，**并非要替代图谱方法**，而是发现两种方法的互补点，为未来架构演进积累经验。

### 1.2 术语定义

| 方法 | 全称 | 英文 | 简称 |
|------|------|------|------|
| 现有方法 | 图谱增强推理方法 | Graph-Augmented-Reasoning (GAR) | 图谱方法 |
| 本提案 | 检索增强推理方法 | Retrieval-Augmented-Reasoning (RAR) | 检索方法 |

---

## 二、两种方法概述

### 2.1 图谱方法 (GAR)

**架构**：多模块协作

```
User Input → Retriever → HypothesisTracker → Recommender → ResponseGenerator
                ↓              ↓                  ↓
         Retrieve         Track Hypo          Multi-factor
         Phenomena        Confidence          Scoring
```

**数据依赖**：`phenomena`、`root_causes`、`phenomenon_root_causes` 等预处理表

**核心类**：`GARDialogueManager`

**优势**：
- ✅ **可靠性强**：确定性算法，行为可预测、可复现
- ✅ **可解释性好**：量化置信度、打分依据、工单引用
- ✅ **无幻觉风险**：所有内容来自真实数据
- ✅ **性能高效**：预处理索引，运行时快速
- ✅ **状态一致**：SessionState 严格追踪，不会重复推荐

**局限**：
- ⚠️ **预处理依赖**：需要 rebuild-index，新工单无法实时生效
- ⚠️ **灵活性受限**：只能推荐预定义的 phenomena
- ⚠️ **冷启动问题**：需要足够历史工单构建知识图谱
- ⚠️ **语义理解有限**：向量相似度匹配，对表述多样性理解不如 LLM
- ⚠️ **架构复杂**：多模块协作，学习和维护成本较高

### 2.2 检索方法 (RAR)

**架构**：RAG + LLM 端到端

```
User Input → RAG Retrieval raw_tickets → LLM Reasoning → Output
                                            ↓
                               Recommend Phenomena or Diagnose
```

**数据依赖**：`raw_tickets`（单表，无需预处理）

**核心类**：`RARDialogueManager`（待实现）

**优势**：
- ✅ **架构简单**：核心逻辑约 100-200 行代码
- ✅ **灵活性高**：LLM 自由组合信息，不受预定义限制
- ✅ **无需预处理**：直接使用原始工单数据
- ✅ **冷启动友好**：少量工单即可工作
- ✅ **语义理解强**：LLM 理解用户表述的多样性

**局限**：
- ⚠️ **幻觉风险**：LLM 可能编造不存在的内容
- ⚠️ **可解释性差**：推理过程是黑盒
- ⚠️ **行为不稳定**：相同输入可能得到不同输出
- ⚠️ **收敛不可控**：可能过早/过晚给出结论
- ⚠️ **成本较高**：每轮需要 LLM 调用

---

## 三、对比分析

### 3.1 综合对比

| 维度 | 图谱方法 (GAR) | 检索方法 (RAR) |
|------|---------------|---------------|
| **架构** | 多模块协作 | RAG + LLM |
| **数据依赖** | 预处理多表 | 原始单表 |
| **可靠性** | ✅ 高 | ⚠️ 中 |
| **可解释性** | ✅ 高 | ⚠️ 中 |
| **幻觉风险** | ✅ 无 | ⚠️ 有 |
| **运行性能** | ✅ 快 | ⚠️ 慢 |
| **灵活性** | ⚠️ 低 | ✅ 高 |
| **预处理成本** | ⚠️ 高 | ✅ 低 |
| **冷启动** | ⚠️ 难 | ✅ 易 |
| **语义理解** | ⚠️ 有限 | ✅ 强 |
| **维护成本** | ⚠️ 中 | ✅ 低 |

### 3.2 适用场景

**图谱方法更适合**：
- 生产环境（需要可靠性和可预测行为）
- 高频诊断（性能敏感）
- 合规审计（需要可解释的决策依据）
- 工单量充足且相对稳定的场景

**检索方法更适合**：
- 快速原型验证
- 工单量少或变化频繁的场景
- 探索性诊断（问题边界模糊）
- 对灵活性要求高于可靠性的场景

### 3.3 未来展望：两种方法的结合

| 结合思路 | 说明 |
|---------|------|
| **Hybrid 决策** | 图谱方法追踪状态 + 检索方法辅助判断 |
| **Fallback 机制** | 图谱方法为主，低置信度时切换到检索方法 |
| **LLM 增强图谱** | 保持图谱架构，用 LLM 增强现象匹配和响应生成 |
| **图谱验证检索** | 用图谱方法的规则作为 Guardrails 约束检索方法输出 |

---

## 四、详细设计

### 4.1 数据流

```
┌───────────────────────────────────────────────────────────────────────┐
│                        Per-Turn Dialogue Flow                         │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  User Input                                                           │
│      │                                                                │
│      ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 1. Build Retrieval Query                                        │  │
│  │    - Current user input                                         │  │
│  │    - Accumulated state (confirmed/denied phenomena)             │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│      │                                                                │
│      ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 2. RAG Retrieval raw_tickets                                    │  │
│  │    - Vector similarity search top-K tickets                     │  │
│  │    - Optional: LLM rerank                                       │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│      │                                                                │
│      ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 3. LLM Reasoning & Decision                                     │  │
│  │    Input:                                                       │  │
│  │      - Retrieved raw_tickets (anomalies, root_cause, solution)  │  │
│  │      - Accumulated state (confirmed/denied phenomena)           │  │
│  │      - User problem description                                 │  │
│  │    Output (structured JSON):                                    │  │
│  │      - action: "recommend" | "diagnose"                         │  │
│  │      - confidence: 0-1                                          │  │
│  │      - content: Phenomena list or Diagnosis report              │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│      │                                                                │
│      ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 4. Post-processing & Guardrails                                 │  │
│  │    - Check if recommended phenomena already asked               │  │
│  │    - Verify cited tickets exist                                 │  │
│  │    - Update accumulated state                                   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│      │                                                                │
│      ▼                                                                │
│  Render Output                                                        │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

### 4.2 累积状态结构

每轮对话维护一个结构化的累积状态，避免对话历史过长：

```python
@dataclass
class RARSessionState:
    """检索方法会话状态"""
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
def build_search_query(state: RARSessionState, user_message: str) -> str:
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
    state: RARSessionState,
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
│   ├── rar_dialogue_manager.py    # 新增：检索方法对话管理器
│   └── ...                        # 现有文件不变
├── cli/
│   └── main.py                    # 可选：添加 --rar 开关
└── ...
```

### 5.2 实现步骤

| 步骤 | 内容 | 预计工作量 |
|------|------|-----------|
| 1 | 实现 `RARSessionState` 数据结构 | 小 |
| 2 | 实现 RAG 检索（复用现有 EmbeddingService） | 小 |
| 3 | 设计并调试 LLM Prompt | 中 |
| 4 | 实现 Guardrails | 小 |
| 5 | 集成到 CLI（添加 `--rar` 开关或新命令） | 小 |
| 6 | 测试与对比评估 | 中 |

### 5.3 评估指标

与图谱方法对比：

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
Priority from high to low:
┌─────────────────────────────────────────────────────────────────┐
│ 1. User problem + Accumulated state (MUST keep)                 │
├─────────────────────────────────────────────────────────────────┤
│ 2. Top-3 most relevant tickets (full content, all anomalies)    │
├─────────────────────────────────────────────────────────────────┤
│ 3. Top-4~10 tickets (only description + root_cause)             │
├─────────────────────────────────────────────────────────────────┤
│ 4. Remaining tickets (only ticket_id + one-line description)    │
└─────────────────────────────────────────────────────────────────┘
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

def check_force_diagnose(state: RARSessionState) -> bool:
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
def detect_no_progress(state: RARSessionState) -> bool:
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

### 6.4 与图谱方法的切换

**问题**：是否支持运行时切换？

**建议方案：独立实现，通过 CLI 参数切换**

```bash
# 图谱方法（默认）
python -m dbdiag cli

# 检索方法（实验性）
python -m dbdiag cli --rar
```

**实现方式**：

```python
# cli/main.py
import click

@click.command()
@click.option('--rar', is_flag=True, help='使用检索增强推理方法（实验性）')
def chat(rar: bool):
    if rar:
        from dbdiag.core.rar_dialogue_manager import RARDialogueManager
        manager = RARDialogueManager(db_path, llm_service, embedding_service)
    else:
        from dbdiag.core.dialogue_manager import GARDialogueManager
        manager = GARDialogueManager(db_path, llm_service, embedding_service)

    cli = RichCLI(manager)
    cli.run()
```

**优势**：
- 两套代码完全独立，互不影响
- 方便 A/B 对比测试
- 如果检索方法效果好，未来可以替换默认方案
