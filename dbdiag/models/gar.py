"""GAR (图谱增强推理) 会话模型

本模块定义 GAR 方法的会话状态相关模型：
- SessionState: 会话状态
- Hypothesis: 根因假设
- ConfirmedPhenomenon: 已确认现象
- DeniedPhenomenon: 已否定现象
- RecommendedPhenomenon: 已推荐现象
- DialogueMessage: 对话消息
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


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
    """GAR 会话状态"""

    session_id: str
    user_problem: str
    created_at: datetime = Field(default_factory=datetime.now)

    active_hypotheses: List[Hypothesis] = []
    dialogue_history: List[DialogueMessage] = []

    confirmed_phenomena: List[ConfirmedPhenomenon] = []
    denied_phenomena: List[DeniedPhenomenon] = []
    recommended_phenomena: List[RecommendedPhenomenon] = []

    # 混合模式：来自相似工单的候选现象 ID
    hybrid_candidate_phenomenon_ids: List[str] = []

    # 用户描述的新观察（不在待确认列表中的）
    new_observations: List[str] = []

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
