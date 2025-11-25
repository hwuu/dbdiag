"""工单数据模型"""
from typing import Dict, Any
from pydantic import BaseModel


class Ticket(BaseModel):
    """工单"""

    ticket_id: str
    metadata: Dict[str, Any]  # {"db_type": "...", "version": "...", ...}
    description: str
    root_cause: str
    solution: str

    class Config:
        from_attributes = True
