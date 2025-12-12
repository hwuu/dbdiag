# Agent 诊断系统设计方案

> 日期：2024-12-09
> 状态：设计讨论中

## 目录

- [一、背景与目标](#一背景与目标)
- [二、架构设计](#二架构设计)
- [三、Planner 设计](#三planner-设计)
- [四、Executor 设计](#四executor-设计)
- [五、Responder 设计](#五responder-设计)
- [六、GraphEngine 设计](#六graphengine-设计)
- [七、核心工具设计：match_phenomena](#七核心工具设计match_phenomena)
- [八、核心工具设计：diagnose](#八核心工具设计diagnose)
- [九、会话管理](#九会话管理)
- [十、与现有系统集成](#十与现有系统集成)
- [十一、测试策略](#十一测试策略)
- [十二、实施计划](#十二实施计划)
- [附录](#附录)

---

## 一、背景与目标

### 1.1 现状问题

当前诊断系统存在以下体验问题：

1. **对话死板**：系统按固定流程执行（检索→推荐→反馈→推荐），缺乏"像真人对话"的灵活性
2. **意图理解有限**：只支持 feedback/query/mixed 三种意图，无法处理更复杂的用户需求
3. **响应风格单一**：无论用户怎么问，输出格式都是固定的结构化数据

### 1.2 设计目标

引入 Agent 模式，实现：

1. **灵活的意图理解**：LLM 理解用户意图，动态决定执行什么动作
2. **自然的对话体验**：响应更像真人，能主动追问、总结、澄清
3. **可解释的诊断过程**：核心算法仍是确定性的，保证可解释性
4. **高度解耦的架构**：核心算法可独立测试和复用

### 1.3 核心设计理念

**Agent 壳 + 确定性核**：让 LLM 当"前台接待"决定做什么，但诊断推理仍用确定性算法当"后台专家"。

**关键分层**：
- **理解层**：LLM 理解用户意图、匹配现象、处理指代
- **推理层**：确定性算法（贝叶斯推理）计算置信度、推荐现象
- **表达层**：LLM 生成自然语言响应

**Agent Loop**：Agent 遵循以下循环工作：

```
   ┌─────────────────────────────────────────────────────┐
   │                                                     │
   ▼                                                     │
Receive ──▶ Planner ──Yes──▶ Execute Tool ───────────────┘
 Input         │                  (back to Planner)
               │ No
               ▼
         Responder ──▶ Wait for next input ──▶ (back to Receive)
```

1. **Receive user input**：接收用户输入
2. **Planner**：决定是否需要调用工具
   - Yes → 执行工具，结果返回 Planner 继续决策
   - No → 生成响应，等待下一轮用户输入

**工具列表**（Agent 可调用）：

| Tool | Type | Description |
|------|------|-------------|
| match_phenomena | LLM+Embed | Raw observation -> Matched phenomena or Clarification |
| diagnose | Deterministic | Matched phenomena -> Hypotheses + Recommendations |
| query_progress | Deterministic | Session state -> Progress summary |
| query_hypotheses | Deterministic | Session state -> Hypothesis details |
| query_relations | Deterministic | Entity ID -> Related entities |

---

## 二、架构设计

### 2.1 整体架构

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        AgentDialogueManager                               │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                         Agent Loop                                  │  │
│  │                                                                     │  │
│  │  ┌───────────────────────────────────────────────────────────────┐  │  │
│  │  │ 1. Receive user input                                         │◀─┼──┼──┐
│  │  └─────────────────────────────┬─────────────────────────────────┘  │  │  │
│  │                                │                                    │  │  │
│  │                                ▼                                    │  │  │
│  │  ┌───────────────────────────────────────────────────────────────┐  │  │  │
│  │  │ 2. Planner: need tool call?                                   │◀─┼──┼──┼──┐
│  │  │    - Yes: which tool? what params?                            │  │  │  │  │
│  │  │    - No: ready to respond / need user clarification           │  │  │  │  │
│  │  └─────────────────────────────┬─────────────────────────────────┘  │  │  │  │
│  │                                │                                    │  │  │  │
│  │                  ┌─────────────┴─────────────┐                      │  │  │  │
│  │                  │                           │                      │  │  │  │
│  │                 No                          Yes                     │  │  │  │
│  │           (respond/clarify)                  │                      │  │  │  │
│  │                  │                           │                      │  │  │  │
│  │                  ▼                           ▼                      │  │  │  │
│  │  ┌───────────────────────────┐  ┌───────────────────────────┐       │  │  │  │
│  │  │ 3. Responder              │  │ 4. Executor               │       │  │  │  │
│  │  │    Generate response      │  │    Execute tool from      │───────┼──┼──┼──┘
│  │  │    to user                │  │    ToolSet                │       │  │  │
│  │  └─────────────┬─────────────┘  └───────────────────────────┘       │  │  │
│  │                │                        (back to 2)                 │  │  │
│  │                │                                                    │  │  │
│  │                └────────────────────────────────────────────────────┼──┼──┘
│  │                               (back to 1)                           │  │
│  │                                                                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                            ToolSet                                  │  │
│  │                                                                     │  │
│  │  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐        │  │
│  │  │ match_phenomena │ │    diagnose     │ │ query_progress  │  ...   │  │
│  │  │ (Embed + LLM)   │ │ (Deterministic) │ │ (Deterministic) │        │  │
│  │  └─────────────────┘ └─────────────────┘ └─────────────────┘        │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                         GraphEngine                                 │  │
│  │                                                                     │  │
│  │  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐     │  │
│  │  │  GraphBuilder    │ │  GraphQuery      │ │ ConfidenceCalc   │     │  │
│  │  │                  │ │                  │ │ (Bayesian)       │     │  │
│  │  └──────────────────┘ └──────────────────┘ └──────────────────┘     │  │
│  │                                                                     │  │
│  │  Note: All methods are PURE deterministic, no LLM                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                              DAO Layer                                    │
│        PhenomenonDAO | RootCauseDAO | TicketDAO | ...                     │
└───────────────────────────────────────────────────────────────────────────┘
```

**Agent Loop 流程示例**

场景：用户说 "1确认，另外 IO 很高"

```
User Input: "1确认，另外 IO 很高"
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Loop 1: Planner                                                         │
│                                                                         │
│ Input:  user_message + session (pending: [P-0001, P-0002, P-0003])      │
│ Output: {                                                               │
│   decision: "call",                                                     │
│   tool: "match_phenomena",                                              │
│   params: {                                                             │
│     confirmations: ["P-0001"],                                          │
│     raw_observations: ["IO很高"]                                        │
│   }                                                                     │
│ }                                                                       │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Tool Execution: match_phenomena                                         │
│                                                                         │
│ Result: {                                                               │
│   all_matched: true,                                                    │
│   interpreted: [                                                        │
│     {raw: "IO很高", matched: {P-0012, score: 0.85}}                     │
│   ]                                                                     │
│ }                                                                       │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Loop 2: Planner (with tool result)                                      │
│                                                                         │
│ Input:  previous context + match_phenomena result (all_matched: true)   │
│ Output: {                                                               │
│   decision: "call",                                                     │
│   tool: "diagnose",                                                     │
│   params: {                                                             │
│     confirmed_phenomena: [                                              │
│       {P-0001, score: 1.0},   // direct confirm                         │
│       {P-0012, score: 0.85}   // matched from "IO很高"                  │
│     ]                                                                   │
│   }                                                                     │
│ }                                                                       │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Tool Execution: diagnose                                                │
│                                                                         │
│ Result: {                                                               │
│   hypotheses: [{RC-0001, confidence: 0.72}, ...],                       │
│   recommendations: [{P-0015, info_gain: 0.3}, ...]                      │
│ }                                                                       │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Loop 3: Planner (with diagnose result)                                  │
│                                                                         │
│ Input:  previous context + diagnose result                              │
│ Output: {                                                               │
│   decision: "respond",                                                  │
│   response_context: {hypotheses, recommendations}                       │
│ }                                                                       │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Responder                                                               │
│                                                                         │
│ Output: "好的，已记录你的反馈。目前最可能是索引膨胀（72%）...           │
│          建议接下来确认：1. xxx  2. xxx"                                │
└─────────────────────────────────────────────────────────────────────────┘
```

**澄清场景示例**

场景：用户说 "数据库有点慢"

```
User Input: "数据库有点慢"
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Loop 1: Planner                                                         │
│ Output: { decision: "call", tool: "match_phenomena", ... }              │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Tool Execution: match_phenomena                                         │
│                                                                         │
│ Result: {                                                               │
│   all_matched: false,                                                   │
│   interpreted: [{                                                       │
│     raw: "数据库有点慢",                                                │
│     needs_clarification: true,                                          │
│     clarification_question: "你说的'慢'是指哪种情况？",                 │
│     options: [P-0031, P-0032, P-0033]                                   │
│   }]                                                                    │
│ }                                                                       │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Loop 2: Planner (with match_phenomena result: needs_clarification)      │
│                                                                         │
│ Output: {                                                               │
│   decision: "respond",           // 需要用户澄清，不继续调工具          │
│   response_context: {clarification_needed: true, ...}                   │
│ }                                                                       │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Responder                                                               │
│                                                                         │
│ Output: "你说的'慢'具体是指哪种情况？                                   │
│          1. 查询响应时间长  2. 连接建立慢  3. 写入延迟高"               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        等待用户下一轮输入 (Back to 1)
```

### 2.2 模块职责

| 模块 | 职责 | 是否使用 LLM |
|------|------|-------------|
| **Planner** | 在 Agent Loop 中决策：调哪个工具 / 直接回复 / 需要澄清 | 是 |
| **Executor** | 执行单个工具调用，返回结果 | 否 |
| **match_phenomena** | 将原始观察描述匹配到标准 phenomena，处理指代消解 | 是（Embedding 召回 + LLM 精排） |
| **diagnose** | 核心诊断算法，纯确定性贝叶斯推理 | **否** |
| **query_progress / query_hypotheses / ...** | 查询类工具，纯确定性 | **否** |
| **Responder** | 将结构化结果转换为自然语言响应 | 是 |

### 2.3 目录结构

```
dbdiag/core/
├── agent/                          # Agent 诊断系统 (新增)
│   ├── __init__.py
│   ├── planner.py                  # Planner 决策层
│   ├── executor.py                 # Executor 工具执行器
│   ├── responder.py                # Responder 响应生成层
│   ├── dialogue_manager.py         # Agent 对话管理器 (Agent Loop)
│   ├── models.py                   # 数据模型 (AgentDecision 等)
│   ├── graph_engine.py             # GraphEngine 确定性诊断核心
│   │
│   └── tools/                      # 工具目录
│       ├── __init__.py
│       ├── match_phenomena.py      # 现象匹配工具 (LLM + Embedding)
│       ├── diagnose.py             # 诊断工具 (确定性)
│       ├── query_progress.py       # 进展查询工具 (确定性)
│       ├── query_hypotheses.py     # 假设查询工具 (确定性)
│       └── query_relations.py      # 关系查询工具 (确定性)
│
├── gar2/                           # GAR2 (保留，不修改)
│   └── ...
│
└── ...
```

---

## 三、Planner 设计

### 3.1 职责

Planner 是 Agent Loop 的核心决策者，**每次循环**负责：
1. 理解当前上下文（用户输入 + 工具执行结果）
2. 决定下一步：调用工具 / 直接回复用户 / 请求用户澄清
3. 如果调用工具，指定工具名和参数

**关键设计**：每次只决定一个 action，不支持一次返回多个 action。

### 3.2 Prompt 设计

#### System Prompt

````
你是一个数据库诊断助手的决策模块，运行在 Agent Loop 中。

每次循环，你需要根据当前上下文决定下一步行动：
1. 调用工具（call）
2. 直接回复用户（respond）

## 可用工具

### match_phenomena
将用户的原始观察描述匹配到标准现象库。

使用场景：
- 用户描述了新的观察（如"IO 很高"、"慢查询很多"）
- 需要将模糊描述转换为标准 phenomenon

输入参数：
- raw_observations: 原始观察描述列表
- confirmations: 直接确认的现象 ID 列表（如用户说"1确认"）
- denials: 否认的现象 ID 列表

输出：
- 匹配成功：返回 matched phenomena 列表（含匹配度）
- 匹配失败：返回 needs_clarification + 澄清问题

### diagnose
执行核心诊断算法（贝叶斯推理）。

使用场景：
- match_phenomena 返回了 matched phenomena
- 需要更新假设置信度和获取推荐现象

输入参数：
- confirmed_phenomena: 已匹配的现象列表（含匹配度）
- denied_phenomena: 否认的现象 ID 列表

输出：
- hypotheses: 假设列表（按置信度排序）
- recommendations: 推荐确认的现象列表

### query_progress
查询当前诊断进展。

使用场景：用户询问"现在怎么样了"、"进展如何"

### query_hypotheses
查询假设详情。

使用场景：用户想了解"还有什么可能"、"其他原因"

### query_relations
查询现象和根因的关联关系。

使用场景：用户想了解某个现象/根因的关联

## 决策规则

1. **用户有新观察描述** → 先调 match_phenomena
2. **match_phenomena 返回 all_matched: true** → 调 diagnose
3. **match_phenomena 返回 needs_clarification** → 直接回复（请求澄清）
4. **diagnose 返回结果** → 直接回复（展示结果）
5. **用户纯查询（无新观察）** → 调对应查询工具
6. **工具返回结果后** → 再次决策是否需要调其他工具

## 输出格式

必须输出 JSON，格式如下：

### 调用工具
```json
{
  "decision": "call",
  "tool": "工具名",
  "params": { ... },
  "reasoning": "决策理由"
}
```

### 直接回复
```json
{
  "decision": "respond",
  "response_context": {
    "type": "diagnosis_result" | "clarification_needed" | "progress_summary" | ...,
    "data": { ... }
  },
  "reasoning": "决策理由"
}
```
````

#### User Prompt Template

```
## 会话状态

- 会话轮次: {rounds}
- 已确认现象: {confirmed_count} 个
- 已否认现象: {denied_count} 个
- 当前假设数: {hypotheses_count} 个
- 最可能根因: {top_hypothesis}
- 最高置信度: {top_confidence:.0%}

## 当前待确认的现象

{pending_recommendations_text}

## 最近对话历史

{dialogue_history}

## 当前循环上下文

{loop_context}
// 首次循环: 用户输入
// 后续循环: 上一个工具的执行结果

请决定下一步行动，输出 JSON。
```

### 3.3 决策示例

#### 示例 1：用户提供反馈，需要先匹配

```
当前循环上下文: 用户输入 "1确认，另外 IO 很高"
待确认现象: [1] P-0001 wait_io高, [2] P-0002 索引增长

输出:
{
  "decision": "call",
  "tool": "match_phenomena",
  "params": {
    "confirmations": ["P-0001"],
    "raw_observations": ["IO很高"]
  },
  "reasoning": "用户确认了P-0001，并描述了新观察'IO很高'，需要先匹配到标准现象"
}
```

#### 示例 2：match_phenomena 匹配成功，继续调 diagnose

```
当前循环上下文: match_phenomena 返回
{
  "all_matched": true,
  "interpreted": [{"raw": "IO很高", "matched": {"phenomenon_id": "P-0012", "score": 0.85}}]
}

输出:
{
  "decision": "call",
  "tool": "diagnose",
  "params": {
    "confirmed_phenomena": [
      {"phenomenon_id": "P-0001", "score": 1.0},
      {"phenomenon_id": "P-0012", "score": 0.85}
    ]
  },
  "reasoning": "match_phenomena 匹配成功，调用 diagnose 更新假设置信度"
}
```

#### 示例 3：match_phenomena 需要澄清，直接回复

```
当前循环上下文: match_phenomena 返回
{
  "all_matched": false,
  "interpreted": [{
    "raw": "数据库有点慢",
    "needs_clarification": true,
    "clarification_question": "你说的'慢'是指哪种情况？",
    "options": [...]
  }]
}

输出:
{
  "decision": "respond",
  "response_context": {
    "type": "clarification_needed",
    "data": {
      "question": "你说的'慢'是指哪种情况？",
      "options": [...]
    }
  },
  "reasoning": "用户描述太模糊，需要澄清后才能继续"
}
```

#### 示例 4：diagnose 返回结果，直接回复

```
当前循环上下文: diagnose 返回
{
  "hypotheses": [{"root_cause_id": "RC-0001", "confidence": 0.72}, ...],
  "recommendations": [...]
}

输出:
{
  "decision": "respond",
  "response_context": {
    "type": "diagnosis_result",
    "data": {
      "hypotheses": [...],
      "recommendations": [...]
    }
  },
  "reasoning": "诊断完成，展示结果给用户"
}
```

---

## 四、Executor 设计

### 4.1 职责

Executor 是 Agent Loop 中的工具执行组件，负责：
1. 接收 Planner 的工具调用决策
2. 根据工具名查找并执行对应的工具
3. 将结果反馈给 Agent Loop 进行下一轮决策

**注意**：Executor 只执行单个工具，不负责协调多个工具的调用顺序——这由 Planner 在 Agent Loop 中决策。

### 4.2 Tool 抽象基类

所有工具都继承自统一的抽象基类，遵循相同的输入输出接口：

```python
"""
dbdiag/core/agent/tools/base.py
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic
from pydantic import BaseModel

from dbdiag.core.agent.models import SessionState


# 泛型类型：工具输入和输出
TInput = TypeVar("TInput", bound=BaseModel)
TOutput = TypeVar("TOutput", bound=BaseModel)


class BaseTool(ABC, Generic[TInput, TOutput]):
    """工具抽象基类

    所有工具都必须实现此接口，确保统一的调用方式。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称，用于 Planner 调用"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述，用于 Planner prompt"""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> type[TInput]:
        """输入参数的 Pydantic 模型类"""
        pass

    @property
    @abstractmethod
    def output_schema(self) -> type[TOutput]:
        """输出结果的 Pydantic 模型类"""
        pass

    @abstractmethod
    def execute(
        self,
        session: SessionState,
        input: TInput,
    ) -> tuple[TOutput, SessionState]:
        """执行工具

        Args:
            session: 当前会话状态
            input: 工具输入参数

        Returns:
            (工具执行结果, 更新后的 session)

        Note:
            即使工具不修改 session，也返回原 session 以保持接口一致性。
        """
        pass
```

### 4.3 工具列表与数据模型

#### 工具列表

| Tool | Type | 说明 | 优先级 |
|------|------|------|--------|
| `match_phenomena` | LLM+Embed | 将原始观察匹配到标准现象 | P0 核心 |
| `diagnose` | Deterministic | 继续诊断（处理反馈 + 推荐现象） | P0 核心 |
| `query_progress` | Deterministic | 查询当前诊断进展 | P0 核心 |
| `query_hypotheses` | Deterministic | 查询假设列表详情 | P0 核心 |
| `query_relations` | Deterministic | 图谱查询（现象↔根因关系） | P1 |

**后续扩展（P2）**：
- `show_history` - 查看对话历史摘要
- `explain_reasoning` - 解释推荐/诊断的推理过程

#### 数据模型定义

```python
"""
dbdiag/core/agent/models.py

Tool 输入输出的数据模型定义
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ============================================================
# 基础模型
# ============================================================

class ToolOutput(BaseModel):
    """Tool 执行结果的基类"""
    success: bool = True
    error_message: Optional[str] = None


# ============================================================
# match_phenomena 工具
# ============================================================

class RawObservation(BaseModel):
    """原始观察描述"""
    description: str = Field(description="用户原始描述，如 'IO 很高'")
    context: Optional[str] = Field(
        default=None,
        description="上下文信息，如 '用户在回应上轮推荐的现象'"
    )


class MatchPhenomenaInput(BaseModel):
    """现象匹配工具的输入"""
    raw_observations: List[RawObservation] = Field(
        description="需要匹配的原始观察描述列表"
    )
    confirmations: List[str] = Field(
        default_factory=list,
        description="直接确认的现象 ID 列表（如用户说'1确认'）"
    )
    denials: List[str] = Field(
        default_factory=list,
        description="否认的现象 ID 列表"
    )
    dialogue_history: str = Field(
        default="",
        description="最近对话历史，用于指代消解"
    )
    pending_recommendations: List[dict] = Field(
        default_factory=list,
        description="当前待确认的现象列表（用于指代消解）"
    )


class CandidatePhenomenon(BaseModel):
    """召回的候选现象"""
    phenomenon_id: str
    description: str
    observation_method: str
    similarity_score: float = Field(ge=0, le=1)


class MatchedPhenomenon(BaseModel):
    """匹配到的现象"""
    phenomenon_id: str = Field(description="现象 ID，如 P-0001")
    phenomenon_description: str = Field(description="现象的标准描述")
    user_observation: str = Field(description="用户原始描述")
    match_score: float = Field(
        ge=0, le=1,
        description="匹配度，作为贝叶斯计算的权重"
    )
    extracted_value: Optional[str] = Field(
        default=None,
        description="从用户描述中提取的具体数值，如 '65%'"
    )


class ClarificationOption(BaseModel):
    """澄清选项"""
    phenomenon_id: str
    description: str
    observation_method: str


class InterpretedObservation(BaseModel):
    """解释后的观察"""
    raw_description: str = Field(description="原始用户描述")
    matched_phenomenon: Optional[MatchedPhenomenon] = Field(
        default=None,
        description="匹配到的现象（如果匹配成功）"
    )
    needs_clarification: bool = Field(
        default=False,
        description="是否需要用户澄清"
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="澄清问题（如果需要澄清）"
    )
    clarification_options: List[ClarificationOption] = Field(
        default_factory=list,
        description="候选选项（如果需要澄清）"
    )


class MatchPhenomenaOutput(ToolOutput):
    """现象匹配工具的输出"""
    interpreted: List[InterpretedObservation] = Field(
        description="解释结果列表，每个原始描述对应一个"
    )
    all_matched: bool = Field(
        description="是否全部匹配成功（无需澄清）"
    )


# ============================================================
# diagnose 工具
# ============================================================

class DiagnoseInput(BaseModel):
    """诊断工具的输入 - 纯结构化数据，由 match_phenomena 预处理"""
    confirmed_phenomena: List[MatchedPhenomenon] = Field(
        default_factory=list,
        description="确认的现象列表（已匹配，含匹配度）"
    )
    denied_phenomena: List[str] = Field(
        default_factory=list,
        description="否认的现象 ID，如 ['P-0001', 'P-0002']"
    )


class Hypothesis(BaseModel):
    """假设信息"""
    root_cause_id: str
    root_cause_description: str
    confidence: float = Field(ge=0, le=1, description="置信度 0-1")
    contributing_phenomena: List[str] = Field(
        default_factory=list,
        description="贡献的现象 ID"
    )


class Recommendation(BaseModel):
    """推荐现象信息"""
    phenomenon_id: str
    description: str
    observation_method: str
    reason: str = Field(description="推荐原因，面向用户的解释")
    related_hypotheses: List[str] = Field(
        default_factory=list,
        description="关联的根因 ID"
    )
    information_gain: float = Field(
        ge=0, le=1,
        description="信息增益分数"
    )


class Diagnosis(BaseModel):
    """诊断结论"""
    root_cause_id: str
    root_cause_description: str
    confidence: float
    observed_phenomena: List[str] = Field(description="观察到的现象描述")
    solution: str
    reference_tickets: List[str] = Field(description="参考工单 ID")
    reasoning: str = Field(description="推导过程说明")


class DiagnoseOutput(ToolOutput):
    """诊断工具的输出"""
    diagnosis_complete: bool = Field(description="是否完成诊断（置信度达阈值）")
    hypotheses: List[Hypothesis] = Field(description="假设列表，按置信度排序")
    recommendations: List[Recommendation] = Field(
        default_factory=list,
        description="推荐现象列表（仅当 diagnosis_complete=False）"
    )
    diagnosis: Optional[Diagnosis] = Field(
        default=None,
        description="诊断结论（仅当 diagnosis_complete=True）"
    )


# ============================================================
# query_progress 工具
# ============================================================

class QueryProgressInput(BaseModel):
    """查询进展的输入 - 无需参数"""
    pass


class QueryProgressOutput(ToolOutput):
    """查询进展的输出"""
    rounds: int = Field(description="已进行轮次")
    confirmed_count: int = Field(description="已确认现象数")
    denied_count: int = Field(description="已否认现象数")
    hypotheses_count: int = Field(description="当前假设数")
    top_hypothesis: Optional[str] = Field(description="最可能的根因描述")
    top_confidence: float = Field(description="最高置信度")
    status: Literal["exploring", "narrowing", "confirming", "stuck"] = Field(
        description="诊断状态"
    )
    status_description: str = Field(description="状态的自然语言描述")


# ============================================================
# query_hypotheses 工具
# ============================================================

class QueryHypothesesInput(BaseModel):
    """查询假设的输入"""
    top_k: int = Field(default=5, ge=1, le=10, description="返回前 K 个假设")


class HypothesisDetail(BaseModel):
    """假设详情"""
    root_cause_id: str
    root_cause_description: str
    confidence: float
    rank: int = Field(description="排名，从 1 开始")
    contributing_phenomena: List[str] = Field(description="贡献的现象 ID")
    missing_phenomena: List[str] = Field(description="尚未确认但相关的现象描述")
    related_tickets: List[str] = Field(description="相关工单 ID")


class QueryHypothesesOutput(ToolOutput):
    """查询假设的输出"""
    hypotheses: List[HypothesisDetail]
    total_count: int = Field(description="假设总数")


# ============================================================
# query_relations 工具
# ============================================================

class QueryRelationsInput(BaseModel):
    """图谱查询的输入"""
    query_type: Literal["phenomenon_to_root_causes", "root_cause_to_phenomena"] = Field(
        description="查询方向：现象→根因 或 根因→现象"
    )
    phenomenon_id: Optional[str] = Field(
        default=None,
        description="现象 ID（当 query_type 为 phenomenon_to_root_causes 时）"
    )
    root_cause_id: Optional[str] = Field(
        default=None,
        description="根因 ID（当 query_type 为 root_cause_to_phenomena 时）"
    )


class GraphRelation(BaseModel):
    """图谱关系"""
    entity_id: str
    entity_description: str
    relation_strength: float = Field(
        ge=0, le=1,
        description="关联强度，基于 ticket_count 归一化"
    )
    supporting_ticket_count: int


class QueryRelationsOutput(ToolOutput):
    """图谱查询的输出"""
    query_type: str
    source_entity_id: str
    source_entity_description: str
    results: List[GraphRelation]
```

### 4.4 工具实现示例

```python
"""
dbdiag/core/agent/tools/diagnose.py
"""

from dbdiag.core.agent.tools.base import BaseTool
from dbdiag.core.agent.models import DiagnoseInput, DiagnoseOutput
from dbdiag.core.agent.models import SessionState
from dbdiag.core.agent.graph_engine import GraphEngine


class DiagnoseTool(BaseTool[DiagnoseInput, DiagnoseOutput]):
    """诊断工具

    执行核心诊断算法（贝叶斯推理），更新假设置信度。
    """

    def __init__(self, graph_engine: GraphEngine):
        self.graph_engine = graph_engine

    @property
    def name(self) -> str:
        return "diagnose"

    @property
    def description(self) -> str:
        return "执行诊断，处理已匹配的现象，更新假设置信度，推荐下一步确认的现象"

    @property
    def input_schema(self) -> type[DiagnoseInput]:
        return DiagnoseInput

    @property
    def output_schema(self) -> type[DiagnoseOutput]:
        return DiagnoseOutput

    def execute(
        self,
        session: SessionState,
        input: DiagnoseInput,
    ) -> tuple[DiagnoseOutput, SessionState]:
        """执行诊断"""
        return self.graph_engine.diagnose(session, input)


"""
dbdiag/core/agent/tools/match_phenomena.py
"""

class MatchPhenomenaTool(BaseTool[MatchPhenomenaInput, MatchPhenomenaOutput]):
    """现象匹配工具

    将用户的原始观察描述匹配到标准 phenomena。
    使用 Embedding 召回 + LLM 精排。
    """

    def __init__(
        self,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        phenomenon_dao: PhenomenonDAO,
    ):
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self.phenomenon_dao = phenomenon_dao

    @property
    def name(self) -> str:
        return "match_phenomena"

    @property
    def description(self) -> str:
        return "将用户原始观察描述匹配到标准现象，支持指代消解和澄清引导"

    @property
    def input_schema(self) -> type[MatchPhenomenaInput]:
        return MatchPhenomenaInput

    @property
    def output_schema(self) -> type[MatchPhenomenaOutput]:
        return MatchPhenomenaOutput

    def execute(
        self,
        session: SessionState,
        input: MatchPhenomenaInput,
    ) -> tuple[MatchPhenomenaOutput, SessionState]:
        """执行现象匹配"""
        # 1. Embedding 召回候选
        # 2. LLM 精排 + 指代消解
        # 3. 返回结果（不修改 session）
        result = self._interpret(session, input)
        return result, session  # match_phenomena 不修改 session
```

### 4.5 Executor 实现

```python
"""
dbdiag/core/agent/executor.py
"""

from typing import Dict
from dbdiag.core.agent.tools.base import BaseTool
from dbdiag.core.agent.models import SessionState


class Executor:
    """工具执行器

    职责：管理和执行工具调用
    """

    def __init__(self, tools: list[BaseTool]):
        """初始化工具执行器

        Args:
            tools: 可用工具列表
        """
        self._tools: Dict[str, BaseTool] = {
            tool.name: tool for tool in tools
        }

    @property
    def available_tools(self) -> list[str]:
        """返回可用工具名称列表"""
        return list(self._tools.keys())

    def get_tool_descriptions(self) -> list[dict]:
        """返回工具描述列表，用于 Planner prompt"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema.model_json_schema(),
            }
            for tool in self._tools.values()
        ]

    def execute(
        self,
        session: SessionState,
        tool_name: str,
        params: dict,
    ) -> tuple[dict, SessionState]:
        """执行指定工具

        Args:
            session: 当前会话状态
            tool_name: 工具名称
            params: 工具参数（dict 形式，会转换为对应的 Input 模型）

        Returns:
            (工具执行结果的 dict, 更新后的 session)

        Raises:
            ValueError: 未知的工具名称
        """
        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool = self._tools[tool_name]

        # 将 dict 参数转换为工具的输入模型
        input_obj = tool.input_schema(**params)

        # 执行工具
        output, new_session = tool.execute(session, input_obj)

        # 返回 dict 形式的结果
        return output.model_dump(), new_session
```

### 4.6 工具注册与初始化

```python
"""
dbdiag/core/agent/dialogue_manager.py
"""

def create_executor(
    graph_engine: GraphEngine,
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    phenomenon_dao: PhenomenonDAO,
) -> Executor:
    """创建并初始化 Executor"""

    tools = [
        # 现象匹配工具（LLM + Embedding）
        MatchPhenomenaTool(
            llm_service=llm_service,
            embedding_service=embedding_service,
            phenomenon_dao=phenomenon_dao,
        ),
        # 诊断工具（确定性）
        DiagnoseTool(graph_engine=graph_engine),
        # 查询工具（确定性）
        QueryProgressTool(graph_engine=graph_engine),
        QueryHypothesesTool(graph_engine=graph_engine),
        QueryRelationsTool(graph_engine=graph_engine),
    ]

    return Executor(tools)
```

### 4.7 Agent Loop 主循环

Agent Loop 由 `AgentDialogueManager` 实现：

```python
class AgentDialogueManager:
    """Agent 对话管理器"""

    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        responder: Responder,
    ):
        self.planner = planner
        self.executor = executor
        self.responder = responder

    def handle_user_input(
        self,
        session: SessionState,
        user_input: str,
    ) -> tuple[str, SessionState]:
        """处理用户输入，返回响应"""

        # 记录用户输入
        session.add_user_dialogue(user_input)

        # Agent Loop
        loop_context = {"type": "user_input", "content": user_input}

        while True:
            # Planner 决策
            decision = self.planner.decide(session, loop_context)

            if decision.decision == "respond":
                # 生成响应，退出循环
                response = self.responder.render(
                    session=session,
                    response_context=decision.response_context,
                )
                session.add_assistant_dialogue(response, decision.response_context)
                return response, session

            elif decision.decision == "call":
                # 执行工具
                result, session = self.executor.execute(
                    session=session,
                    tool_name=decision.tool,
                    params=decision.params,
                )
                # 将结果作为下一轮的 loop_context
                loop_context = {
                    "type": "tool_result",
                    "tool": decision.tool,
                    "result": result,
                }
```

### 4.8 对话历史管理

对话历史由 `AgentDialogueManager` 管理：

```
User Input: "1确认，另外 IO 很高"
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│ DialogueManager                                                 │
│                                                                 │
│ 1. Record user input to dialogue_history                        │
│                                                                 │
│ 2. Agent Loop:                                                  │
│    ┌─────────────────────────────────────────────────────────┐  │
│    │ Loop 1: Planner -> call match_phenomena                 │  │
│    │ Loop 2: Planner -> call diagnose                        │  │
│    │ Loop 3: Planner -> respond                              │  │
│    └─────────────────────────────────────────────────────────┘  │
│                                                                 │
│ 3. Record assistant response to dialogue_history                │
│    (include: response text + tool calls summary)                │
└─────────────────────────────────────────────────────────────────┘
              │
              ▼
        Response to User
```

**存储内容**：
- 用户侧：存原文（方便 Planner 理解上下文）
- 系统侧：存响应文本 + 工具调用摘要（便于调试和上下文理解）

**传递给 Planner**：只传最近 3 轮对话历史，控制 token 消耗

---

## 五、Responder 设计

### 5.1 职责

Responder 负责将 Agent Loop 的最终结果转换为自然语言响应。

### 5.2 设计决策

1. **使用 LLM 生成主体响应**：实现"像真人对话"的效果
2. **推荐现象包含完整信息**：描述、observation_method、推荐原因
3. **错误需明确说明**：什么失败了、原因、当前状况、建议
4. **附录仅 API 返回**：CLI/Web 暂不展示结构化详情

### 5.3 响应结构

```python
class AgentResponse(BaseModel):
    """Agent 响应"""

    # 主体响应（自然语言，面向用户，包含完整信息）
    message: str

    # 结构化详情（仅 API 返回，CLI/Web 暂不展示）
    details: Optional[ResponseDetails] = None


class ResponseDetails(BaseModel):
    """响应详情（结构化数据，仅 API 返回）"""

    status: str
    top_hypothesis: Optional[str]
    top_confidence: float
    call_results: List[CallResult]
    recommendations: List[Recommendation] = []
    diagnosis: Optional[Diagnosis] = None
    call_errors: List[CallError] = []


class CallResult(BaseModel):
    """工具调用结果"""
    tool: str
    success: bool
    summary: str  # 一句话摘要


class CallError(BaseModel):
    """工具调用错误"""
    tool: str
    error_message: str
```

### 5.4 Prompt 设计

```
你是一个数据库诊断助手。根据诊断结果生成自然、友好的响应。

## 要求

1. 用口语化的方式描述诊断进展和建议
2. 如果有推荐现象，必须包含完整信息：
   - 现象描述
   - 如何观察（observation_method）
   - 为什么推荐这个现象
3. 如果有工具调用失败，必须说明：
   - 什么操作执行不成功
   - 失败原因
   - 目前的状况是什么
   - 建议用户怎么做
4. 根据诊断状态调整语气：
   - exploring（早期）：鼓励用户继续提供信息
   - narrowing（缩小范围）：表达进展，引导确认关键现象
   - confirming（接近确认）：表达信心，但提醒还需确认
   - stuck（卡住）：委婉表达困难，建议换个方向
5. 如果有多个工具调用结果，自然地整合在一起

## 输出格式

直接输出响应文本。推荐现象用编号列表展示，每个现象包含描述、观察方法、推荐原因。
```

### 5.5 响应示例

**正常情况**：

```
好的，我记录下了你的反馈。目前来看，索引膨胀的可能性比较大（58%），
这是基于你确认的 wait_io 高和索引增长推断的。

建议接下来确认以下现象：

1. 死元组数量异常高
   - 如何观察：SELECT n_dead_tup FROM pg_stat_user_tables WHERE relname = 'xxx';
   - 推荐原因：与假设"索引膨胀导致 IO 瓶颈"强相关，可进一步提高置信度

2. 表膨胀率超过阈值
   - 如何观察：检查 pg_stat_user_tables 的 n_live_tup 与实际行数的比值
   - 推荐原因：可区分索引膨胀和表膨胀两种情况
```

**有错误的情况**：

```
查询诊断进展时遇到问题，原因是：会话状态异常。

目前的状况是：你刚才的反馈（1确认 2否定）已经成功记录，当前最可能的根因是索引膨胀（58%）。

建议：可以继续提供观察信息，或者输入"重新开始"来开启新的诊断会话。
```

---

## 六、GraphEngine 设计

### 6.1 设计目标

GraphEngine 是诊断系统的**确定性核心**，提供：

1. **纯确定性算法**：贝叶斯推理、信息增益计算，不依赖 LLM
2. **无状态设计**：所有方法接收 session 状态，返回结果和更新后的 session
3. **独立可测试**：可以单独对每个方法进行单元测试

### 6.2 核心接口

```python
"""
dbdiag/core/agent/graph_engine.py
"""

class GraphEngine:
    """诊断图谱引擎

    职责：
    1. 管理诊断图谱（GraphBuilder, GraphQuery）
    2. 计算假设置信度（ConfidenceCalculator）
    3. 推荐下一步确认的现象（信息增益排序）
    """

    # 阈值常量
    HIGH_CONFIDENCE_THRESHOLD = 0.95   # 高置信度，可以给出诊断
    MEDIUM_CONFIDENCE_THRESHOLD = 0.50 # 中等置信度
    RECOMMEND_TOP_N = 5                # 推荐现象数量

    def __init__(
        self,
        phenomenon_dao: PhenomenonDAO,
        root_cause_dao: RootCauseDAO,
        ticket_dao: TicketDAO,
    ):
        """初始化核心引擎"""
        self.graph_builder = GraphBuilder(phenomenon_dao, root_cause_dao, ticket_dao)
        self.graph_query = GraphQuery(self.graph_builder)
        self.confidence_calculator = ConfidenceCalculator()

    def diagnose(
        self,
        session: SessionState,
        input: DiagnoseInput,
    ) -> tuple[DiagnoseOutput, SessionState]:
        """执行诊断

        Args:
            session: 当前会话状态
            input: 诊断输入（确认/否认的现象）

        Returns:
            (诊断结果, 更新后的 session)
        """
        ...

    def query_progress(
        self,
        session: SessionState,
    ) -> QueryProgressOutput:
        """查询诊断进展"""
        ...

    def query_hypotheses(
        self,
        session: SessionState,
        top_k: int = 5,
    ) -> QueryHypothesesOutput:
        """查询假设详情"""
        ...

    def query_relations(
        self,
        entity_id: str,
        query_type: str,
    ) -> QueryRelationsOutput:
        """图谱关系查询"""
        ...
```

### 6.3 diagnose 方法详解

`diagnose` 是核心方法，处理流程：

```
Input: DiagnoseInput
  - confirmed_phenomena: [{P-0001, score: 1.0}, {P-0012, score: 0.85}]
  - denied_phenomena: ["P-0002"]
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Update session state                                   │
│                                                                 │
│  - Add confirmed phenomena to session.confirmed_observations    │
│  - Add denied phenomena to session.denied_observations          │
│  - Update session.rounds                                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: Calculate hypotheses confidence (Bayesian)             │
│                                                                 │
│  For each root_cause in graph:                                  │
│    P(RC|observations) = ConfidenceCalculator.calculate(...)     │
│                                                                 │
│  Output: sorted hypotheses by confidence                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Check diagnosis condition                              │
│                                                                 │
│  if top_confidence >= HIGH_CONFIDENCE_THRESHOLD:                │
│    diagnosis_complete = True                                    │
│    Generate Diagnosis                                           │
│  else:                                                          │
│    diagnosis_complete = False                                   │
│    Generate recommendations (Step 4)                            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: Generate recommendations (if not complete)             │
│                                                                 │
│  For each unconfirmed phenomenon:                               │
│    info_gain = calculate_information_gain(phenomenon)           │
│                                                                 │
│  Return top-N by info_gain, with reasons                        │
└─────────────────────────────────────────────────────────────────┘

Output: DiagnoseOutput
  - diagnosis_complete: bool
  - hypotheses: [Hypothesis, ...]
  - recommendations: [Recommendation, ...] (if not complete)
  - diagnosis: Diagnosis (if complete)
```

### 6.4 子模块职责

| 模块 | 职责 | 是否使用 LLM |
|------|------|-------------|
| **GraphBuilder** | 从 DAO 构建诊断图谱（phenomenon ↔ root_cause 关系） | 否 |
| **GraphQuery** | 查询图谱关系（根因的关联现象、现象的关联根因等） | 否 |
| **ConfidenceCalculator** | 贝叶斯推理计算假设置信度 | 否 |

---

## 七、核心工具设计：match_phenomena

### 7.1 职责

match_phenomena 是一个**工具**，负责将用户的原始观察描述匹配到标准 phenomena。它与 diagnose、query_progress 等工具同层，由 Executor 协调调用。

核心职责：
1. **Embedding 召回**：根据用户描述召回 top-k 候选 phenomena
2. **LLM 精排**：结合对话历史、背景知识，判断最匹配的 phenomena
3. **指代消解**：处理"上一轮提到的那个"等指代表达
4. **引导具体化**：描述太模糊时，生成澄清问题引导用户

### 7.2 输入输出定义

数据模型定义见 [4.3 工具列表与数据模型](#43-工具列表与数据模型) 中的 match_phenomena 部分。

关键模型：
- `MatchPhenomenaInput`：包含原始观察、确认/否认列表、对话历史
- `MatchPhenomenaOutput`：包含解释结果列表、是否全部匹配成功
- `CandidatePhenomenon`：Embedding 召回的候选现象
- `MatchedPhenomenon`：最终匹配到的现象（含匹配度）
- `InterpretedObservation`：每个原始描述的解释结果

### 7.3 处理流程

```
Input: raw_observations = ["IO 很高", "上一轮说的那个也有"]
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Embedding Recall (per observation)                     │
│                                                                 │
│  "IO 很高" -> top-5 candidates:                                 │
│    - P-0012 "wait_io 占比高" (sim: 0.88)                        │
│    - P-0015 "io_util 高" (sim: 0.82)                            │
│    - P-0023 "磁盘 IOPS 高" (sim: 0.75)                          │
│    - ...                                                        │
│                                                                 │
│  "上一轮说的那个也有" -> no direct match (指代表达)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: LLM Interpretation                                     │
│                                                                 │
│  Input:                                                         │
│    - raw_observations + candidates                              │
│    - dialogue_history (含上轮推荐的现象)                         │
│    - pending_recommendations                                    │
│    - DB 运维背景知识                                             │
│                                                                 │
│  LLM 判断:                                                      │
│    - "IO 很高" -> P-0012 (score: 0.88, 高置信)                  │
│    - "上一轮说的那个" -> 指代 P-0005 (上轮推荐的第一个)          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Output                                                 │
│                                                                 │
│  MatchPhenomenaOutput:                                          │
│    all_matched: true                                            │
│    interpreted: [                                               │
│      {raw: "IO很高", matched: {P-0012, 0.88}, needs_clarif: F}, │
│      {raw: "上一轮...", matched: {P-0005, 1.0}, needs_clarif: F}│
│    ]                                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 7.4 澄清场景处理

当匹配不确定时，生成澄清问题：

```
Input: "数据库有点慢"
              │
              ▼
Step 1: Embedding Recall
  candidates:
    - P-0031 "查询响应时间长" (sim: 0.65)
    - P-0032 "连接建立慢" (sim: 0.62)
    - P-0033 "写入延迟高" (sim: 0.58)
              │
              ▼
Step 2: LLM Interpretation
  判断: 描述太模糊，无法确定具体类型
              │
              ▼
Step 3: Output
  MatchPhenomenaOutput:
    all_matched: false
    interpreted: [{
      raw: "数据库有点慢",
      matched: null,
      needs_clarification: true,
      clarification_question: "你说的'慢'具体是指哪种情况？",
      clarification_options: [
        {P-0031, "查询响应时间长", "执行 SQL 后等待结果时间久"},
        {P-0032, "连接建立慢", "应用连接数据库时耗时长"},
        {P-0033, "写入延迟高", "INSERT/UPDATE 执行慢"},
      ]
    }]
```

### 7.5 Prompt 设计

````
你是数据库诊断系统的观察解释器。你的任务是将用户的观察描述匹配到标准现象库。

## 输入

### 用户原始描述
{raw_observations}

### 候选现象（Embedding 召回）
{candidates_json}

### 对话历史
{dialogue_history}

### 当前待确认的现象
{pending_recommendations}

## 任务

对每个用户描述，判断：

1. **能否匹配**：是否能确定对应哪个标准现象
2. **匹配置信度**：0-1 之间，表示匹配的确定程度
3. **指代消解**：如果是指代表达（如"上一轮那个"），解析指代对象
4. **数值提取**：如果描述中包含具体数值（如"65%"），提取出来

## 输出格式

```json
{
  "interpretations": [
    {
      "raw_description": "用户原始描述",
      "matched": {
        "phenomenon_id": "P-xxxx",
        "match_score": 0.85,
        "extracted_value": "65%"  // 如有
      },
      // 或者
      "needs_clarification": true,
      "clarification_question": "澄清问题",
      "options": ["P-0001", "P-0002"]
    }
  ]
}
```

## 判断规则

1. **高置信匹配 (score >= 0.8)**：描述明确对应某个现象
2. **中等置信 (0.6 <= score < 0.8)**：可能匹配，但建议确认
3. **低置信 (score < 0.6)**：需要澄清
4. **指代表达**：根据对话历史和待确认列表解析，匹配后 score = 1.0
5. **多候选接近**：top-2 的 similarity 差距 < 0.1 时，需要澄清
````

---

## 八、核心工具设计：diagnose

### 8.1 职责

diagnose 工具是 GraphEngine 的封装，负责执行贝叶斯推理诊断。

### 8.2 输入输出

数据模型定义见 [4.3 工具列表与数据模型](#43-工具列表与数据模型) 中的 diagnose 部分。

关键模型：
- `DiagnoseInput`：确认的现象列表（含匹配度）、否认的现象 ID 列表
- `DiagnoseOutput`：是否完成诊断、假设列表、推荐现象、诊断结论
- `Hypothesis`：假设摘要（id, description, confidence）
- `HypothesisDetail`：假设详情（含 rank, missing_phenomena, related_tickets）
- `Recommendation`：推荐现象信息
- `Diagnosis`：诊断结论

### 8.3 贝叶斯推理算法

#### 8.3.1 核心公式

使用贝叶斯定理计算根因置信度：

```
P(RC | O₁, O₂, ..., Oₙ) ∝ P(RC) × ∏ᵢ P(Oᵢ | RC)
```

其中：
- `RC`: 根因 (Root Cause)
- `Oᵢ`: 第 i 个观察到的现象 (Observation)
- `P(RC)`: 根因的先验概率
- `P(Oᵢ | RC)`: 在根因为 RC 的情况下，观察到现象 Oᵢ 的似然

#### 8.3.2 先验概率 P(RC)

基于历史工单统计：

```python
P(RC) = ticket_count(RC) / total_tickets
```

#### 8.3.3 似然 P(O | RC)

基于工单中现象与根因的共现统计：

```python
P(O | RC) = co_occurrence(O, RC) / ticket_count(RC)
```

**匹配度加权**：当现象不是 100% 确认时，用匹配度作为权重：

```python
# 原始似然
raw_likelihood = P(O | RC)

# 加权似然（match_score 来自 match_phenomena）
weighted_likelihood = 1 + (raw_likelihood - 1) * match_score

# 例如：match_score = 0.85, raw_likelihood = 0.7
# weighted_likelihood = 1 + (0.7 - 1) * 0.85 = 0.745
```

#### 8.3.4 否认现象处理

否认某现象时，降低关联根因的置信度：

```python
# 如果 O 被否认，且 O 与 RC 强相关
if denied(O) and P(O | RC) > 0.5:
    penalty = 1 - P(O | RC)  # 惩罚因子
    P(RC | observations) *= penalty
```

#### 8.3.5 算法伪代码

```python
def calculate_confidence(
    session: SessionState,
    graph: DiagnosisGraph,
) -> List[Hypothesis]:
    """计算所有根因的置信度"""

    hypotheses = []

    for rc in graph.root_causes:
        # 1. 先验概率
        prior = rc.ticket_count / graph.total_tickets

        # 2. 似然累积
        likelihood = 1.0
        for obs in session.confirmed_observations:
            p_o_given_rc = graph.get_co_occurrence(obs.phenomenon_id, rc.id)
            weighted = 1 + (p_o_given_rc - 1) * obs.match_score
            likelihood *= weighted

        # 3. 否认惩罚
        for denied_id in session.denied_observations:
            p_o_given_rc = graph.get_co_occurrence(denied_id, rc.id)
            if p_o_given_rc > 0.5:
                likelihood *= (1 - p_o_given_rc)

        # 4. 后验（未归一化）
        posterior = prior * likelihood
        hypotheses.append(Hypothesis(
            root_cause_id=rc.id,
            root_cause_description=rc.description,
            confidence=posterior,
            contributing_phenomena=[...],
        ))

    # 5. 归一化
    total = sum(h.confidence for h in hypotheses)
    for h in hypotheses:
        h.confidence /= total

    # 6. 排序返回
    return sorted(hypotheses, key=lambda h: h.confidence, reverse=True)
```

### 8.4 信息增益计算

推荐现象时，按信息增益排序：

```python
def calculate_information_gain(phenomenon_id: str, hypotheses: List[Hypothesis]) -> float:
    """计算确认某现象的信息增益

    信息增益 = 确认后假设分布的熵减少量
    """
    current_entropy = calculate_entropy(hypotheses)

    # 模拟确认该现象后的假设分布
    hypotheses_if_confirmed = simulate_confirmation(phenomenon_id, hypotheses)
    entropy_if_confirmed = calculate_entropy(hypotheses_if_confirmed)

    # 模拟否认该现象后的假设分布
    hypotheses_if_denied = simulate_denial(phenomenon_id, hypotheses)
    entropy_if_denied = calculate_entropy(hypotheses_if_denied)

    # 期望信息增益（加权平均）
    p_confirm = estimate_confirmation_probability(phenomenon_id)
    expected_entropy = p_confirm * entropy_if_confirmed + (1 - p_confirm) * entropy_if_denied

    return current_entropy - expected_entropy
```

---

## 九、会话管理

### 9.1 设计决策

1. **第一版保持内存会话**：和现有 GAR2 一致，简化实现
2. **超时策略**：
   - CLI：无需处理（用户主动退出）
   - Web API：30 分钟超时
3. **多会话并发**：Web API 通过 session_id 区分不同用户的会话

### 9.2 后续演进

会话持久化（存 DB）作为后续优化项，当前版本不实现。

---

## 十、与现有系统集成

### 10.1 CLI 集成

**方案**：实现独立的 `AgentCLI`，继承 `CLI` 基类

```python
class AgentCLI(CLI):
    """Agent 诊断系统 CLI"""

    def __init__(
        self,
        dialogue_manager: AgentDialogueManager,
        ...
    ):
        super().__init__(...)
        self.dialogue_manager = dialogue_manager

    def run(self):
        """运行 CLI 主循环"""
        ...
```

### 10.2 Web API 集成

**方案**：复用现有 `/chat` 端点，通过配置切换模式

```python
# 配置
agent:
  enabled: true  # 启用 Agent 模式

# 路由保持不变
POST /chat
{
  "session_id": "xxx",
  "message": "用户输入"
}
```

### 10.3 配置项

```yaml
agent:
  enabled: true                      # 是否启用 Agent 模式
  agent_model: "gpt-4"               # Planner 使用的模型
  response_model: "gpt-3.5-turbo"    # Responder 使用的模型
  high_confidence_threshold: 0.95    # 诊断完成阈值
  stuck_detection_rounds: 3          # 卡住检测轮数
  session_timeout_minutes: 30        # 会话超时时间（Web API）
```

---

## 十一、测试策略

### 11.1 GraphEngine 单元测试

构造固定的 session 状态和 input，验证 output：

```python
def test_diagnose_with_confirmations():
    """测试确认现象后的诊断"""
    graph_engine = GraphEngine(...)
    session = create_test_session(confirmed=["P-0001"])
    input = DiagnoseInput(confirmations=["P-0002"])

    output, new_session = graph_engine.diagnose(session, input)

    assert output.success
    assert len(new_session.symptom.observations) == 2
    assert output.hypotheses[0].confidence > 0
```

### 11.2 Planner 测试

Mock LLM 返回预设 JSON：

```python
def test_planner_diagnose_intent():
    """测试识别诊断意图"""
    mock_llm = Mock()
    mock_llm.generate.return_value = '''
    {
      "actions": [{"action": "diagnose", "parameters": {"confirmations": ["P-0001"]}}],
      "reasoning": "用户确认了第一个现象"
    }
    '''

    planner = Planner(mock_llm)
    decision = planner.plan(session, "1确认")

    assert decision.actions[0]["action"] == "diagnose"
    assert "P-0001" in decision.actions[0]["parameters"]["confirmations"]
```

### 11.3 E2E 测试场景

| 场景 | 描述 | 验证点 |
|------|------|--------|
| 正常诊断流程 | 用户描述问题 → 确认现象 → 得出结论 | 置信度递增，最终诊断正确 |
| 查询进展 | 用户中途询问"现在怎么样了" | 返回正确的状态摘要 |
| 混合意图 | "1确认，现在进展如何？" | 多个工具依次调用 |
| 澄清流程 | 用户输入模糊 → 系统澄清 → 用户回应 | 正确理解澄清后的回应 |
| 错误处理 | 工具调用失败 | 响应中包含错误说明和建议 |

---

## 十二、实施计划

### 阶段一：核心工具实现

1. 创建 `dbdiag/core/agent/tools/` 目录结构
2. 实现 `diagnose.py` - 诊断工具（纯确定性）
3. 实现 `query_progress.py`、`query_hypotheses.py`、`query_relations.py` - 查询工具
4. 实现 `match_phenomena.py` - 现象匹配工具（Embedding 召回 + LLM 精排）
5. 编写各工具的单元测试

### 阶段二：Agent Loop 实现

1. 创建 `dbdiag/core/agent/models.py` - AgentDecision 等数据模型
2. 实现 `planner.py` - Planner 决策层
3. 实现 `executor.py` - Executor 工具执行器
4. 实现 `responder.py` - Responder 响应生成层
5. 实现 `dialogue_manager.py` - Agent Loop 主循环

### 阶段三：集成与测试

1. 实现 `AgentCLI`（继承 `CLI` 基类）
2. Web API 复用 `/chat` 端点，通过配置切换
3. 端到端测试（正常流程、澄清流程、错误处理）
4. 文档更新

---

## 附录

### A. 与现有架构对比

| 维度 | GAR2（现有） | Agent（新） |
|------|-------------|-----------|
| 意图理解 | IntentClassifier（3 种意图） | Planner（Agent Loop 动态决策） |
| 决策逻辑 | 硬编码在 DialogueManager | LLM 在循环中逐步决策 |
| 核心算法 | 耦合在 DialogueManager | 独立的工具（diagnose 等） |
| 现象匹配 | 内嵌在诊断流程中 | 独立工具 match_phenomena |
| 响应生成 | 返回结构化 dict | 自然语言 + 结构化附录 |
| 可扩展性 | 需改代码添加新功能 | 添加新工具即可 |

### B. 术语表

| 术语 | 说明 |
|------|------|
| Agent | 本设计的诊断系统名称 |
| Agent Loop | Agent 工作循环：决策 → 执行工具 → 再决策 → ... → 回复 |
| Action | Planner 决策的下一步行动，分两种：call（调用工具）或 respond（生成响应） |
| Planner | LLM 驱动的决策层，每次循环决定下一步 |
| Executor | 工具执行器，执行单个工具调用 |
| Responder | 响应生成层，将结构化结果转为自然语言 |
| ToolSet | 工具集合，包含所有可用工具 |
| Tool | Agent 可调用的工具，如 diagnose、match_phenomena |
| GraphEngine | 确定性诊断核心，包含贝叶斯推理、图谱查询等算法 |
| match_phenomena | 现象匹配工具，将用户描述匹配到标准现象（LLM + Embedding） |
| diagnose | 诊断工具，纯确定性贝叶斯推理 |

### C. 命名规范

#### 类命名

| 后缀 | 用途 | 示例 |
|------|------|------|
| `Input` | 工具的输入参数模型 | `DiagnoseInput`, `MatchPhenomenaInput` |
| `Output` | 工具的输出结果模型 | `DiagnoseOutput`, `MatchPhenomenaOutput` |
| 无后缀 | 核心业务实体 | `Hypothesis`, `Recommendation`, `Diagnosis` |
| `Detail` | 业务实体的详细版本（比无后缀版本多字段） | `HypothesisDetail` |

#### 数据模型一览

**工具输入/输出**：
- `MatchPhenomenaInput` / `MatchPhenomenaOutput`
- `DiagnoseInput` / `DiagnoseOutput`
- `QueryProgressInput` / `QueryProgressOutput`
- `QueryHypothesesInput` / `QueryHypothesesOutput`
- `QueryRelationsInput` / `QueryRelationsOutput`

**核心业务实体**：
- `Hypothesis` - 假设（用于 `DiagnoseOutput`）
- `HypothesisDetail` - 假设详情（用于 `QueryHypothesesOutput`，比 `Hypothesis` 多 rank、missing_phenomena 等字段）
- `Recommendation` - 推荐现象
- `Diagnosis` - 诊断结论

**辅助模型**：
- `ToolOutput` - 工具输出基类（含 success、error_message）
- `RawObservation` - 原始观察描述
- `MatchedPhenomenon` - 匹配到的现象
- `CandidatePhenomenon` - 召回的候选现象
- `InterpretedObservation` - 解释后的观察
- `ClarificationOption` - 澄清选项
- `GraphRelation` - 图谱关系

**Responder 模型**：
- `AgentResponse` - Agent 响应
- `ResponseDetails` - 响应详情
- `CallResult` - 工具调用结果摘要
- `CallError` - 工具调用错误

#### 变量/字段命名

| 命名 | 说明 |
|------|------|
| `call` | Planner 决策的动作类型（调用工具） |
| `respond` | Planner 决策的动作类型（生成响应） |
| `call_results` | 工具调用结果列表 |
| `call_errors` | 工具调用错误列表 |
| `confirmed_phenomena` | 确认的现象列表 |
| `denied_phenomena` | 否认的现象列表 |
| `hypotheses` | 假设列表 |
| `recommendations` | 推荐现象列表 |
| `diagnosis` | 诊断结论 |
