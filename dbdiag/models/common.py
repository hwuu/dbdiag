"""共享领域模型

本模块定义所有方法共享的领域模型：
- Ticket: 工单
- RootCause: 根因
- RawAnomaly: 原始异常
- Phenomenon: 标准现象
- TicketAnomaly: 工单-现象关联
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


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
