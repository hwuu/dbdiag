"""现象数据模型

本模块定义了 V2 架构中的核心数据模型：
- RawAnomaly: 原始异常（专家标注的原始数据）
- Phenomenon: 标准现象（聚类后的标准化现象）
- TicketAnomaly: 工单-现象关联
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class RawAnomaly(BaseModel):
    """原始异常

    存储专家标注的原始异常描述，在 import 时导入到 raw_anomalies 表。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str  # 格式: {ticket_id}_anomaly_{index}
    ticket_id: str
    anomaly_index: int  # 异常在工单中的序号

    # 异常内容
    description: str  # 原始异常描述
    observation_method: str  # 原始观察方法
    why_relevant: str  # 原始相关性解释

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now)


class Phenomenon(BaseModel):
    """标准现象

    聚类去重后的标准化现象，在 rebuild-index 时生成。
    """

    model_config = ConfigDict(from_attributes=True)

    phenomenon_id: str  # 格式: P-{序号}，如 P-0001
    description: str  # 标准化描述（LLM 生成）
    observation_method: str  # 标准观察方法（选最佳）

    # 溯源信息
    source_anomaly_ids: List[str]  # 来源的原始 anomaly IDs
    cluster_size: int  # 聚类中的异常数量

    # 向量（可选，检索时填充）
    embedding: Optional[List[float]] = None

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now)


class TicketAnomaly(BaseModel):
    """工单-现象关联

    记录工单与标准现象的关联关系，以及该工单上下文中的相关性解释。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str  # 格式: {ticket_id}_anomaly_{index}
    ticket_id: str
    phenomenon_id: str  # 关联的标准现象

    # 上下文相关性
    why_relevant: str  # 该工单上下文中的相关性解释

    # 溯源（可选）
    raw_anomaly_id: Optional[str] = None  # 关联的原始异常ID
