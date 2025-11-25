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
    supporting_step_ids: List[str]
    missing_facts: List[str]
    next_recommended_step_id: Optional[str] = None


class ExecutedStep(BaseModel):
    """已执行的步骤"""

    step_id: str
    executed_at: datetime = Field(default_factory=datetime.now)
    result_summary: str


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
    executed_steps: List[ExecutedStep] = []
    recommended_step_ids: List[str] = []  # 已推荐过的步骤 ID（避免重复推荐）
    dialogue_history: List[DialogueMessage] = []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return self.model_dump(mode='json')

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        """从字典创建（用于 JSON 反序列化）"""
        return cls(**data)
