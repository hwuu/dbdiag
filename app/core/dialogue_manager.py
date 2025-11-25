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

        # 记录推荐的步骤（避免重复推荐）
        if response.get("action") == "recommend_step" and response.get("step"):
            step_id = response["step"]["step_id"]
            if step_id not in session.recommended_step_ids:
                session.recommended_step_ids.append(step_id)

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

        # 检查用户是否执行了之前推荐的步骤
        self._mark_executed_steps_from_feedback(user_message, session)

        # 更新假设
        session = self.hypothesis_tracker.update_hypotheses(session, new_facts)

        # 获取推荐
        recommendation = self.recommender.recommend_next_action(session)

        # 生成响应
        response = self.response_generator.generate_response(session, recommendation)

        # 记录推荐的步骤（避免重复推荐）
        if response.get("action") == "recommend_step" and response.get("step"):
            step_id = response["step"]["step_id"]
            if step_id not in session.recommended_step_ids:
                session.recommended_step_ids.append(step_id)

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
        # 使用 LLM 智能提取事实
        system_prompt = """你是一个数据库诊断助手，负责从用户反馈中提取诊断事实。

用户会回复诊断步骤的执行结果或观察到的现象。你需要提取关键事实。

规则:
1. 提取明确的观察结果（如"CPU 使用率 95%"、"IO 正常"、"查询时间 30 秒"）
2. 提取否定信息（如"IO 正常"表示"IO 没有瓶颈"）
3. 忽略无关的闲聊或问题
4. 每个事实用一句话概括

输出格式: JSON 数组，每个元素是一个字符串
例如: ["CPU 使用率 95%", "内存使用正常", "慢查询日志显示全表扫描"]

如果没有提取到事实，返回空数组: []"""

        user_prompt = f"""用户消息: {user_message}

请提取其中的诊断事实:"""

        try:
            # 调用 LLM
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=system_prompt,
            )

            # 解析 JSON
            import json
            facts_text = response.strip()

            # 尝试提取 JSON（可能被包在代码块中）
            if "```json" in facts_text:
                facts_text = facts_text.split("```json")[1].split("```")[0].strip()
            elif "```" in facts_text:
                facts_text = facts_text.split("```")[1].split("```")[0].strip()

            extracted_facts = json.loads(facts_text)

            # 转换为 ConfirmedFact 对象
            facts = []
            for fact_text in extracted_facts:
                if fact_text and fact_text.strip():
                    facts.append(
                        ConfirmedFact(
                            fact=fact_text.strip(),
                            from_user_input=True,
                        )
                    )

            return facts

        except Exception as e:
            # LLM 调用失败时的回退逻辑：使用关键词匹配
            facts = []

            # 扩展关键词列表，包含常见反馈
            if any(
                keyword in user_message.lower()
                for keyword in [
                    "是", "确认", "看到", "发现", "观察到", "显示",
                    "%", "占比", "正常", "异常", "没问题", "有问题",
                    "不正常", "ok", "good", "bad", "高", "低", "多", "少"
                ]
            ):
                facts.append(
                    ConfirmedFact(
                        fact=user_message,
                        from_user_input=True,
                    )
                )

            return facts

    def _mark_executed_steps_from_feedback(
        self, user_message: str, session: SessionState
    ) -> None:
        """
        从用户反馈中识别已执行的步骤

        当用户反馈结果时（如"io 正常"），说明用户执行了最近推荐的步骤。
        将该步骤标记为已执行。

        Args:
            user_message: 用户消息
            session: 会话状态
        """
        # 找到最近推荐的步骤（还未标记为执行的）
        last_recommended_step_id = None
        if session.recommended_step_ids:
            # 从后往前找第一个未执行的推荐步骤
            executed_step_ids = {s.step_id for s in session.executed_steps}
            for step_id in reversed(session.recommended_step_ids):
                if step_id not in executed_step_ids:
                    last_recommended_step_id = step_id
                    break

        if not last_recommended_step_id:
            return  # 没有待确认的推荐步骤

        # 使用 LLM 判断用户是否提供了执行结果
        system_prompt = """你是一个对话分析助手。判断用户的消息是否包含对诊断步骤的执行反馈。

执行反馈的特征：
1. 报告了观察结果（如"CPU 使用率 95%"、"IO 正常"、"没发现慢查询"）
2. 回答了诊断问题（如"是的"、"确认"、"看到了"）
3. 提供了检查结果（如"查询时间 30 秒"、"索引都在"）

非执行反馈：
1. 单纯的问题（如"怎么检查？"、"这个命令是什么意思？"）
2. 闲聊或其他话题

输出格式: 只输出 "yes" 或 "no"
- yes: 用户提供了执行反馈
- no: 用户没有提供执行反馈"""

        user_prompt = f"""用户消息: {user_message}

这是否包含诊断步骤的执行反馈？"""

        try:
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=system_prompt,
            )

            is_feedback = response.strip().lower() in ["yes", "是"]

            if is_feedback:
                # 标记为已执行
                from app.models.session import ExecutedStep

                session.executed_steps.append(
                    ExecutedStep(
                        step_id=last_recommended_step_id,
                        result_summary=user_message,
                    )
                )

        except Exception as e:
            # LLM 调用失败时的回退逻辑：使用简单规则
            # 如果用户消息包含明确的反馈关键词，认为是执行反馈
            feedback_keywords = [
                "正常", "异常", "没问题", "有问题", "不正常",
                "%", "占比", "发现", "观察到", "显示", "看到",
                "是", "确认", "ok", "good", "bad",
                "高", "低", "多", "少", "快", "慢"
            ]

            if any(keyword in user_message.lower() for keyword in feedback_keywords):
                from app.models.session import ExecutedStep

                session.executed_steps.append(
                    ExecutedStep(
                        step_id=last_recommended_step_id,
                        result_summary=user_message,
                    )
                )

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
