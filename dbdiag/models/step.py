"""诊断步骤数据模型"""
from typing import Optional, List
from pydantic import BaseModel


class DiagnosticStep(BaseModel):
    """诊断步骤"""

    step_id: str
    ticket_id: str
    step_index: int

    # 步骤内容
    observed_fact: str
    observation_method: str
    analysis_result: str

    # 冗余字段
    ticket_description: str
    ticket_root_cause: str

    # 向量（可选，检索时填充）
    fact_embedding: Optional[List[float]] = None
    method_embedding: Optional[List[float]] = None

    class Config:
        from_attributes = True
