# Agentic GAR2 设计方案

> 日期：2024-12-09
> 状态：设计讨论中

## 一、背景与目标

### 1.1 现状问题

当前 GAR2 架构存在以下体验问题：

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

```
┌─────────────────────────────────────────────────────────────────┐
│                      用户交互层                                  │
│                    "像真人对话"                                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Agent 决策层 (LLM)                              │
│                                                                 │
│  输入: 用户消息 + 会话摘要 + 可用动作列表                        │
│  输出: { action, parameters, reasoning }                        │
│                                                                 │
│  关键: LLM 只决定"做什么"，不决定"怎么做"                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┬─────────────┐
              ▼             ▼             ▼             ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────┐
│ diagnose      │ │ query_progress│ │ query_graph   │ │ ...       │
│               │ │               │ │               │ │           │
│ GAR2 核心算法 │ │ 读取会话状态  │ │ 图谱查询      │ │ 其他工具  │
│ (确定性)      │ │ (确定性)      │ │ (确定性)      │ │           │
└───────────────┘ └───────────────┘ └───────────────┘ └───────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  响应生成层 (LLM)                                │
│                                                                 │
│  输入: 工具执行结果 + response_style                            │
│  输出: 自然语言响应（可解释，因为基于确定性结果）                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    AgenticGAR2DialogueManager                           │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │AgentPlanner │  │ActionExecutor│  │   ResponseRenderer      │  │
│  │ (LLM 决策)  │  │  (路由层)   │  │   (响应生成)            │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
│         │                │                     │                │
│         │    ┌───────────┴───────────┐         │                │
│         │    │                       │         │                │
│         ▼    ▼                       ▼         ▼                │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                       GAR2Core                              ││
│  │                                                             ││
│  │  ┌─────────────────┐  ┌─────────────────────────────────┐  ││
│  │  │ObservationMatcher│  │   ConfidenceCalculator          │  ││
│  │  └─────────────────┘  └─────────────────────────────────┘  ││
│  │                                                             ││
│  │  方法: diagnose(), query_progress(), query_hypotheses(),   ││
│  │        query_graph(), get_history(), generate_clarification()││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         DAO 层                                   │
│  PhenomenonDAO | RootCauseDAO | TicketDAO | ...                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 | 是否使用 LLM |
|------|------|-------------|
| **AgentPlanner** | 理解用户意图，决定执行哪些 Action，提取参数 | 是 |
| **ActionExecutor** | 将 AgentPlanner 的决策路由到 GAR2Core 的具体方法 | 否 |
| **GAR2Core** | 核心诊断算法，无状态，接收输入返回结果 | 部分（生成推理过程） |
| **ResponseRenderer** | 将结构化结果转换为自然语言响应 | 是 |

### 2.3 目录结构

```
dbdiag/core/
├── gar2a/                           # Agentic GAR2 (新增)
│   ├── __init__.py
│   ├── actions.py                  # Action 接口定义
│   ├── agent_planner.py            # Agent 决策层
│   ├── action_executor.py          # Action 路由层
│   ├── response_renderer.py        # 响应生成层
│   └── dialogue_manager.py         # AgenticGAR2 对话管理器
│
├── gar2/                           # GAR2 核心 (重构)
│   ├── __init__.py
│   ├── models.py                   # 数据模型 (扩展)
│   ├── core.py                     # 核心引擎 (新增，从 dialogue_manager 抽取)
│   ├── observation_matcher.py      # 观察匹配器 (不变)
│   ├── confidence_calculator.py    # 置信度计算器 (不变)
│   └── dialogue_manager.py         # 原 GAR2 对话管理器 (保留兼容)
│
└── intent/                         # 意图识别 (可能废弃，合并到 AgentPlanner)
    ├── __init__.py
    ├── models.py
    └── classifier.py
```

---

## 三、Action 接口设计

### 3.1 Action 列表

| Action | 说明 | 优先级 |
|--------|------|--------|
| `diagnose` | 继续诊断（处理用户反馈 + 推荐现象） | P0 核心 |
| `query_progress` | 查询当前诊断进展 | P0 核心 |
| `query_hypotheses` | 查询假设列表详情 | P0 核心 |
| `query_graph` | 图谱查询（现象↔根因关系） | P1 |
| `show_history` | 查看对话历史摘要 | P1 |
| `ask_clarification` | 请用户澄清模糊输入 | P1 |

**后续扩展（P2）**：
- `confirm_contradiction` - 确认用户是否改变想法
- `explain_reasoning` - 解释推荐/诊断的推理过程

### 3.2 接口定义

```python
"""
dbdiag/core/gar2a/actions.py

Agentic GAR2 的 Action 接口定义
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ============================================================
# 基础模型
# ============================================================

class ActionResult(BaseModel):
    """Action 执行结果的基类"""
    success: bool = True
    error_message: Optional[str] = None


# ============================================================
# Action 枚举
# ============================================================

class ActionType:
    """支持的 Action 类型"""
    DIAGNOSE = "diagnose"
    QUERY_PROGRESS = "query_progress"
    QUERY_HYPOTHESES = "query_hypotheses"
    QUERY_GRAPH = "query_graph"
    SHOW_HISTORY = "show_history"
    ASK_CLARIFICATION = "ask_clarification"


# ============================================================
# diagnose - 继续诊断 (P0)
# ============================================================

class DiagnoseInput(BaseModel):
    """诊断动作的输入"""
    confirmations: List[str] = Field(
        default_factory=list,
        description="确认的现象 ID，如 ['P-0001', 'P-0002']"
    )
    denials: List[str] = Field(
        default_factory=list,
        description="否认的现象 ID"
    )
    new_observations: List[str] = Field(
        default_factory=list,
        description="新观察描述，如 ['wait_io 占比 65%', '慢查询很多']"
    )


class HypothesisInfo(BaseModel):
    """假设信息"""
    root_cause_id: str
    root_cause_description: str
    confidence: float = Field(ge=0, le=1, description="置信度 0-1")
    contributing_observations: List[str] = Field(
        default_factory=list,
        description="贡献的观察描述"
    )
    contributing_phenomena: List[str] = Field(
        default_factory=list,
        description="贡献的现象 ID"
    )


class RecommendationInfo(BaseModel):
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


class DiagnosisInfo(BaseModel):
    """诊断结论"""
    root_cause_id: str
    root_cause_description: str
    confidence: float
    observed_phenomena: List[str] = Field(description="观察到的现象描述")
    solution: str
    reference_tickets: List[str] = Field(description="参考工单 ID")
    reasoning: str = Field(description="推导过程说明")


class DiagnoseOutput(ActionResult):
    """诊断动作的输出"""
    diagnosis_complete: bool = Field(description="是否完成诊断（置信度达阈值）")
    hypotheses: List[HypothesisInfo] = Field(description="假设列表，按置信度排序")
    recommendations: List[RecommendationInfo] = Field(
        default_factory=list,
        description="推荐现象列表（仅当 diagnosis_complete=False）"
    )
    diagnosis: Optional[DiagnosisInfo] = Field(
        default=None,
        description="诊断结论（仅当 diagnosis_complete=True）"
    )


# ============================================================
# query_progress - 查询诊断进展 (P0)
# ============================================================

class ProgressStatus:
    """诊断进展状态"""
    EXPLORING = "exploring"      # 早期探索：confirmed < 3
    NARROWING = "narrowing"      # 缩小范围：confirmed >= 3 且 top_confidence < 0.6
    CONFIRMING = "confirming"    # 接近确认：top_confidence >= 0.6
    STUCK = "stuck"              # 卡住：连续 3 轮 top_confidence 变化 < 0.05


class QueryProgressInput(BaseModel):
    """查询进展的输入 - 无需参数"""
    pass


class QueryProgressOutput(ActionResult):
    """查询进展的输出"""
    rounds: int = Field(description="已进行轮次")
    confirmed_count: int = Field(description="已确认现象数")
    denied_count: int = Field(description="已否认现象数")
    new_observation_count: int = Field(description="新观察数")
    hypotheses_count: int = Field(description="当前假设数")
    top_hypothesis: Optional[str] = Field(description="最可能的根因描述")
    top_confidence: float = Field(description="最高置信度")
    status: Literal["exploring", "narrowing", "confirming", "stuck"] = Field(
        description="诊断状态"
    )
    status_description: str = Field(description="状态的自然语言描述")


# ============================================================
# query_hypotheses - 查询假设详情 (P0)
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
    contributing_observations: List[str] = Field(description="贡献的观察描述")
    contributing_phenomena: List[str] = Field(description="贡献的现象 ID")
    missing_phenomena: List[str] = Field(description="尚未确认但相关的现象描述")
    related_tickets: List[str] = Field(description="相关工单 ID")


class QueryHypothesesOutput(ActionResult):
    """查询假设的输出"""
    hypotheses: List[HypothesisDetail]
    total_count: int = Field(description="假设总数")


# ============================================================
# query_graph - 图谱查询 (P1)
# ============================================================

class QueryGraphInput(BaseModel):
    """图谱查询的输入"""
    query_type: Literal["phenomenon_to_root_causes", "root_cause_to_phenomena"] = Field(
        description="查询方向：现象→根因 或 根因→现象"
    )
    phenomenon_id: Optional[str] = Field(
        default=None,
        description="现象 ID，如 P-0001（当 query_type 为 phenomenon_to_root_causes 时）"
    )
    root_cause_id: Optional[str] = Field(
        default=None,
        description="根因 ID，如 RC-0001（当 query_type 为 root_cause_to_phenomena 时）"
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


class QueryGraphOutput(ActionResult):
    """图谱查询的输出"""
    query_type: str
    source_entity_id: str
    source_entity_description: str
    results: List[GraphRelation]


# ============================================================
# show_history - 查看历史 (P1)
# ============================================================

class ShowHistoryInput(BaseModel):
    """查看历史的输入"""
    last_n_rounds: Optional[int] = Field(
        default=None,
        ge=1,
        description="最近 N 轮，None 表示全部"
    )


class RoundSummary(BaseModel):
    """轮次摘要"""
    round_number: int
    user_input_summary: str = Field(description="用户输入摘要")
    action_taken: str = Field(description="系统采取的动作")
    confirmations: List[str] = Field(description="该轮确认的现象 ID")
    denials: List[str] = Field(description="该轮否认的现象 ID")
    new_observations: List[str] = Field(description="该轮新增的观察")
    top_confidence_after: float = Field(description="该轮结束后的最高置信度")


class ShowHistoryOutput(ActionResult):
    """查看历史的输出"""
    total_rounds: int
    rounds: List[RoundSummary]


# ============================================================
# ask_clarification - 请求澄清 (P1)
# ============================================================

class ClarificationType:
    """澄清类型"""
    VAGUE_OBSERVATION = "vague_observation"      # 模糊的观察描述
    MISSING_VALUE = "missing_value"              # 缺少具体数值
    AMBIGUOUS_FEEDBACK = "ambiguous_feedback"    # 不确定是确认还是否认
    MULTIPLE_MATCHES = "multiple_matches"        # 匹配到多个实体


class AskClarificationInput(BaseModel):
    """请求澄清的输入"""
    clarification_type: Literal[
        "vague_observation",
        "missing_value",
        "ambiguous_feedback",
        "multiple_matches"
    ]
    context: str = Field(description="需要澄清的内容/用户原话")
    matched_entities: List[str] = Field(
        default_factory=list,
        description="匹配到的实体 ID（用于 multiple_matches 类型）"
    )


class ClarificationOption(BaseModel):
    """澄清选项"""
    option_id: str
    option_text: str
    entity_id: Optional[str] = Field(
        default=None,
        description="关联的实体 ID（如有）"
    )


class AskClarificationOutput(ActionResult):
    """请求澄清的输出"""
    question: str = Field(description="生成的澄清问题")
    options: List[ClarificationOption] = Field(
        default_factory=list,
        description="可选的回答选项（如适用）"
    )
    allow_free_text: bool = Field(
        default=True,
        description="是否允许自由文本回答"
    )


# ============================================================
# AgentPlanner 的输入输出
# ============================================================

class SessionSummary(BaseModel):
    """会话摘要，供 AgentPlanner 决策参考"""
    session_id: str
    rounds: int
    confirmed_count: int
    denied_count: int
    new_observation_count: int
    top_hypothesis: Optional[str]
    top_confidence: float
    status: str
    recent_actions: List[str] = Field(
        default_factory=list,
        description="最近 3 轮的 action 类型"
    )
    pending_recommendations: List[str] = Field(
        default_factory=list,
        description="当前待确认的现象 ID"
    )


class AgentDecision(BaseModel):
    """AgentPlanner 的决策输出"""
    actions: List[dict] = Field(
        description="要执行的 action 列表，每项包含 action 和 parameters"
    )
    reasoning: str = Field(description="决策理由，用于调试和日志")
```

---

## 四、AgentPlanner 设计

### 4.1 职责

AgentPlanner 负责：
1. 理解用户输入的意图
2. 决定执行哪些 Action（支持多个）
3. 从用户输入中提取 Action 所需的参数

### 4.2 Prompt 设计

#### System Prompt

````
你是一个数据库诊断助手的意图理解模块。你的任务是：
1. 理解用户的输入意图
2. 决定执行哪个 Action
3. 提取 Action 所需的参数

## 可用 Action

### diagnose（继续诊断）
当用户提供诊断反馈时使用，包括：
- 确认/否认推荐的现象（如"1确认"、"第二个没有"、"都确认"）
- 描述新的观察（如"另外发现慢查询很多"、"wait_io 占比 65%"）
- 开始新的诊断（首轮，用户描述问题）

参数：
- confirmations: 确认的现象 ID 列表
- denials: 否认的现象 ID 列表
- new_observations: 新观察描述列表

### query_progress（查询进展）
当用户询问当前诊断状态时使用，如：
- "现在进展如何？"
- "检查到哪了？"
- "还需要多久？"

参数：无

### query_hypotheses（查询假设）
当用户想了解当前的可能原因时使用，如：
- "还有什么可能？"
- "其他原因呢？"
- "为什么觉得是索引问题？"

参数：
- top_k: 返回假设数量，默认 5

### query_graph（图谱查询）
当用户想了解现象和根因的关联关系时使用，如：
- "wait_io 高会导致什么？"（需要先确定具体现象 ID）
- "索引膨胀有哪些表现？"（需要先确定具体根因 ID）

参数：
- query_type: "phenomenon_to_root_causes" 或 "root_cause_to_phenomena"
- phenomenon_id: 现象 ID（当 query_type 为 phenomenon_to_root_causes 时）
- root_cause_id: 根因 ID（当 query_type 为 root_cause_to_phenomena 时）

注意：如果用户用自然语言描述而非 ID，需要返回 ask_clarification 来确认具体实体。

### show_history（查看历史）
当用户想回顾之前的对话时使用，如：
- "之前说了什么？"
- "我确认过哪些？"
- "回顾一下"

参数：
- last_n_rounds: 查看最近几轮，null 表示全部

### ask_clarification（请求澄清）
当用户输入模糊或有歧义时使用：
- 观察描述模糊，需要具体数值
- 反馈不明确，不确定是确认还是否认
- 自然语言匹配到多个实体，需要用户选择

参数：
- clarification_type: "vague_observation" | "missing_value" | "ambiguous_feedback" | "multiple_matches"
- context: 需要澄清的内容
- matched_entities: 匹配到的实体 ID 列表（用于 multiple_matches）

## 决策规则

1. **优先处理诊断反馈**：如果用户输入包含对现象的确认/否认/新观察，优先使用 diagnose
2. **混合意图处理**：如果用户同时提供反馈和查询（如"1确认，现在怎么样了"），返回多个 action: [diagnose, query_progress]
3. **首轮识别**：如果是会话首轮（rounds=0）且用户描述问题，使用 diagnose，将描述作为 new_observations
4. **模糊输入处理**：如果用户输入无法明确归类，倾向于 ask_clarification 而非猜测
5. **现象 ID 提取**：用户可能用序号（1、2、3）或 ID（P-0001）来指代现象，需要根据 pending_recommendations 转换
6. **上下文理解**：参考对话历史理解用户意图，如用户回复"第一个"可能是对上轮 ask_clarification 的回应

## 输出格式

必须输出 JSON，格式如下：
```json
{
  "actions": [
    {
      "action": "action_name",
      "parameters": { ... }
    }
  ],
  "reasoning": "决策理由的简要说明"
}
```

说明：
- actions 是数组，支持返回多个 action（按执行顺序排列）
- 大多数情况只需返回 1 个 action
- 当用户输入包含多个意图时，可以返回多个 action
````

#### User Prompt Template

```
## 会话状态

- 会话轮次: {rounds}
- 已确认现象: {confirmed_count} 个
- 已否认现象: {denied_count} 个
- 新观察数: {new_observation_count} 个
- 当前假设数: {hypotheses_count} 个
- 最可能根因: {top_hypothesis}
- 最高置信度: {top_confidence:.0%}
- 诊断状态: {status}

## 当前待确认的现象

{pending_recommendations_text}

## 最近对话历史

{dialogue_history}

## 用户输入

{user_input}

请分析用户意图并输出决策 JSON。
```

### 4.3 决策示例

#### 示例 1：常规反馈

```
会话状态: rounds=2, top_confidence=45%
待确认现象: [1] P-0001 wait_io高, [2] P-0002 索引增长, [3] P-0003 碎片率高
用户输入: "1确认 2确认 3没有"

输出:
{
  "actions": [
    {
      "action": "diagnose",
      "parameters": {
        "confirmations": ["P-0001", "P-0002"],
        "denials": ["P-0003"],
        "new_observations": []
      }
    }
  ],
  "reasoning": "用户对推荐的3个现象给出了明确反馈"
}
```

#### 示例 2：反馈 + 查询（多 Action）

```
用户输入: "1确认，现在进展怎么样了？"

输出:
{
  "actions": [
    {
      "action": "diagnose",
      "parameters": {
        "confirmations": ["P-0001"],
        "denials": [],
        "new_observations": []
      }
    },
    {
      "action": "query_progress",
      "parameters": {}
    }
  ],
  "reasoning": "用户确认了第一个现象，同时询问进展"
}
```

#### 示例 3：回应上轮澄清

```
## 最近对话历史

用户: 索引膨胀一般有什么表现？
系统 [ask_clarification]: 找到两个相关的根因，你问的是哪个？
  [1] RC-0001: 索引膨胀导致 IO 瓶颈
  [2] RC-0003: 索引膨胀导致查询计划变化

## 用户输入

第一个

---

输出:
{
  "actions": [
    {
      "action": "query_graph",
      "parameters": {
        "query_type": "root_cause_to_phenomena",
        "root_cause_id": "RC-0001"
      }
    }
  ],
  "reasoning": "用户选择了上轮澄清中的第一个选项，即 RC-0001"
}
```

#### 示例 4：模糊反馈需澄清

```
用户输入: "第一个好像有一点"

输出:
{
  "actions": [
    {
      "action": "ask_clarification",
      "parameters": {
        "clarification_type": "ambiguous_feedback",
        "context": "第一个好像有一点",
        "matched_entities": ["P-0001"]
      }
    }
  ],
  "reasoning": "用户对P-0001的反馈不明确，'好像有一点'无法判断是确认还是否认"
}
```

---

## 五、GAR2Core 设计

### 5.1 设计目标

从 `GAR2DialogueManager` 中抽取核心诊断算法，实现：

1. **无状态设计**：所有方法接收 session 状态，返回结果
2. **独立可测试**：可以单独对每个方法进行单元测试
3. **接口标准化**：输入输出使用 Action 接口定义的类型

### 5.2 接口定义

```python
class GAR2Core:
    """GAR2 核心诊断引擎

    无状态设计：所有方法接收 session 状态，返回结果和更新后的 session。
    """

    # 阈值常量
    HIGH_CONFIDENCE_THRESHOLD = 0.95
    MEDIUM_CONFIDENCE_THRESHOLD = 0.50
    RECOMMEND_TOP_N = 5

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        match_threshold: float = 0.75,
    ):
        """初始化核心引擎"""
        ...

    def diagnose(
        self,
        session: SessionStateV2,
        input: DiagnoseInput,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> tuple[DiagnoseOutput, SessionStateV2]:
        """执行诊断"""
        ...

    def query_progress(
        self,
        session: SessionStateV2,
        input: QueryProgressInput,
    ) -> QueryProgressOutput:
        """查询诊断进展"""
        ...

    def query_hypotheses(
        self,
        session: SessionStateV2,
        input: QueryHypothesesInput,
    ) -> QueryHypothesesOutput:
        """查询假设详情"""
        ...

    def query_graph(
        self,
        session: SessionStateV2,
        input: QueryGraphInput,
    ) -> QueryGraphOutput:
        """图谱查询"""
        ...

    def get_history(
        self,
        session: SessionStateV2,
        input: ShowHistoryInput,
    ) -> ShowHistoryOutput:
        """获取对话历史"""
        ...

    def generate_clarification(
        self,
        session: SessionStateV2,
        input: AskClarificationInput,
    ) -> AskClarificationOutput:
        """生成澄清问题"""
        ...
```

### 5.3 方法迁移映射

| 原方法 (GAR2DialogueManager) | 新位置 (GAR2Core) | 变化 |
|------------------------------|-------------------|------|
| `start_conversation()` | 移除 | Agent 层处理 |
| `continue_conversation()` | 移除 | Agent 层处理 |
| `_handle_confirmation()` | `_handle_confirmations()` | 批量处理 |
| `_handle_denial()` | `_handle_denials()` | 批量处理 |
| `_process_new_observations()` | `_process_new_observations()` | 返回 MatchResult |
| `_calculate_and_decide()` | 拆分 | `_calculate_hypotheses()` + `diagnose()` 决策 |
| `_generate_diagnosis()` | `_generate_diagnosis_info()` | 返回 DiagnosisInfo |
| `_generate_recommendation()` | `_generate_recommendations()` | 返回 List[RecommendationInfo] |
| `_generate_summary_response()` | 拆分 | `query_progress()`, `query_hypotheses()` |

### 5.4 SessionStateV2 扩展

```python
class DialogueHistoryItem(BaseModel):
    """对话历史条目"""
    role: Literal["user", "assistant"]
    content: str                          # 用户原文 或 系统响应摘要
    actions_taken: List[str] = []         # 本轮执行的 Action 列表（仅 assistant）
    action_results_summary: Optional[dict] = None  # Action 结果摘要（仅 assistant）
    timestamp: datetime = Field(default_factory=datetime.now)


class SessionStateV2(BaseModel):
    # ... 现有字段 ...

    # 新增：对话历史
    dialogue_history: List[DialogueHistoryItem] = Field(default_factory=list)

    # 新增：历史置信度（用于判断是否卡住）
    confidence_history: List[float] = Field(default_factory=list)

    def add_user_dialogue(self, content: str):
        """添加用户对话记录"""
        self.dialogue_history.append(DialogueHistoryItem(
            role="user",
            content=content,
        ))

    def add_assistant_dialogue(
        self,
        content: str,
        actions_taken: List[str],
        action_results_summary: Optional[dict] = None,
    ):
        """添加系统对话记录"""
        self.dialogue_history.append(DialogueHistoryItem(
            role="assistant",
            content=content,
            actions_taken=actions_taken,
            action_results_summary=action_results_summary,
        ))

    def record_confidence(self, confidence: float):
        """记录置信度历史"""
        self.confidence_history.append(confidence)

    def is_stuck(self, threshold: float = 0.05, lookback: int = 3) -> bool:
        """判断是否卡住（连续 N 轮置信度变化 < threshold）"""
        if len(self.confidence_history) < lookback:
            return False
        recent = self.confidence_history[-lookback:]
        return max(recent) - min(recent) < threshold

    def get_recent_dialogue_for_prompt(self, last_n: int = 3) -> str:
        """获取最近 N 轮对话，用于 AgentPlanner prompt"""
        recent = self.dialogue_history[-last_n * 2:]  # 每轮 2 条（user + assistant）

        lines = []
        for item in recent:
            if item.role == "user":
                lines.append(f"用户: {item.content}")
            else:
                summary = item.content[:100] + "..." if len(item.content) > 100 else item.content
                if item.actions_taken:
                    actions_str = ", ".join(item.actions_taken)
                    lines.append(f"系统 [{actions_str}]: {summary}")
                else:
                    lines.append(f"系统: {summary}")

        return "\n".join(lines) if lines else "（首轮对话）"
```

**对话历史示例**：

```python
# 用户轮
DialogueHistoryItem(
    role="user",
    content="1确认 2否定，现在进展如何？",
)

# 系统轮
DialogueHistoryItem(
    role="assistant",
    content="已更新诊断状态。当前最可能是索引膨胀（58%），已确认2个现象...",
    actions_taken=["diagnose", "query_progress"],
    action_results_summary={
        "diagnose": {"confirmed": 1, "denied": 1, "top_confidence": 0.58},
        "query_progress": {"status": "narrowing", "confirmed_count": 3},
    }
)
```

---

## 六、ActionExecutor 设计

### 6.1 职责

ActionExecutor 负责将 AgentPlanner 的决策路由到 GAR2Core 的具体方法。

### 6.2 执行策略

1. **执行顺序**：按 actions 数组顺序依次执行
2. **错误隔离**：单个 Action 失败不阻塞其他 Action
3. **Session 更新**：只有 `diagnose` 会修改 session，其他 Action 都是只读查询

### 6.3 接口设计

```python
class ActionExecutor:
    """Action 执行器

    职责：将 AgentPlanner 的决策路由到 GAR2Core 的具体方法
    """

    def __init__(self, core: GAR2Core):
        self.core = core

    def execute(
        self,
        session: SessionStateV2,
        decision: AgentDecision,
    ) -> tuple[List[dict], SessionStateV2]:
        """执行决策中的所有 Action

        执行策略：
        1. 按 actions 数组顺序依次执行
        2. diagnose 会修改 session，后续 Action 使用更新后的 session
        3. 单个 Action 失败不影响其他 Action 执行
        4. 返回所有 Action 的结果列表

        Returns:
            (结果列表, 最终的 session 状态)
        """
        results = []
        current_session = session

        for action_item in decision.actions:
            action = action_item["action"]
            params = action_item.get("parameters", {})

            try:
                result, current_session = self._execute_one(
                    current_session, action, params
                )
                results.append({
                    "action": action,
                    "result": result,
                    "success": True,
                })
            except Exception as e:
                results.append({
                    "action": action,
                    "error": str(e),
                    "success": False,
                })

        return results, current_session

    def _execute_one(
        self,
        session: SessionStateV2,
        action: str,
        params: dict,
    ) -> tuple[ActionResult, SessionStateV2]:
        """执行单个 Action"""

        if action == ActionType.DIAGNOSE:
            input = DiagnoseInput(**params)
            output, new_session = self.core.diagnose(session, input)
            return output, new_session

        elif action == ActionType.QUERY_PROGRESS:
            input = QueryProgressInput(**params)
            output = self.core.query_progress(session, input)
            return output, session  # 查询不修改 session

        elif action == ActionType.QUERY_HYPOTHESES:
            input = QueryHypothesesInput(**params)
            output = self.core.query_hypotheses(session, input)
            return output, session

        elif action == ActionType.QUERY_GRAPH:
            input = QueryGraphInput(**params)
            output = self.core.query_graph(session, input)
            return output, session

        elif action == ActionType.SHOW_HISTORY:
            input = ShowHistoryInput(**params)
            output = self.core.get_history(session, input)
            return output, session

        elif action == ActionType.ASK_CLARIFICATION:
            input = AskClarificationInput(**params)
            output = self.core.generate_clarification(session, input)
            return output, session

        else:
            raise ValueError(f"Unknown action: {action}")
```

### 6.4 对话历史管理

对话历史由 `AgenticGAR2DialogueManager`（最外层）管理，而不是 ActionExecutor：

```
用户输入
    │
    ▼
AgenticGAR2DialogueManager
    │
    ├─> 1. 记录用户输入到 dialogue_history
    │
    ├─> 2. 调用 AgentPlanner
    │
    ├─> 3. 调用 ActionExecutor
    │
    ├─> 4. 调用 ResponseRenderer
    │
    └─> 5. 记录系统响应到 dialogue_history
    │
    ▼
返回响应
```

**存储内容**：
- 用户侧：存原文（方便 AgentPlanner 理解上下文）
- 系统侧：存响应摘要 + Action 结果摘要（只存关键状态变化）

**传递给 AgentPlanner**：全量存在 session 里，但只传最近 3 轮

---

## 七、ResponseRenderer 设计

### 7.1 职责

ResponseRenderer 负责将 ActionExecutor 的结构化结果转换为自然语言响应。

### 7.2 设计决策

1. **使用 LLM 生成主体响应**：实现"像真人对话"的效果
2. **推荐现象包含完整信息**：描述、observation_method、推荐原因
3. **错误需明确说明**：什么失败了、原因、当前状况、建议
4. **附录仅 API 返回**：CLI/Web 暂不展示结构化详情

### 7.3 响应结构

```python
class AgenticGAR2Response(BaseModel):
    """AgenticGAR2 响应"""

    # 主体响应（自然语言，面向用户，包含完整信息）
    message: str

    # 结构化详情（仅 API 返回，CLI/Web 暂不展示）
    details: Optional[ResponseDetails] = None


class ResponseDetails(BaseModel):
    """响应详情（结构化数据，仅 API 返回）"""

    status: str
    top_hypothesis: Optional[str]
    top_confidence: float
    actions_executed: List[ActionSummary]
    recommendations: List[RecommendationInfo] = []
    diagnosis: Optional[DiagnosisInfo] = None
    errors: List[ActionError] = []


class ActionSummary(BaseModel):
    """Action 执行摘要"""
    action: str
    success: bool
    summary: str  # 一句话摘要


class ActionError(BaseModel):
    """Action 执行错误"""
    action: str
    error_message: str
```

### 7.4 Prompt 设计

```
你是一个数据库诊断助手。根据诊断结果生成自然、友好的响应。

## 要求

1. 用口语化的方式描述诊断进展和建议
2. 如果有推荐现象，必须包含完整信息：
   - 现象描述
   - 如何观察（observation_method）
   - 为什么推荐这个现象
3. 如果有 Action 执行失败，必须说明：
   - 什么操作执行不成功
   - 失败原因
   - 目前的状况是什么
   - 建议用户怎么做
4. 根据诊断状态调整语气：
   - exploring（早期）：鼓励用户继续提供信息
   - narrowing（缩小范围）：表达进展，引导确认关键现象
   - confirming（接近确认）：表达信心，但提醒还需确认
   - stuck（卡住）：委婉表达困难，建议换个方向
5. 如果有多个 Action 结果，自然地整合在一起

## 输出格式

直接输出响应文本。推荐现象用编号列表展示，每个现象包含描述、观察方法、推荐原因。
```

### 7.5 响应示例

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

## 八、会话管理

### 8.1 设计决策

1. **第一版保持内存会话**：和现有 GAR2 一致，简化实现
2. **超时策略**：
   - CLI：无需处理（用户主动退出）
   - Web API：30 分钟超时
3. **多会话并发**：Web API 通过 session_id 区分不同用户的会话

### 8.2 后续演进

会话持久化（存 DB）作为后续优化项，当前版本不实现。

---

## 九、与现有系统集成

### 9.1 CLI 集成

**方案**：改造现有 `GAR2CLI`，支持 AgenticGAR2 模式

```python
class GAR2CLI:
    def __init__(self, ..., use_gar2a: bool = True):
        """
        Args:
            use_gar2a: 是否使用 AgenticGAR2 模式，默认 True
        """
        if use_gar2a:
            self.dialogue_manager = AgenticGAR2DialogueManager(...)
        else:
            self.dialogue_manager = GAR2DialogueManager(...)  # 兼容旧模式
```

### 9.2 Web API 集成

**方案**：复用现有 `/chat` 端点，通过配置切换模式

```python
# 配置
gar2a:
  enabled: true  # 启用 AgenticGAR2 模式

# 路由保持不变
POST /chat
{
  "session_id": "xxx",
  "message": "用户输入"
}
```

### 9.3 配置项

```yaml
gar2a:
  enabled: true                      # 是否启用 AgenticGAR2 模式
  agent_model: "gpt-4"               # AgentPlanner 使用的模型
  response_model: "gpt-3.5-turbo"    # ResponseRenderer 使用的模型
  high_confidence_threshold: 0.95    # 诊断完成阈值
  stuck_detection_rounds: 3          # 卡住检测轮数
  session_timeout_minutes: 30        # 会话超时时间（Web API）
```

---

## 十、测试策略

### 10.1 GAR2Core 单元测试

构造固定的 session 状态和 input，验证 output：

```python
def test_diagnose_with_confirmations():
    """测试确认现象后的诊断"""
    core = GAR2Core(...)
    session = create_test_session(confirmed=["P-0001"])
    input = DiagnoseInput(confirmations=["P-0002"])

    output, new_session = core.diagnose(session, input)

    assert output.success
    assert len(new_session.symptom.observations) == 2
    assert output.hypotheses[0].confidence > 0
```

### 10.2 AgentPlanner 测试

Mock LLM 返回预设 JSON：

```python
def test_agent_planner_diagnose_intent():
    """测试识别诊断意图"""
    mock_llm = Mock()
    mock_llm.generate.return_value = '''
    {
      "actions": [{"action": "diagnose", "parameters": {"confirmations": ["P-0001"]}}],
      "reasoning": "用户确认了第一个现象"
    }
    '''

    planner = AgentPlanner(mock_llm)
    decision = planner.plan(session, "1确认")

    assert decision.actions[0]["action"] == "diagnose"
    assert "P-0001" in decision.actions[0]["parameters"]["confirmations"]
```

### 10.3 E2E 测试场景

| 场景 | 描述 | 验证点 |
|------|------|--------|
| 正常诊断流程 | 用户描述问题 → 确认现象 → 得出结论 | 置信度递增，最终诊断正确 |
| 查询进展 | 用户中途询问"现在怎么样了" | 返回正确的状态摘要 |
| 混合意图 | "1确认，现在进展如何？" | 两个 Action 都执行 |
| 澄清流程 | 用户输入模糊 → 系统澄清 → 用户回应 | 正确理解澄清后的回应 |
| 错误处理 | 某个 Action 失败 | 响应中包含错误说明和建议 |

---

## 十一、实施计划

### 阶段一：核心抽取

1. 创建 `dbdiag/core/gar2a/actions.py` - Action 接口定义
2. 创建 `dbdiag/core/gar2/core.py` - GAR2Core 实现
3. 更新 `dbdiag/core/gar2/models.py` - 扩展 SessionStateV2
4. 编写 GAR2Core 单元测试

### 阶段二：Agent 层实现

1. 创建 `dbdiag/core/gar2a/agent_planner.py` - AgentPlanner
2. 创建 `dbdiag/core/gar2a/action_executor.py` - ActionExecutor
3. 创建 `dbdiag/core/gar2a/response_renderer.py` - ResponseRenderer
4. 创建 `dbdiag/core/gar2a/dialogue_manager.py` - AgenticGAR2DialogueManager

### 阶段三：集成与测试

1. 改造 `GAR2CLI`，支持 AgenticGAR2 模式
2. Web API 复用 `/chat` 端点，通过配置切换
3. 端到端测试
4. 文档更新

---

## 附录

### A. 与现有架构对比

| 维度 | GAR2（现有） | AgenticGAR2（新） |
|------|-------------|-----------|
| 意图理解 | IntentClassifier（3 种意图） | AgentPlanner（6+ 种 Action） |
| 决策逻辑 | 硬编码在 DialogueManager | LLM 动态决策 |
| 核心算法 | 耦合在 DialogueManager | 独立的 GAR2Core |
| 响应生成 | 返回结构化 dict | 自然语言 + 结构化附录 |
| 可扩展性 | 需改代码添加新功能 | 添加新 Action 即可 |

### B. 术语表

| 术语 | 说明 |
|------|------|
| AgenticGAR2 | Agent-enhanced GAR，本设计的系统名称 |
| Action | Agent 可执行的原子操作，如 diagnose、query_progress |
| AgentPlanner | LLM 驱动的决策层，决定执行什么 Action |
| GAR2Core | 核心诊断算法引擎，无状态，确定性 |
| ActionExecutor | Action 路由层，将决策分发到具体实现 |
| ResponseRenderer | 响应生成层，将结构化结果转为自然语言 |
