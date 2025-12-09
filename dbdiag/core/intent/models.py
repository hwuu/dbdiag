"""意图识别数据模型

定义用户意图的数据结构。
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """意图类型"""
    FEEDBACK = "feedback"      # I-101: 诊断反馈
    QUERY = "query"            # I-102: 系统查询
    MIXED = "mixed"            # 混合意图


class QueryType(str, Enum):
    """查询子类型"""
    PROGRESS = "progress"      # 查询诊断进展（检查了什么）
    CONCLUSION = "conclusion"  # 查询当前结论（有什么结论）
    HYPOTHESES = "hypotheses"  # 查询假设列表（还有哪些可能）


class UserIntent(BaseModel):
    """用户意图

    表示解析后的用户意图，包含：
    - 意图类型（feedback/query/mixed）
    - 反馈内容（确认、否认、新观察）
    - 查询类型（progress/conclusion/hypotheses）

    Attributes:
        intent_type: 意图类型
        confirmations: 确认的现象 ID 列表
        denials: 否认的现象 ID 列表
        new_observations: 新观察列表（支持多个，对应 I-303）
        query_type: 查询子类型（仅 query/mixed 时有效）
        confidence: LLM 分类置信度
    """

    intent_type: IntentType = Field(
        default=IntentType.FEEDBACK,
        description="意图类型"
    )

    # I-101 feedback 内容
    confirmations: List[str] = Field(
        default_factory=list,
        description="确认的现象 ID 列表"
    )
    denials: List[str] = Field(
        default_factory=list,
        description="否认的现象 ID 列表"
    )
    new_observations: List[str] = Field(
        default_factory=list,
        description="新观察列表（支持多个）"
    )

    # I-102 query 内容
    query_type: Optional[QueryType] = Field(
        default=None,
        description="查询子类型"
    )

    # 元信息
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="LLM 分类置信度"
    )

    @property
    def has_feedback(self) -> bool:
        """是否包含反馈内容"""
        return bool(self.confirmations or self.denials or self.new_observations)

    @property
    def has_query(self) -> bool:
        """是否包含查询"""
        return self.query_type is not None

    @property
    def is_empty(self) -> bool:
        """是否为空（无任何有效内容）"""
        return not self.has_feedback and not self.has_query
