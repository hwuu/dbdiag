"""工单数据模型"""
from typing import Dict, Any
from pydantic import BaseModel, ConfigDict


class Ticket(BaseModel):
    """工单"""

    model_config = ConfigDict(from_attributes=True)

    ticket_id: str
    metadata: Dict[str, Any]  # {"db_type": "...", "version": "...", ...}
    description: str
    root_cause: str
    solution: str
