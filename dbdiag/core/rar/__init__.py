"""RAR (Retrieval-Augmented-Reasoning) 检索增强推理方法

使用 RAG + LLM 进行端到端诊断推理的核心模块（实验性）。
"""
from dbdiag.core.rar.dialogue_manager import RARDialogueManager
from dbdiag.core.rar.retriever import RARRetriever, RARTicket
from dbdiag.models.rar import RARSessionState

__all__ = [
    "RARDialogueManager",
    "RARRetriever",
    "RARTicket",
    "RARSessionState",
]
