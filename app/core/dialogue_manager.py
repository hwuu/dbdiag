"""对话管理器

整合所有组件，管理对话流程
"""
from typing import Dict, Any, Optional
from datetime import datetime

from app.models.session import SessionState, ConfirmedFact, DialogueMessage
from app.core.hypothesis_tracker import HypothesisTracker
from app.core.recommender import RecommendationEngine
from app.core.response_generator import ResponseGenerator
from app.services.session_service import SessionService
from app.services.llm_service import LLMService
from app.utils.config import Config


class DialogueManager:
    """对话管理器"""

    def __init__(self, db_path: str, config: Config):
        """
        初始化对话管理器

        Args:
            db_path: 数据库路径
            config: 配置对象
        """
        self.db_path = db_path
        self.config = config

        # 初始化服务
        self.session_service = SessionService(db_path)
        self.llm_service = LLMService(config)
        self.hypothesis_tracker = HypothesisTracker(db_path, config)
        self.recommender = RecommendationEngine(db_path)
        self.response_generator = ResponseGenerator(db_path, self.llm_service)

    def start_conversation(self, user_problem: str) -> Dict[str, Any]:
        """
        开始新对话

        Args:
            user_problem: 用户问题描述

        Returns:
            响应字典
        """
        # 创建新会话
        session = self.session_service.create_session(user_problem)

        # 添加用户消息到历史
        session.dialogue_history.append(
            DialogueMessage(role="user", content=user_problem)
        )

        # 生成初始假设
        session = self.hypothesis_tracker.update_hypotheses(session)

        # 获取推荐
        recommendation = self.recommender.recommend_next_action(session)

        # 生成响应
        response = self.response_generator.generate_response(session, recommendation)

        # 添加助手响应到历史
        session.dialogue_history.append(
            DialogueMessage(role="assistant", content=response["message"])
        )

        # 保存会话
        self.session_service.update_session(session)

        # 返回响应（包含 session_id）
        response["session_id"] = session.session_id
        return response

    def continue_conversation(
        self, session_id: str, user_message: str
    ) -> Dict[str, Any]:
        """
        继续对话

        Args:
            session_id: 会话 ID
            user_message: 用户消息

        Returns:
            响应字典
        """
        # 加载会话
        session = self.session_service.get_session(session_id)
        if not session:
            return {
                "error": "会话不存在",
                "message": "会话已过期或不存在，请重新开始对话。",
            }

        # 添加用户消息到历史
        session.dialogue_history.append(
            DialogueMessage(role="user", content=user_message)
        )

        # 解析用户消息，提取确认事实
        new_facts = self._extract_facts_from_user_message(user_message, session)

        # 更新假设
        session = self.hypothesis_tracker.update_hypotheses(session, new_facts)

        # 获取推荐
        recommendation = self.recommender.recommend_next_action(session)

        # 生成响应
        response = self.response_generator.generate_response(session, recommendation)

        # 添加助手响应到历史
        session.dialogue_history.append(
            DialogueMessage(role="assistant", content=response["message"])
        )

        # 保存会话
        self.session_service.update_session(session)

        # 返回响应
        response["session_id"] = session.session_id
        return response

    def _extract_facts_from_user_message(
        self, user_message: str, session: SessionState
    ) -> list[ConfirmedFact]:
        """
        从用户消息中提取确认的事实

        Args:
            user_message: 用户消息
            session: 会话状态

        Returns:
            确认事实列表
        """
        # 简化版：直接将用户消息作为一个事实
        # TODO: 未来可以用 LLM 进行更智能的解析
        facts = []

        # 如果消息看起来像是回答观察结果
        if any(
            keyword in user_message.lower()
            for keyword in ["是", "确认", "看到", "发现", "观察到", "显示", "%", "占比"]
        ):
            facts.append(
                ConfirmedFact(
                    fact=user_message,
                    from_user_input=True,
                )
            )

        return facts

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话信息

        Args:
            session_id: 会话 ID

        Returns:
            会话信息字典
        """
        session = self.session_service.get_session(session_id)
        if not session:
            return None

        return {
            "session_id": session.session_id,
            "user_problem": session.user_problem,
            "created_at": session.created_at.isoformat(),
            "confirmed_facts_count": len(session.confirmed_facts),
            "active_hypotheses_count": len(session.active_hypotheses),
            "dialogue_turns": len(session.dialogue_history),
        }

    def list_sessions(self, limit: int = 10) -> list[dict]:
        """
        列出最近的会话

        Args:
            limit: 返回数量

        Returns:
            会话列表
        """
        return self.session_service.list_sessions(limit)
