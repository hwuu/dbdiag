"""会话管理 API 接口"""
from fastapi import APIRouter, HTTPException
from pathlib import Path

from dbdiag.core.dialogue_manager import PhenomenonDialogueManager
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.config import load_config

# 创建路由
router = APIRouter()

# 初始化单例服务
config = load_config()
llm_service = LLMService(config)
embedding_service = EmbeddingService(config)

# 初始化对话管理器 (V2)
db_path = str(Path("data") / "tickets.db")
dialogue_manager = PhenomenonDialogueManager(db_path, llm_service, embedding_service)


@router.get("/sessions")
async def list_sessions(limit: int = 10):
    """
    列出最近的会话

    返回最近的对话会话列表，包含会话 ID、问题描述和创建时间等信息。
    """
    try:
        sessions = dialogue_manager.list_sessions(limit)
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """
    获取会话详情

    获取指定会话的详细信息，包括假设数量、对话轮次等。
    """
    try:
        session = dialogue_manager.get_session(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
