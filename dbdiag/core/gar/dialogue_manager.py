"""对话管理器

整合所有组件，管理对话流程
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from dbdiag.models import (
    SessionState, ConfirmedPhenomenon, DialogueMessage, Phenomenon,
    RecommendedPhenomenon, DeniedPhenomenon
)
from dbdiag.core.gar.hypothesis_tracker import PhenomenonHypothesisTracker
from dbdiag.core.gar.recommender import PhenomenonRecommendationEngine
from dbdiag.core.gar.response_generator import ResponseGenerator
from dbdiag.core.gar.retriever import PhenomenonRetriever
from dbdiag.dao import PhenomenonDAO
from dbdiag.services.session_service import SessionService
from dbdiag.services.llm_service import LLMService
from dbdiag.utils.config import RecommenderConfig


class GARDialogueManager:
    """图谱增强推理对话管理器 (Graph-Augmented-Reasoning)

    使用 phenomena 和 ticket_phenomena 构建的知识图谱进行诊断对话。

    hybrid_mode: 混合增强模式
        - 启用 ticket description 语义检索，从相似工单提取候选现象
        - 增强初始推荐的覆盖率
    """

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: Optional["EmbeddingService"] = None,
        progress_callback: Optional[callable] = None,
        recommender_config: Optional[RecommenderConfig] = None,
        hybrid_mode: bool = False,
    ):
        """
        初始化对话管理器

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务实例（单例）
            embedding_service: Embedding 服务实例（单例，可选）
            progress_callback: 进度回调函数，签名为 callback(message: str)
            recommender_config: 推荐引擎配置
            hybrid_mode: 是否启用混合增强模式
        """
        self.db_path = db_path
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self.progress_callback = progress_callback
        self.hybrid_mode = hybrid_mode

        # 初始化服务
        self.session_service = SessionService(db_path)
        self.hypothesis_tracker = PhenomenonHypothesisTracker(
            db_path, llm_service, embedding_service,
            progress_callback=progress_callback,
            recommender_config=recommender_config,
        )
        self.recommender = PhenomenonRecommendationEngine(
            db_path, llm_service, recommender_config
        )
        self.response_generator = ResponseGenerator(db_path, llm_service)
        self._phenomenon_dao = PhenomenonDAO(db_path)

        # 混合模式使用的检索器
        if hybrid_mode:
            self._retriever = PhenomenonRetriever(db_path, embedding_service)

    def _report_progress(self, message: str) -> None:
        """报告进度"""
        if self.progress_callback:
            self.progress_callback(message)

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

        # 混合模式：先搜索相似工单，提取候选现象存入 session
        if self.hybrid_mode:
            self._report_progress("检索相似工单...")
            ticket_matches = self._retriever.search_by_ticket_description(
                user_problem, top_k=5
            )
            if ticket_matches:
                self._report_progress(f"找到 {len(ticket_matches)} 个相似工单")
                # 获取关联现象
                ticket_ids = [m.ticket_id for m in ticket_matches]
                candidate_phenomena = self._retriever.get_phenomena_by_ticket_ids(ticket_ids)
                session.hybrid_candidate_phenomenon_ids = [p.phenomenon_id for p in candidate_phenomena]
                self._report_progress(f"提取 {len(session.hybrid_candidate_phenomenon_ids)} 个候选现象")

        # 生成初始假设
        self._report_progress("检索相关现象...")
        session = self.hypothesis_tracker.update_hypotheses(session)

        # 获取推荐
        self._report_progress("生成推荐...")
        recommendation = self.recommender.recommend_next_action(session)

        # 生成响应
        response = self._generate_response(session, recommendation)

        # 记录推荐的现象（支持批量）
        if response.get("action") == "recommend_phenomenon":
            phenomena = response.get("phenomena", [])
            if not phenomena and response.get("phenomenon"):
                phenomena = [response["phenomenon"]]
            round_number = len(session.dialogue_history) // 2 + 1
            for p in phenomena:
                if p.phenomenon_id not in session.recommended_phenomenon_ids:
                    session.recommended_phenomena.append(
                        RecommendedPhenomenon(
                            phenomenon_id=p.phenomenon_id,
                            round_number=round_number
                        )
                    )

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

        # 检查用户是否确认了之前推荐的现象
        self._report_progress("识别用户反馈...")
        new_observations = self._mark_confirmed_phenomena_from_feedback(user_message, session)

        # 中间轮语义检索：若有新观察，检索相似工单补充候选现象
        if new_observations and self.hybrid_mode:
            self._report_progress("检索相关案例...")
            query = " ".join(new_observations)
            ticket_matches = self._retriever.search_by_ticket_description(query, top_k=3)
            if ticket_matches:
                self._report_progress(f"找到 {len(ticket_matches)} 个相关案例")
                ticket_ids = [m.ticket_id for m in ticket_matches]
                candidate_phenomena = self._retriever.get_phenomena_by_ticket_ids(ticket_ids)
                # 合并到候选池（去重）
                existing_ids = set(session.hybrid_candidate_phenomenon_ids)
                for p in candidate_phenomena:
                    if p.phenomenon_id not in existing_ids:
                        session.hybrid_candidate_phenomenon_ids.append(p.phenomenon_id)
                        existing_ids.add(p.phenomenon_id)
                self._report_progress(f"补充 {len(candidate_phenomena)} 个候选现象")

            # 记录新观察到 session
            session.new_observations.extend(new_observations)

        # 更新假设
        self._report_progress("更新假设置信度...")
        session = self.hypothesis_tracker.update_hypotheses(session)

        # 获取推荐
        self._report_progress("生成推荐...")
        recommendation = self.recommender.recommend_next_action(session)

        # 生成响应
        response = self._generate_response(session, recommendation)

        # 记录推荐的现象（支持批量）
        if response.get("action") == "recommend_phenomenon":
            phenomena = response.get("phenomena", [])
            if not phenomena and response.get("phenomenon"):
                phenomena = [response["phenomenon"]]
            round_number = len(session.dialogue_history) // 2 + 1
            for p in phenomena:
                if p.phenomenon_id not in session.recommended_phenomenon_ids:
                    session.recommended_phenomena.append(
                        RecommendedPhenomenon(
                            phenomenon_id=p.phenomenon_id,
                            round_number=round_number
                        )
                    )

        # 添加助手响应到历史
        session.dialogue_history.append(
            DialogueMessage(role="assistant", content=response["message"])
        )

        # 保存会话
        self.session_service.update_session(session)

        # 返回响应
        response["session_id"] = session.session_id
        return response

    def _generate_response(
        self, session: SessionState, recommendation: Dict
    ) -> Dict[str, Any]:
        """
        生成响应

        Args:
            session: 会话状态
            recommendation: 推荐动作

        Returns:
            响应字典
        """
        action = recommendation.get("action")

        if action == "recommend_phenomenon":
            # 现象推荐：直接返回（包含关联假设信息）
            phenomena = recommendation.get("phenomena", [])
            phenomenon = recommendation.get("phenomenon")
            phenomena_with_reasons = recommendation.get("phenomena_with_reasons", [])

            return {
                "action": "recommend_phenomenon",
                "phenomena": phenomena,  # 批量现象
                "phenomena_with_reasons": phenomena_with_reasons,  # 包含原因说明
                "phenomenon": phenomenon,  # 兼容旧接口
                "message": recommendation.get("message", ""),
            }

        elif action == "confirm_root_cause":
            # 根因确认：使用 ResponseGenerator 生成 LLM 总结
            return self.response_generator.generate_response(session, recommendation)

        # 其他情况直接返回
        return recommendation

    def _mark_confirmed_phenomena_from_feedback(
        self, user_message: str, session: SessionState
    ) -> List[str]:
        """
        从用户反馈中识别已确认/否定的现象（支持批量）

        支持的输入格式：
        - "1确认 2否定 3确认" - 批量确认/否定
        - "确认" / "是" / "看到了" - 确认最近推荐的所有现象
        - "全否定" / "都不是" - 否定最近推荐的所有现象
        - "IO 正常，索引异常" - 自然语言描述（LLM 提取）

        Args:
            user_message: 用户消息
            session: 会话状态

        Returns:
            用户描述的新观察列表（不在待确认列表中的）
        """
        # 获取最近推荐的未处理现象（最多取最近的3个）
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}
        denied_ids = set(session.denied_phenomenon_ids)
        pending_phenomenon_ids = [
            pid for pid in session.recommended_phenomenon_ids
            if pid not in confirmed_ids and pid not in denied_ids
        ][-3:]  # 最近推荐的3个

        if not pending_phenomenon_ids:
            return []

        # 简单否定关键词 -> 否定所有待确认的现象
        simple_deny_keywords = ["全否定", "都否定", "都不是", "全部否定", "都没有", "都没看到"]
        if any(kw in user_message for kw in simple_deny_keywords):
            for phenomenon_id in pending_phenomenon_ids:
                if phenomenon_id not in session.denied_phenomenon_ids:
                    session.denied_phenomena.append(
                        DeniedPhenomenon(phenomenon_id=phenomenon_id)
                    )
            return []

        # 尝试解析批量确认格式：如 "1确认 2否定 3确认"
        batch_pattern = r'(\d+)\s*(确认|否定|是|否|正常|异常|没有|不是)'
        batch_matches = re.findall(batch_pattern, user_message)

        if batch_matches:
            # 批量确认模式
            for idx_str, action in batch_matches:
                idx = int(idx_str) - 1  # 转为0-based索引
                if 0 <= idx < len(pending_phenomenon_ids):
                    phenomenon_id = pending_phenomenon_ids[idx]
                    if action in ["确认", "是", "正常"]:
                        session.confirmed_phenomena.append(
                            ConfirmedPhenomenon(
                                phenomenon_id=phenomenon_id,
                                result_summary=f"用户确认: {action}",
                            )
                        )
                    elif action in ["否定", "否", "异常", "没有", "不是"]:
                        if phenomenon_id not in session.denied_phenomenon_ids:
                            session.denied_phenomena.append(
                                DeniedPhenomenon(phenomenon_id=phenomenon_id)
                            )
            return []

        # 简单确认关键词 -> 确认所有待确认的现象
        simple_confirm_keywords = ["确认", "是", "是的", "看到了", "观察到", "都确认", "全部确认"]
        if any(kw in user_message for kw in simple_confirm_keywords):
            for phenomenon_id in pending_phenomenon_ids:
                session.confirmed_phenomena.append(
                    ConfirmedPhenomenon(
                        phenomenon_id=phenomenon_id,
                        result_summary=user_message,
                    )
                )
            return []

        # 非简单格式：使用 LLM 结构化提取
        return self._extract_feedback_with_llm(user_message, pending_phenomenon_ids, session)

    def _extract_feedback_with_llm(
        self, user_message: str, pending_phenomenon_ids: List[str], session: SessionState
    ) -> List[str]:
        """
        使用 LLM 从自然语言中提取结构化反馈

        Args:
            user_message: 用户消息
            pending_phenomenon_ids: 待确认的现象 ID 列表
            session: 会话状态

        Returns:
            用户描述的新观察列表
        """
        self._report_progress("分析用户反馈...")

        # 构建待确认现象列表
        pending_descriptions = []
        for i, pid in enumerate(pending_phenomenon_ids, 1):
            phenomenon = self._get_phenomenon_by_id(pid)
            if phenomenon:
                pending_descriptions.append(f"{i}. [{pid}] {phenomenon.description}")

        system_prompt = """你是一个对话分析助手。分析用户消息，判断用户对每个待确认现象的反馈。

输出 JSON 格式：
{
  "feedback": {
    "<phenomenon_id>": "confirmed" | "denied" | "unknown"
  },
  "new_observations": ["用户提到的新观察1", "用户提到的新观察2"]
}

判断规则：
- confirmed: 用户明确确认看到了该现象，或描述符合该现象
- denied: 用户明确否认，或描述与该现象相反（如"正常"对应"异常"）
- unknown: 用户未提及该现象

new_observations: 用户描述的、不在待确认列表中的新观察或现象。只提取具体的技术观察，忽略闲聊。

只输出 JSON，不要其他内容。"""

        user_prompt = f"""待确认现象：
{chr(10).join(pending_descriptions)}

用户消息: {user_message}"""

        try:
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=system_prompt,
            )

            # 解析 JSON
            import json
            # 清理可能的 markdown 代码块
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)

            result = json.loads(response)

            # 处理反馈
            feedback = result.get("feedback", {})
            for pid in pending_phenomenon_ids:
                status = feedback.get(pid, "unknown")
                if status == "confirmed":
                    session.confirmed_phenomena.append(
                        ConfirmedPhenomenon(
                            phenomenon_id=pid,
                            result_summary=user_message,
                        )
                    )
                elif status == "denied":
                    if pid not in session.denied_phenomenon_ids:
                        session.denied_phenomena.append(
                            DeniedPhenomenon(phenomenon_id=pid)
                        )

            # 返回新观察
            return result.get("new_observations", [])

        except Exception as e:
            # LLM 失败时回退到关键词匹配
            self._report_progress(f"LLM 分析失败，使用关键词匹配: {e}")
            return self._fallback_keyword_matching(user_message, pending_phenomenon_ids, session)

    def _fallback_keyword_matching(
        self, user_message: str, pending_phenomenon_ids: List[str], session: SessionState
    ) -> List[str]:
        """关键词匹配回退逻辑"""
        feedback_keywords = [
            "正常", "异常", "没问题", "有问题",
            "%", "占比", "发现", "观察到", "显示", "看到",
            "ok", "高", "低", "多", "少"
        ]

        if any(keyword in user_message.lower() for keyword in feedback_keywords):
            for phenomenon_id in pending_phenomenon_ids:
                session.confirmed_phenomena.append(
                    ConfirmedPhenomenon(
                        phenomenon_id=phenomenon_id,
                        result_summary=user_message,
                    )
                )

        return []

    def _get_phenomenon_by_id(self, phenomenon_id: str) -> Optional[Phenomenon]:
        """根据 ID 获取现象"""
        row_dict = self._phenomenon_dao.get_by_id(phenomenon_id)
        if row_dict:
            return self._phenomenon_dao.dict_to_model(row_dict)
        return None

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
            "confirmed_phenomena_count": len(session.confirmed_phenomena),
            "active_hypotheses_count": len(session.active_hypotheses),
            "dialogue_turns": len(session.dialogue_history),
        }

    def list_sessions(self, limit: int = 10) -> List[dict]:
        """
        列出最近的会话

        Args:
            limit: 返回数量

        Returns:
            会话列表
        """
        return self.session_service.list_sessions(limit)
