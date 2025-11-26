"""会话状态数据模型"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class ConfirmedFact(BaseModel):
    """已确认的事实"""

    fact: str
    from_user_input: bool  # True: 用户提供, False: 系统观察
    step_id: Optional[str] = None
    observation_result: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class Hypothesis(BaseModel):
    """根因假设"""

    root_cause: str
    confidence: float  # 0-1 之间
    supporting_step_ids: List[str]  # V1 字段，保留兼容
    missing_facts: List[str]
    next_recommended_step_id: Optional[str] = None  # V1 字段，保留兼容

    # V2 新增字段
    supporting_phenomenon_ids: List[str] = []  # 支持该假设的现象 ID 列表
    supporting_ticket_ids: List[str] = []  # 支持该假设的工单 ID 列表
    next_recommended_phenomenon_id: Optional[str] = None  # 下一个推荐观察的现象


class ExecutedStep(BaseModel):
    """已执行的步骤

    DEPRECATED: V2 架构中请使用 ConfirmedPhenomenon
    """

    step_id: str
    executed_at: datetime = Field(default_factory=datetime.now)
    result_summary: str


class ConfirmedPhenomenon(BaseModel):
    """已确认的现象 (V2 新增)

    用于追踪用户已执行观察并确认的现象。
    """

    phenomenon_id: str
    confirmed_at: datetime = Field(default_factory=datetime.now)
    result_summary: str  # 用户反馈的观察结果


class DialogueMessage(BaseModel):
    """对话消息"""

    role: str  # "user" 或 "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class SessionState(BaseModel):
    """会话状态"""

    session_id: str
    user_problem: str
    created_at: datetime = Field(default_factory=datetime.now)

    # 状态数据
    confirmed_facts: List[ConfirmedFact] = []
    active_hypotheses: List[Hypothesis] = []
    executed_steps: List[ExecutedStep] = []  # V1 字段，保留兼容
    recommended_step_ids: List[str] = []  # V1 字段，保留兼容
    dialogue_history: List[DialogueMessage] = []

    # V2 新增字段
    confirmed_phenomena: List[ConfirmedPhenomenon] = []  # 已确认的现象列表
    recommended_phenomenon_ids: List[str] = []  # 已推荐过的现象 ID（避免重复推荐）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return self.model_dump(mode='json')

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        """从字典创建（用于 JSON 反序列化）"""
        return cls(**data)
