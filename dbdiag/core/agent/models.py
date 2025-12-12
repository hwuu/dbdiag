"""Agent 数据模型

Tool 输入输出的数据模型定义。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Set, Literal

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# 基础模型
# ============================================================

class ToolOutput(BaseModel):
    """Tool 执行结果的基类"""
    success: bool = True
    error_message: Optional[str] = None


# ============================================================
# 会话状态
# ============================================================

class ConfirmedObservation(BaseModel):
    """已确认的观察"""
    phenomenon_id: str
    phenomenon_description: str
    user_observation: str
    match_score: float = Field(ge=0, le=1)
    confirmed_at: datetime = Field(default_factory=datetime.now)


class SessionState(BaseModel):
    """Agent 会话状态

    Attributes:
        session_id: 会话 ID
        user_problem: 用户问题描述
        confirmed_observations: 已确认的观察列表
        denied_phenomenon_ids: 被否认的现象 ID 集合
        hypotheses: 当前假设列表（按置信度排序）
        recommendations: 当前推荐的现象列表
        rounds: 已进行轮次
        created_at: 会话创建时间
        updated_at: 会话更新时间
    """
    session_id: str
    user_problem: str = ""
    confirmed_observations: List[ConfirmedObservation] = Field(default_factory=list)
    denied_phenomenon_ids: Set[str] = Field(default_factory=set)
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)
    rounds: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def top_hypothesis(self) -> Optional[Hypothesis]:
        """获取置信度最高的假设"""
        if self.hypotheses:
            return self.hypotheses[0]
        return None

    @property
    def confirmed_count(self) -> int:
        """已确认现象数"""
        return len(self.confirmed_observations)

    @property
    def denied_count(self) -> int:
        """已否认现象数"""
        return len(self.denied_phenomenon_ids)

    def is_phenomenon_denied(self, phenomenon_id: str) -> bool:
        """检查现象是否被否认"""
        return phenomenon_id in self.denied_phenomenon_ids

    def get_confirmed_phenomenon_ids(self) -> Set[str]:
        """获取所有已确认的现象 ID"""
        return {obs.phenomenon_id for obs in self.confirmed_observations}


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
        default_factory=list,
        description="解释结果列表，每个原始描述对应一个"
    )
    all_matched: bool = Field(
        default=False,
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
    observed_phenomena: List[str] = Field(
        default_factory=list,
        description="观察到的现象描述"
    )
    solution: str = ""
    reference_tickets: List[str] = Field(
        default_factory=list,
        description="参考工单 ID"
    )
    reasoning: str = Field(default="", description="推导过程说明")


class DiagnoseOutput(ToolOutput):
    """诊断工具的输出"""
    diagnosis_complete: bool = Field(
        default=False,
        description="是否完成诊断（置信度达阈值）"
    )
    hypotheses: List[Hypothesis] = Field(
        default_factory=list,
        description="假设列表，按置信度排序"
    )
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
    rounds: int = Field(default=0, description="已进行轮次")
    confirmed_count: int = Field(default=0, description="已确认现象数")
    denied_count: int = Field(default=0, description="已否认现象数")
    hypotheses_count: int = Field(default=0, description="当前假设数")
    top_hypothesis: Optional[str] = Field(
        default=None,
        description="最可能的根因描述"
    )
    top_confidence: float = Field(default=0.0, description="最高置信度")
    status: Literal["exploring", "narrowing", "confirming", "stuck"] = Field(
        default="exploring",
        description="诊断状态"
    )
    status_description: str = Field(default="", description="状态的自然语言描述")


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
    contributing_phenomena: List[str] = Field(
        default_factory=list,
        description="贡献的现象 ID"
    )
    missing_phenomena: List[str] = Field(
        default_factory=list,
        description="尚未确认但相关的现象描述"
    )
    related_tickets: List[str] = Field(
        default_factory=list,
        description="相关工单 ID"
    )


class QueryHypothesesOutput(ToolOutput):
    """查询假设的输出"""
    hypotheses: List[HypothesisDetail] = Field(default_factory=list)
    total_count: int = Field(default=0, description="假设总数")


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
    supporting_ticket_count: int = 0


class QueryRelationsOutput(ToolOutput):
    """图谱查询的输出"""
    query_type: str = ""
    source_entity_id: str = ""
    source_entity_description: str = ""
    results: List[GraphRelation] = Field(default_factory=list)


# ============================================================
# Responder 模型
# ============================================================

class CallResult(BaseModel):
    """工具调用结果"""
    tool: str
    success: bool
    summary: str


class CallError(BaseModel):
    """工具调用错误"""
    tool: str
    error_message: str


class ResponseDetails(BaseModel):
    """响应详情（结构化数据，仅 API 返回）"""
    status: str = ""
    top_hypothesis: Optional[str] = None
    top_confidence: float = 0.0
    call_results: List[CallResult] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)
    diagnosis: Optional[Diagnosis] = None
    call_errors: List[CallError] = Field(default_factory=list)
    clarifications: List[InterpretedObservation] = Field(
        default_factory=list,
        description="需要澄清的观察列表（CLI 用于渲染）"
    )


class AgentResponse(BaseModel):
    """Agent 响应"""
    message: str = Field(description="主体响应（自然语言，面向用户）")
    details: Optional[ResponseDetails] = Field(
        default=None,
        description="结构化详情（仅 API 返回）"
    )


# ============================================================
# Planner 模型
# ============================================================

class AgentDecision(BaseModel):
    """Planner 决策结果"""
    decision: Literal["call", "respond"] = Field(
        description="决策类型：call 调用工具，respond 直接回复"
    )
    tool: Optional[str] = Field(
        default=None,
        description="工具名（当 decision=call 时）"
    )
    tool_input: Optional[dict] = Field(
        default=None,
        description="工具输入参数（当 decision=call 时）"
    )
    response_context: Optional[dict] = Field(
        default=None,
        description="响应上下文（当 decision=respond 时，传给 Responder）"
    )
    reasoning: str = Field(default="", description="决策理由")


# ============================================================
# 解决前向引用
# ============================================================

# 由于 SessionState 引用了 Hypothesis 和 Recommendation（在其后定义），
# 需要在所有类定义完成后重建模型
SessionState.model_rebuild()
