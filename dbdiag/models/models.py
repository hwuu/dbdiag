"""数据模型

本模块统一定义所有数据模型，包括：
- 领域模型：Ticket, Phenomenon, RawAnomaly, TicketAnomaly, RootCause
- 会话模型：SessionState, Hypothesis, ConfirmedPhenomenon, DeniedPhenomenon, RecommendedPhenomenon, DialogueMessage
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# 领域模型
# ============================================


class Ticket(BaseModel):
    """工单"""

    model_config = ConfigDict(from_attributes=True)

    ticket_id: str
    metadata: Dict[str, Any]
    description: str
    root_cause_id: Optional[str] = None
    root_cause: str
    solution: str


class RootCause(BaseModel):
    """根因"""

    model_config = ConfigDict(from_attributes=True)

    root_cause_id: str
    description: str
    solution: Optional[str] = None
    key_phenomenon_ids: List[str] = []
    related_ticket_ids: List[str] = []
    ticket_count: int = 0
    embedding: Optional[List[float]] = None


class RawAnomaly(BaseModel):
    """原始异常"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    ticket_id: str
    anomaly_index: int
    description: str
    observation_method: str
    why_relevant: str
    created_at: datetime = Field(default_factory=datetime.now)


class Phenomenon(BaseModel):
    """标准现象"""

    model_config = ConfigDict(from_attributes=True)

    phenomenon_id: str
    description: str
    observation_method: str
    source_anomaly_ids: List[str]
    cluster_size: int
    embedding: Optional[List[float]] = None
    created_at: datetime = Field(default_factory=datetime.now)


class TicketAnomaly(BaseModel):
    """工单-现象关联"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    ticket_id: str
    phenomenon_id: str
    why_relevant: str
    raw_anomaly_id: Optional[str] = None


# ============================================
# 会话模型
# ============================================


class Hypothesis(BaseModel):
    """根因假设"""

    root_cause_id: str
    confidence: float
    missing_phenomena: List[str] = []
    supporting_phenomenon_ids: List[str] = []
    supporting_ticket_ids: List[str] = []
    next_recommended_phenomenon_id: Optional[str] = None


class ConfirmedPhenomenon(BaseModel):
    """已确认的现象"""

    phenomenon_id: str
    confirmed_at: datetime = Field(default_factory=datetime.now)
    result_summary: str


class DeniedPhenomenon(BaseModel):
    """被否定的现象"""

    phenomenon_id: str
    denied_at: datetime = Field(default_factory=datetime.now)
    reason: Optional[str] = None


class RecommendedPhenomenon(BaseModel):
    """已推荐的现象"""

    phenomenon_id: str
    recommended_at: datetime = Field(default_factory=datetime.now)
    round_number: int


class DialogueMessage(BaseModel):
    """对话消息"""

    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class SessionState(BaseModel):
    """会话状态"""

    session_id: str
    user_problem: str
    created_at: datetime = Field(default_factory=datetime.now)

    active_hypotheses: List[Hypothesis] = []
    dialogue_history: List[DialogueMessage] = []

    confirmed_phenomena: List[ConfirmedPhenomenon] = []
    denied_phenomena: List[DeniedPhenomenon] = []
    recommended_phenomena: List[RecommendedPhenomenon] = []

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        return cls(**data)

    @property
    def denied_phenomenon_ids(self) -> List[str]:
        return [p.phenomenon_id for p in self.denied_phenomena]

    @property
    def recommended_phenomenon_ids(self) -> List[str]:
        return [p.phenomenon_id for p in self.recommended_phenomena]
