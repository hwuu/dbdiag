"""聊天 API 接口"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path

from app.core.dialogue_manager import DialogueManager
from app.utils.config import load_config

# 创建路由
router = APIRouter()

# 初始化对话管理器
config = load_config()
db_path = str(Path("data") / "tickets.db")
dialogue_manager = DialogueManager(db_path, config)


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
    """
    try:
        response = dialogue_manager.start_conversation(request.user_problem)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/continue")
async def continue_chat(request: ChatContinueRequest):
    """
    继续对话

    在现有会话中继续对话，系统会根据用户反馈更新假设并推荐下一步操作。
    """
    try:
        response = dialogue_manager.continue_conversation(
            request.session_id, request.user_message
        )

        if "error" in response:
            raise HTTPException(status_code=404, detail=response["error"])

        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
