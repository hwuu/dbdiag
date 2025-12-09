"""聊天 API 接口

支持 GAR2 诊断算法。
"""
from typing import Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dbdiag.core.gar2.dialogue_manager import GAR2DialogueManager
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.config import load_config
from dbdiag.dao.base import get_default_db_path

# 创建路由
router = APIRouter()

# 初始化单例服务
_config = load_config()
_llm_service = LLMService(_config)
_embedding_service = EmbeddingService(_config)
_db_path = get_default_db_path()

# 会话管理器映射: session_id -> GAR2DialogueManager
_session_managers: Dict[str, GAR2DialogueManager] = {}


def _create_dialogue_manager() -> GAR2DialogueManager:
    """创建新的对话管理器"""
    return GAR2DialogueManager(
        _db_path,
        _llm_service,
        _embedding_service,
        match_threshold=_config.recommender.match_threshold,
    )


class ChatStartRequest(BaseModel):
    """开始对话请求"""

    user_problem: str


class ChatContinueRequest(BaseModel):
    """继续对话请求"""

    session_id: str
    user_message: str


@router.post("/chat/start")
async def start_chat(request: ChatStartRequest):
    """
    开始新对话

    开始一个新的诊断会话，系统会根据用户问题生成初始假设并推荐第一步诊断操作。

    Returns:
        响应包含:
        - session_id: 会话 ID
        - action: 动作类型 (recommend/diagnose/guide/ask_more_info)
        - 其他字段根据 action 类型不同而变化
    """
    try:
        # 创建新的对话管理器
        dialogue_manager = _create_dialogue_manager()

        # 开始对话
        response = dialogue_manager.start_conversation(request.user_problem)

        # 获取 session_id
        session = response.get("session")
        if session:
            session_id = session.session_id
            # 存储对话管理器
            _session_managers[session_id] = dialogue_manager
            # 移除 session 对象（不可序列化），添加 session_id
            del response["session"]
            response["session_id"] = session_id

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/continue")
async def continue_chat(request: ChatContinueRequest):
    """
    继续对话

    在现有会话中继续对话，系统会根据用户反馈更新假设并推荐下一步操作。

    Returns:
        响应包含:
        - session_id: 会话 ID
        - action: 动作类型 (recommend/diagnose/summary/guide/ask_more_info)
        - 其他字段根据 action 类型不同而变化
    """
    try:
        # 获取对话管理器
        dialogue_manager = _session_managers.get(request.session_id)
        if not dialogue_manager:
            raise HTTPException(status_code=404, detail="会话不存在或已过期")

        # 继续对话
        response = dialogue_manager.continue_conversation(request.user_message)

        # 处理 session 对象
        session = response.get("session")
        if session:
            del response["session"]
            response["session_id"] = request.session_id

        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/chat/{session_id}")
async def end_chat(session_id: str):
    """
    结束对话

    结束指定的诊断会话，释放资源。
    """
    if session_id in _session_managers:
        del _session_managers[session_id]
        return {"message": "会话已结束", "session_id": session_id}
    else:
        raise HTTPException(status_code=404, detail="会话不存在")
