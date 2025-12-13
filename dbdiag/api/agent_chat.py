"""Agent 聊天 API 接口

支持 Agent Loop 诊断模式。
"""
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from dbdiag.core.agent import AgentDialogueManager, AgentResponse
from dbdiag.core.agent.stream_models import StreamMessageType
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

# 会话管理器映射: session_id -> AgentDialogueManager
_agent_session_managers: Dict[str, AgentDialogueManager] = {}


def _create_agent_dialogue_manager() -> AgentDialogueManager:
    """创建新的 Agent 对话管理器"""
    return AgentDialogueManager(
        _db_path,
        _llm_service,
        _embedding_service,
    )


def _serialize_agent_response(response: AgentResponse, session_id: str) -> dict:
    """序列化 AgentResponse 为 dict

    Args:
        response: AgentResponse 对象
        session_id: 会话 ID

    Returns:
        可序列化的 dict
    """
    result = {
        "session_id": session_id,
        "message": response.message,
    }

    if response.details:
        details = {}

        # 诊断结果
        if response.details.diagnosis:
            diag = response.details.diagnosis
            details["diagnosis"] = {
                "root_cause_id": diag.root_cause_id,
                "root_cause_description": diag.root_cause_description,
                "confidence": diag.confidence,
                "observed_phenomena": diag.observed_phenomena,
                "reasoning": diag.reasoning,
                "solution": diag.solution,
                "reference_tickets": diag.reference_tickets,
            }

        # 推荐
        if response.details.recommendations:
            details["recommendations"] = [
                {
                    "phenomenon_id": rec.phenomenon_id,
                    "description": rec.description,
                    "observation_method": rec.observation_method,
                    "reason": rec.reason,
                }
                for rec in response.details.recommendations
            ]

        # 澄清选项
        if response.details.clarification_options:
            details["clarification_options"] = [
                {
                    "phenomenon_id": opt.phenomenon_id,
                    "description": opt.description,
                    "observation_method": opt.observation_method,
                }
                for opt in response.details.clarification_options
            ]

        # 假设
        if response.details.hypotheses:
            details["hypotheses"] = [
                {
                    "root_cause_id": hyp.root_cause_id,
                    "root_cause_description": hyp.root_cause_description,
                    "confidence": hyp.confidence,
                }
                for hyp in response.details.hypotheses
            ]

        if details:
            result["details"] = details

    return result


class AgentChatStartRequest(BaseModel):
    """开始 Agent 对话请求"""

    user_problem: str


class AgentChatContinueRequest(BaseModel):
    """继续 Agent 对话请求"""

    session_id: str
    user_message: str


@router.post("/agent/chat/start")
async def start_agent_chat(request: AgentChatStartRequest):
    """
    开始新的 Agent 对话

    开始一个新的 Agent 诊断会话。

    Returns:
        响应包含:
        - session_id: 会话 ID
        - message: 助手响应消息
        - details: 可选，包含推荐、假设等信息
    """
    try:
        # 创建新的对话管理器
        dialogue_manager = _create_agent_dialogue_manager()

        # 创建会话
        session_id = dialogue_manager.create_session(request.user_problem)

        # 存储对话管理器
        _agent_session_managers[session_id] = dialogue_manager

        # 处理用户输入
        response = dialogue_manager.process_input(session_id, request.user_problem)

        return _serialize_agent_response(response, session_id)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/chat/continue")
async def continue_agent_chat(request: AgentChatContinueRequest):
    """
    继续 Agent 对话

    在现有 Agent 会话中继续对话。

    Returns:
        响应包含:
        - session_id: 会话 ID
        - message: 助手响应消息
        - details: 可选，包含推荐、诊断结果、假设等信息
    """
    try:
        # 获取对话管理器
        dialogue_manager = _agent_session_managers.get(request.session_id)
        if not dialogue_manager:
            raise HTTPException(status_code=404, detail="会话不存在或已过期")

        # 继续对话
        response = dialogue_manager.process_input(
            request.session_id, request.user_message
        )

        return _serialize_agent_response(response, request.session_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent/sessions/{session_id}")
async def get_agent_session(session_id: str):
    """
    获取 Agent 会话详情

    获取指定 Agent 会话的详细信息。
    """
    dialogue_manager = _agent_session_managers.get(session_id)
    if not dialogue_manager:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    session = dialogue_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话状态异常")

    # 构建响应
    return {
        "session_id": session_id,
        "user_problem": session.user_problem,
        "confirmed_count": session.confirmed_count,
        "denied_count": session.denied_count,
        "observations": [
            {
                "phenomenon_id": obs.phenomenon_id,
                "description": obs.description,
                "matched_phenomenon_ids": obs.matched_phenomenon_ids,
                "is_confirmed": obs.is_confirmed,
            }
            for obs in session.observations
        ],
        "denied_phenomena": list(session.denied_phenomena),
        "hypotheses": [
            {
                "root_cause_id": hyp.root_cause_id,
                "root_cause_description": hyp.root_cause_description,
                "confidence": hyp.confidence,
            }
            for hyp in session.hypotheses
        ],
        "recommendations": [
            {
                "phenomenon_id": rec.phenomenon_id,
                "description": rec.description,
                "observation_method": rec.observation_method,
                "reason": rec.reason,
            }
            for rec in session.recommendations
        ],
    }


@router.delete("/agent/chat/{session_id}")
async def end_agent_chat(session_id: str):
    """
    结束 Agent 对话

    结束指定的 Agent 诊断会话，释放资源。
    """
    if session_id in _agent_session_managers:
        del _agent_session_managers[session_id]
        return {"message": "会话已结束", "session_id": session_id}
    else:
        raise HTTPException(status_code=404, detail="会话不存在")


# ============================================================
# WebSocket 流式端点
# ============================================================


@router.websocket("/agent/ws/chat")
async def agent_websocket_chat(websocket: WebSocket):
    """Agent 流式 WebSocket 聊天端点

    协议：
    1. 客户端发送消息:
       {"type": "start", "user_problem": "问题描述"}   -- 开始新会话
       {"type": "continue", "user_message": "用户输入"} -- 继续对话

    2. 服务端发送消息:
       {"type": "progress", "content": "进度信息..."}   -- 进度更新
       {"type": "chunk", "content": "文本增量"}         -- 响应文本增量
       {"type": "final", "content": "完整响应", "data": {...}, "session_id": "xxx"}  -- 最终消息
       {"type": "error", "content": "错误信息"}         -- 错误
    """
    await websocket.accept()

    dialogue_manager: Optional[AgentDialogueManager] = None
    session_id: Optional[str] = None

    try:
        while True:
            # 接收消息
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "start":
                # 开始新会话
                user_problem = msg.get("user_problem", "").strip()
                if not user_problem:
                    await websocket.send_json({
                        "type": "error",
                        "content": "问题描述不能为空",
                    })
                    continue

                # 创建对话管理器和会话
                dialogue_manager = _create_agent_dialogue_manager()
                session_id = dialogue_manager.create_session(user_problem)
                _agent_session_managers[session_id] = dialogue_manager

                # 流式处理
                try:
                    async for stream_msg in dialogue_manager.process_stream(
                        session_id, user_problem
                    ):
                        await websocket.send_json({
                            "type": stream_msg.type.value,
                            "content": stream_msg.content,
                            "data": stream_msg.data if stream_msg.type == StreamMessageType.FINAL else None,
                            "session_id": session_id if stream_msg.type == StreamMessageType.FINAL else None,
                        })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"处理失败: {str(e)}",
                    })

            elif msg_type == "continue":
                # 继续对话
                user_message = msg.get("user_message", "").strip()
                if not user_message:
                    await websocket.send_json({
                        "type": "error",
                        "content": "消息内容不能为空",
                    })
                    continue

                if not dialogue_manager or not session_id:
                    await websocket.send_json({
                        "type": "error",
                        "content": "请先开始会话",
                    })
                    continue

                # 流式处理
                try:
                    async for stream_msg in dialogue_manager.process_stream(
                        session_id, user_message
                    ):
                        await websocket.send_json({
                            "type": stream_msg.type.value,
                            "content": stream_msg.content,
                            "data": stream_msg.data if stream_msg.type == StreamMessageType.FINAL else None,
                            "session_id": session_id if stream_msg.type == StreamMessageType.FINAL else None,
                        })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"处理失败: {str(e)}",
                    })

            elif msg_type == "close":
                # 关闭会话
                break

            else:
                await websocket.send_json({
                    "type": "error",
                    "content": f"未知消息类型: {msg_type}",
                })

    except WebSocketDisconnect:
        pass
    finally:
        # 清理会话
        if session_id and session_id in _agent_session_managers:
            del _agent_session_managers[session_id]
