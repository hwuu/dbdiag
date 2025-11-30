"""数据模型模块

组织结构：
- common: 共享领域模型 (Ticket, RootCause, Phenomenon, etc.)
- gar: GAR 会话模型 (SessionState, Hypothesis, etc.)
- rar: RAR 会话模型 (RARSessionState)
"""
# 共享领域模型
from dbdiag.models.common import (
    Ticket,
    RootCause,
    RawAnomaly,
    Phenomenon,
    TicketAnomaly,
)

# GAR 会话模型
from dbdiag.models.gar import (
    Hypothesis,
    ConfirmedPhenomenon,
    DeniedPhenomenon,
    RecommendedPhenomenon,
    DialogueMessage,
    SessionState,
)

# RAR 会话模型
from dbdiag.models.rar import RARSessionState

__all__ = [
    # 共享模型
    "Ticket",
    "RootCause",
    "RawAnomaly",
    "Phenomenon",
    "TicketAnomaly",
    # GAR 模型
    "Hypothesis",
    "ConfirmedPhenomenon",
    "DeniedPhenomenon",
    "RecommendedPhenomenon",
    "DialogueMessage",
    "SessionState",
    # RAR 模型
    "RARSessionState",
]
