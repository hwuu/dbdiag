"""诊断步骤数据模型

DEPRECATED: 此模块已废弃，请使用 dbdiag.models.phenomenon 中的 Phenomenon 类。
V2 架构使用 phenomenon-based 检索替代 step-based 检索。
"""
import warnings
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class DiagnosticStep(BaseModel):
    """诊断步骤

    DEPRECATED: 此类已废弃，请使用 dbdiag.models.phenomenon.Phenomenon。

    V2 架构变更：
    - DiagnosticStep → Phenomenon
    - step_id → phenomenon_id
    - observed_fact → description
    - observation_method → observation_method (保留)

    迁移指南：
        # V1 (deprecated)
        from dbdiag.models.step import DiagnosticStep

        # V2 (recommended)
        from dbdiag.models.phenomenon import Phenomenon
    """

    model_config = ConfigDict(from_attributes=True)

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

    def __init__(self, **data):
        warnings.warn(
            "DiagnosticStep is deprecated. Use dbdiag.models.phenomenon.Phenomenon instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(**data)
