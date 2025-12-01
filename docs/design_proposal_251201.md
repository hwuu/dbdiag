# 设计提案：混合增强推理方法（Hyb）

**日期**: 2025-12-01
**状态**: 已实现

---

## 一、背景与目标

### 1.1 问题回顾

前期我们实现了两种诊断方法：

| 方法 | 优势 | 局限 |
|------|------|------|
| **GAR（图谱增强推理）** | 可靠、可解释、无幻觉 | 预处理依赖、语义理解有限 |
| **RAR（检索增强推理）** | 灵活、语义理解强 | 幻觉风险、行为不稳定 |

**核心问题**：能否取两者之长，构建一种兼具**可靠性**和**灵活性**的混合方法？

### 1.2 设计目标

**Hyb（混合增强推理）** 的设计目标：

1. **保持 GAR 的可靠性**：确定性算法、量化置信度、无幻觉
2. **增强语义理解能力**：利用工单描述的语义检索补充候选现象
3. **支持自然语言交互**：LLM 提取用户自然语言反馈中的结构化信息
4. **动态发现新线索**：中间轮次基于用户新观察扩展候选池

### 1.3 术语定义

| 方法 | 全称 | 英文 | 简称 |
|------|------|------|------|
| 图谱方法 | 图谱增强推理 | Graph-Augmented-Reasoning | GAR |
| 检索方法 | 检索增强推理 | Retrieval-Augmented-Reasoning | RAR |
| 混合方法 | 混合增强推理 | Hybrid-Augmented-Reasoning | Hyb |

---

## 二、三种方法概述

### 2.1 图谱方法 (GAR)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              GAR 流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────────┐   │
│  │  用户输入  │ →  │ Retriever │ →  │ Hypothesis│ →  │  Recommender  │   │
│  └───────────┘    │ 检索现象   │    │  Tracker  │    │  推荐/诊断    │   │
│                   └───────────┘    └───────────┘    └───────────────┘   │
│                         ↓                ↓                              │
│                   现象向量检索      确定性置信度计算                       │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  反馈处理：关键词匹配（"1确认 2否定"、"确认"、"否定"）              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**核心特点**：
- 基于预处理的 `phenomena`、`root_causes`、`phenomenon_root_causes` 表
- 确定性算法计算置信度
- 用户反馈通过关键词匹配解析

### 2.2 检索方法 (RAR)

```
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
                               RAR 流程
├ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
│                                                                          │
   ┌ ─ ─ ─ ─ ─ ┐    ┌ ─ ─ ─ ─ ─ ─ ─ ─ ┐    ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
│  │  用户输入  │ →     RAG 检索        │ →     LLM 端到端推理         │    │
   └ ─ ─ ─ ─ ─ ┘    │ rar_raw_tickets │    │  推荐现象 / 诊断结论  │
│                   └ ─ ─ ─ ─ ─ ─ ─ ─ ┘    └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘    │
                          ↓                          ↓
│                  工单描述向量检索            LLM 自主判断置信度            │
                                                     ↓
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐    │
      反馈处理：LLM 自由理解（无结构化约束）
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘    │

└ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
```

**核心特点**：
- 直接使用 `raw_tickets` 原始数据
- LLM 端到端推理，自由组合信息
- 高度灵活但行为不可预测

### 2.3 混合方法 (Hyb) = GAR 架构 + RAR 能力

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Hyb 流程 = GAR 架构 + RAR 能力                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ╔═══════════════════════════════════════════════════════════════════════╗  │
│  ║ 【借鉴 RAR】初始轮语义检索                                              ║  │
│  ║  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐   ║  │
│  ║     用户问题 → 检索 rar_raw_tickets → 提取关联现象 → 补充候选池       ║  │
│  ║  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘   ║  │
│  ╚═══════════════════════════════════════════════════════════════════════╝  │
│                                       ↓                                      │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 【继承 GAR】核心推理流程                                                │  │
│  │                                                                        │  │
│  │  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    │  │
│  │  │  用户输入  │ →  │ Retriever │ →  │ Hypothesis│ →  │Recommender│    │  │
│  │  └───────────┘    │ 检索现象   │    │  Tracker  │    │ 推荐/诊断 │    │  │
│  │                   └───────────┘    └───────────┘    └───────────┘    │  │
│  │                         ↓                ↓                            │  │
│  │                   现象向量检索      确定性置信度计算                     │  │
│  │                                                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                       ↓                                      │
│  ╔═══════════════════════════════════════════════════════════════════════╗  │
│  ║ 【借鉴 RAR】反馈理解增强                                                ║  │
│  ║                                                                        ║  │
│  ║  简单格式 ─────→ 快速路径（关键词匹配，继承 GAR）                        ║  │
│  ║  ("1确认 2否定")                                                       ║  │
│  ║                   ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐    ║  │
│  ║  自然语言 ─────→    LLM 结构化提取（借鉴 RAR 的语义理解能力）        ║  │
│  ║  ("IO正常,           ↓                                           │    ║  │
│  ║   索引涨了")      { feedback: {...}, new_observations: [...] }        ║  │
│  ║                                            ↓                     │    ║  │
│  ║                   若有 new_observations → 触发语义检索 → 补充候选      ║  │
│  ║                   └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘    ║  │
│  ╚═══════════════════════════════════════════════════════════════════════╝  │
│                                                                              │
│  图例：┌───┐ 继承自 GAR     ╔═══╗ Hyb 增强层                                 │
│       └───┘ (确定性算法)   ╚═══╝                                            │
│       ┌ ─ ┐ 借鉴自 RAR                                                      │
│       └ ─ ┘ (语义检索/LLM)                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**核心特点**：
- **继承 GAR**：多模块协作架构、确定性置信度计算（实线框 `┌───┐`）
- **借鉴 RAR**：工单描述语义检索、LLM 语义理解能力（虚线框 `┌ ─ ┐`）
- **Hyb 创新**：增强层整合两者，保持可靠性的同时提升灵活性（双线框 `╔═══╗`）

---

## 三、对比分析

### 3.1 综合对比

| 维度 | GAR | RAR | Hyb |
|------|-----|-----|-----|
| **架构** | 多模块协作 | RAG + LLM | GAR + 语义检索 + LLM 辅助 |
| **数据依赖** | 预处理多表 | 原始单表 | 预处理多表 + 原始工单 |
| **置信度计算** | 确定性公式 | LLM 自主判断 | 确定性公式 |
| **反馈理解** | 关键词匹配 | LLM 自主判断 | 简单格式快速路径 + LLM 结构化提取 |
| **可靠性** | ✅ 高 | ⚠️ 中 | ✅ 高 |
| **可解释性** | ✅ 高 | ⚠️ 中 | ✅ 高 |
| **幻觉风险** | ✅ 无 | ⚠️ 有 | ✅ 无（LLM 仅提取，不生成内容） |
| **灵活性** | ⚠️ 低 | ✅ 高 | ✅ 中高 |
| **语义理解** | ⚠️ 有限 | ✅ 强 | ✅ 强 |
| **初始推荐覆盖率** | ⚠️ 中 | ✅ 高 | ✅ 高 |
| **中间轮动态发现** | ❌ 否 | ✅ 是 | ✅ 是 |
| **预处理成本** | ⚠️ 高 | ✅ 低 | ⚠️ 高 |
| **运行时 LLM 调用** | 少（仅诊断总结） | 多（每轮） | 中（非简单反馈时） |

### 3.2 关键差异详解

#### 3.2.1 反馈理解机制对比

| 场景 | GAR | RAR | Hyb |
|------|-----|-----|-----|
| `"1确认 2否定"` | ✅ 关键词匹配 | LLM 判断 | ✅ 快速路径（无 LLM） |
| `"确认"` | ✅ 关键词匹配 | LLM 判断 | ✅ 快速路径（无 LLM） |
| `"IO 正常，索引涨了"` | ⚠️ 简单 LLM 是/否判断 | LLM 自由理解 | ✅ LLM 结构化提取 |
| `"另外发现慢查询"` | ❌ 忽略 | LLM 可能注意到 | ✅ 提取为 new_observation |

#### 3.2.2 候选现象来源对比

| 来源 | GAR | RAR | Hyb |
|------|-----|-----|-----|
| 现象向量检索 | ✅ | ❌ | ✅ |
| 工单描述语义检索 | ❌ | ✅ | ✅（初始轮） |
| 用户新观察触发检索 | ❌ | ✅ | ✅（中间轮） |

#### 3.2.3 LLM 使用方式对比

| 方法 | LLM 角色 | 风险控制 |
|------|----------|----------|
| **GAR** | 仅用于诊断总结生成 | 输出基于已确认的事实 |
| **RAR** | 核心推理引擎 | 需要复杂 Guardrails |
| **Hyb** | 信息提取工具 | 只提取结构化信息，不生成推理内容 |

**Hyb 的 LLM 使用原则**：
> LLM 是"理解用户说了什么"的工具，而非"决定下一步做什么"的工具。

### 3.3 适用场景

| 场景 | 推荐方法 | 原因 |
|------|----------|------|
| 生产环境、高可靠性要求 | GAR | 确定性行为，可审计 |
| 快速原型、少量工单 | RAR | 无需预处理，灵活 |
| 用户习惯自然语言描述 | **Hyb** | LLM 理解自然语言 |
| 问题描述模糊，需要动态探索 | **Hyb** | 动态发现新线索 |
| 需要可解释性但又想提升覆盖率 | **Hyb** | 兼顾两者 |

---

## 四、Hyb 详细设计

### 4.1 整体流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Hyb 混合增强推理流程                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        初始轮（start_conversation）                  │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                      │    │
│  │  用户问题: "查询变慢，原来几秒现在要半分钟"                            │    │
│  │      │                                                               │    │
│  │      ▼                                                               │    │
│  │  [1] 语义检索相似工单                                                 │    │
│  │      │   - search_by_ticket_description(user_problem)                │    │
│  │      │   - 返回 Top-5 相似工单                                       │    │
│  │      │                                                               │    │
│  │      ▼                                                               │    │
│  │  [2] 提取候选现象                                                     │    │
│  │      │   - get_phenomena_by_ticket_ids()                             │    │
│  │      │   - 存入 session.hybrid_candidate_phenomenon_ids              │    │
│  │      │                                                               │    │
│  │      ▼                                                               │    │
│  │  [3] GAR 标准流程                                                     │    │
│  │      └─> HypothesisTracker → Recommender → 输出推荐                  │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                     │                                        │
│                                     ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                       中间轮（continue_conversation）                 │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                      │    │
│  │  用户反馈: "IO 正常，索引涨了 6 倍，另外发现很多慢查询"                │    │
│  │      │                                                               │    │
│  │      ▼                                                               │    │
│  │  [1] 判断反馈格式                                                     │    │
│  │      │   - 简单格式 ("1确认 2否定") → 快速路径                        │    │
│  │      │   - 自然语言 → LLM 结构化提取                                 │    │
│  │      │                                                               │    │
│  │      ▼                                                               │    │
│  │  [2] LLM 结构化提取（非简单格式时）                                   │    │
│  │      │   输出: {                                                      │    │
│  │      │     "feedback": {"P-0001": "denied", "P-0002": "confirmed"},  │    │
│  │      │     "new_observations": ["发现很多慢查询"]                     │    │
│  │      │   }                                                           │    │
│  │      │                                                               │    │
│  │      ▼                                                               │    │
│  │  [3] 处理确认/否定                                                    │    │
│  │      │   - 更新 session.confirmed_phenomena                          │    │
│  │      │   - 更新 session.denied_phenomena                             │    │
│  │      │                                                               │    │
│  │      ▼                                                               │    │
│  │  [4] 动态检索（若有 new_observations）                                │    │
│  │      │   - query = new_observations.join(" ")                        │    │
│  │      │   - search_by_ticket_description(query)                       │    │
│  │      │   - 合并候选现象到 hybrid_candidate_phenomenon_ids            │    │
│  │      │                                                               │    │
│  │      ▼                                                               │    │
│  │  [5] GAR 标准流程                                                     │    │
│  │      └─> HypothesisTracker → Recommender → 输出                      │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 会话状态扩展

```python
class SessionState(BaseModel):
    """GAR/Hyb 会话状态"""

    # 标准 GAR 字段
    session_id: str
    user_problem: str
    confirmed_phenomena: List[ConfirmedPhenomenon]
    denied_phenomena: List[DeniedPhenomenon]
    recommended_phenomena: List[RecommendedPhenomenon]
    active_hypotheses: List[Hypothesis]
    dialogue_history: List[DialogueMessage]

    # Hyb 扩展字段
    hybrid_candidate_phenomenon_ids: List[str] = []  # 语义检索补充的候选现象
    new_observations: List[str] = []                  # 用户描述的新观察
```

### 4.3 LLM 反馈提取 Prompt

#### 4.3.1 System Prompt

```
你是一个对话分析助手。分析用户消息，判断用户对每个待确认现象的反馈。

输出 JSON 格式：
{
  "feedback": {
    "<phenomenon_id>": "confirmed" | "denied" | "unknown"
  },
  "new_observations": ["用户提到的新观察1", "用户提到的新观察2"]
}

判断规则：
- confirmed: 用户明确确认看到了该现象，或描述符合该现象
- denied: 用户明确否认，或描述与该现象相反（如"正常"对应"异常"）
- unknown: 用户未提及该现象

new_observations: 用户描述的、不在待确认列表中的新观察或现象。
只提取具体的技术观察，忽略闲聊。

只输出 JSON，不要其他内容。
```

#### 4.3.2 User Prompt 模板

```
待确认现象：
1. [P-0001] wait_io 事件占比异常高
2. [P-0002] 索引大小异常增长
3. [P-0003] CPU 使用率高

用户消息: {user_message}
```

#### 4.3.3 输出示例

```json
{
  "feedback": {
    "P-0001": "denied",
    "P-0002": "confirmed",
    "P-0003": "unknown"
  },
  "new_observations": ["发现很多慢查询", "连接数较高"]
}
```

### 4.4 快速路径优化

为避免不必要的 LLM 调用，简单格式走快速路径：

```python
def _mark_confirmed_phenomena_from_feedback(user_message, session):
    # 快速路径 1：批量格式 "1确认 2否定 3确认"
    batch_pattern = r'(\d+)\s*(确认|否定|是|否)'
    if re.findall(batch_pattern, user_message):
        return process_batch_format(user_message, session)

    # 快速路径 2：简单确认 "确认" / "是"
    if any(kw in user_message for kw in ["确认", "是", "是的"]):
        return confirm_all_pending(session)

    # 快速路径 3：简单否定 "全否定" / "都不是"
    if any(kw in user_message for kw in ["全否定", "都不是"]):
        return deny_all_pending(session)

    # 非简单格式：调用 LLM 结构化提取
    return extract_feedback_with_llm(user_message, session)
```

### 4.5 动态检索策略

```python
def continue_conversation(session_id, user_message):
    session = load_session(session_id)

    # 1. 解析用户反馈
    new_observations = mark_confirmed_phenomena_from_feedback(user_message, session)

    # 2. 动态检索（仅 Hyb 模式且有新观察时）
    if new_observations and self.hybrid_mode:
        query = " ".join(new_observations)
        ticket_matches = retriever.search_by_ticket_description(query, top_k=3)

        if ticket_matches:
            ticket_ids = [m.ticket_id for m in ticket_matches]
            candidate_phenomena = retriever.get_phenomena_by_ticket_ids(ticket_ids)

            # 合并到候选池（去重）
            existing = set(session.hybrid_candidate_phenomenon_ids)
            for p in candidate_phenomena:
                if p.phenomenon_id not in existing:
                    session.hybrid_candidate_phenomenon_ids.append(p.phenomenon_id)

        # 记录新观察
        session.new_observations.extend(new_observations)

    # 3. GAR 标准流程
    session = hypothesis_tracker.update_hypotheses(session)
    recommendation = recommender.recommend_next_action(session)
    return generate_response(session, recommendation)
```

### 4.6 候选现象增强机制

HypothesisTracker 在检索根因候选时，会考虑 `hybrid_candidate_phenomenon_ids`：

```python
def _retrieve_root_cause_candidates(session):
    # 从 session 读取混合模式候选现象
    boost_phenomenon_ids = set(session.hybrid_candidate_phenomenon_ids)

    # 正常的现象向量检索
    retrieved_phenomena = retriever.retrieve(query=session.user_problem, top_k=20)

    # 构建根因候选映射
    root_cause_map = defaultdict(lambda: {"phenomena": [], "ticket_ids": set()})

    for phenomenon, score in retrieved_phenomena:
        # ... 处理检索到的现象

    # 混合模式：补充候选现象（可能检索没召回）
    if boost_phenomenon_ids:
        for pid in boost_phenomenon_ids:
            phenomenon = phenomenon_dao.get_by_id(pid)
            if phenomenon:
                # 找到关联的根因和工单
                ticket_rows = ticket_dao.get_by_phenomenon_id(pid)
                for row in ticket_rows:
                    root_cause_id = row["root_cause_id"]
                    # 添加到根因候选（去重）
                    if pid not in existing_pids:
                        root_cause_map[root_cause_id]["phenomena"].append(phenomenon)
                    root_cause_map[root_cause_id]["ticket_ids"].add(row["ticket_id"])

    return root_cause_map
```

---

## 五、实现总结

### 5.1 文件变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `models/gar.py` | 修改 | 添加 `new_observations` 字段 |
| `core/gar/dialogue_manager.py` | 修改 | 添加 `hybrid_mode` 参数、LLM 提取、动态检索 |
| `core/gar/hypothesis_tracker.py` | 修改 | 读取 `hybrid_candidate_phenomenon_ids` |
| `core/gar/retriever.py` | 修改 | 添加 `search_by_ticket_description`、`get_phenomena_by_ticket_ids` |
| `cli/main.py` | 修改 | 添加 `HybCLI` 类、`--hyb` 开关 |
| `tests/unit/test_dialogue_manager_feedback.py` | 新增 | 9 个测试用例 |

### 5.2 CLI 使用

```bash
# GAR 模式（默认）
python -m dbdiag cli

# RAR 模式（实验性）
python -m dbdiag cli --rar

# Hyb 模式（实验性）
python -m dbdiag cli --hyb
```

### 5.3 Progress 输出

```
• 第 N 轮
  → 识别用户反馈...
  → 分析用户反馈...        # LLM 提取时
  → 检索相关案例...        # 有新观察时
  → 找到 N 个相关案例
  → 补充 N 个候选现象
  → 更新假设置信度...
  → 生成推荐...
```

---

## 六、局限与未来方向

### 6.1 当前局限

| 局限 | 说明 | 影响 |
|------|------|------|
| LLM 提取可能不准确 | 自然语言理解非 100% 准确 | 可能误判确认/否定 |
| 仍需预处理 | 依赖 `phenomena`、`root_causes` 等表 | 新工单需 rebuild-index |
| LLM 调用增加 | 非简单格式时调用 LLM | 延迟和成本增加 |

### 6.2 未来改进方向

| 方向 | 说明 |
|------|------|
| **LLM 提取结果校验** | 对 LLM 提取的 new_observations 做相关性校验 |
| **自适应检索策略** | 根据置信度变化动态调整检索范围 |
| **多轮上下文理解** | LLM 考虑完整对话历史，而非单轮反馈 |
| **与 RAR 的动态切换** | 低置信度时切换到 RAR 进行探索性诊断 |

---

## 附录：对话示例

### A.1 初始轮语义检索增强

```
用户: 查询变慢，原来几秒现在要半分钟

• 第 1 轮
  → 检索相似工单...
  → 找到 5 个相似工单
  → 提取 8 个候选现象
  → 检索根因候选...
  → 生成推荐...

  建议确认以下 3 个现象：
  [1] P-0001 wait_io 事件占比异常高
      推荐原因: 与假设"索引膨胀导致 IO 瓶颈"相关
  ...
```

### A.2 中间轮 LLM 反馈理解 + 动态检索

```
用户: IO 正常，索引涨了 6 倍，另外发现很多慢查询

• 第 2 轮
  → 识别用户反馈...
  → 分析用户反馈...
  → 检索相关案例...
  → 找到 3 个相关案例
  → 补充 4 个候选现象
  → 更新假设置信度...
  → 生成推荐...

  建议确认以下 2 个现象：
  [1] P-0015 慢查询数量异常增多
      推荐原因: 基于用户新观察"发现很多慢查询"检索补充
  ...
```
