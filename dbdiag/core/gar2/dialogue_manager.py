"""GAR2 对话管理器

基于观察的诊断推理对话管理器。

主流程：
1. InputAnalyzer 解析用户输入 → SymptomDelta
2. ObservationMatcher 匹配新观察 → phenomenon_id, match_score
3. Symptom 更新观察列表 / 阻塞列表
4. ConfidenceCalculator 图传播 → 根因置信度
5. 决策：高置信度 → 诊断 | 否则 → 推荐现象
"""

import uuid
from typing import Dict, Any, Optional, List, Callable

from dbdiag.core.gar2.models import (
    Observation,
    Symptom,
    HypothesisV2,
    SessionStateV2,
    MatchResult,
)
from dbdiag.core.gar2.input_analyzer import InputAnalyzer, SymptomDelta
from dbdiag.core.gar2.observation_matcher import ObservationMatcher
from dbdiag.core.gar2.confidence_calculator import ConfidenceCalculator
from dbdiag.dao import PhenomenonDAO, PhenomenonRootCauseDAO, RootCauseDAO
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService


class GAR2DialogueManager:
    """GAR2 对话管理器

    基于观察的诊断推理引擎。
    """

    # 置信度阈值
    HIGH_CONFIDENCE_THRESHOLD = 0.80
    MEDIUM_CONFIDENCE_THRESHOLD = 0.50

    # 推荐数量
    RECOMMEND_TOP_N = 5

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        """初始化

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务
            embedding_service: Embedding 服务
            progress_callback: 进度回调函数
        """
        self.db_path = db_path
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self._progress_callback = progress_callback

        # 子模块
        self.input_analyzer = InputAnalyzer(llm_service)
        self.observation_matcher = ObservationMatcher(db_path, embedding_service)
        self.confidence_calculator = ConfidenceCalculator(db_path)

        # DAO
        self._phenomenon_dao = PhenomenonDAO(db_path)
        self._phenomenon_root_cause_dao = PhenomenonRootCauseDAO(db_path)
        self._root_cause_dao = RootCauseDAO(db_path)

        # 当前会话
        self.session: Optional[SessionStateV2] = None

    def _report_progress(self, message: str) -> None:
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(message)

    def start_conversation(self, user_problem: str) -> Dict[str, Any]:
        """开始新对话

        Args:
            user_problem: 用户问题描述

        Returns:
            响应字典
        """
        # 创建新会话
        self.session = SessionStateV2(
            session_id=str(uuid.uuid4()),
            user_problem=user_problem,
        )
        self.session.turn_count = 1

        self._report_progress("分析问题描述...")

        # 将用户问题作为初始观察处理
        return self._process_new_observations([user_problem])

    def continue_conversation(self, user_message: str) -> Dict[str, Any]:
        """继续对话

        Args:
            user_message: 用户输入

        Returns:
            响应字典
        """
        if not self.session:
            return {"action": "error", "message": "会话未初始化"}

        self.session.turn_count += 1

        # 1. 解析用户输入
        self._report_progress("解析用户反馈...")
        phenomenon_descriptions = self._get_phenomenon_descriptions(
            self.session.recommended_phenomenon_ids
        )
        delta = self.input_analyzer.analyze(
            user_message,
            self.session.recommended_phenomenon_ids,
            phenomenon_descriptions,
        )

        # 2. 处理确认
        for phenomenon_id in delta.confirmations:
            self._handle_confirmation(phenomenon_id)

        # 3. 处理否认
        for phenomenon_id in delta.denials:
            self._handle_denial(phenomenon_id)

        # 4. 处理新观察
        if delta.new_observations:
            return self._process_new_observations(delta.new_observations)

        # 5. 如果没有新观察，重新计算置信度并决策
        return self._calculate_and_decide()

    def _handle_confirmation(self, phenomenon_id: str) -> None:
        """处理现象确认

        将确认的现象作为观察添加到症状中。
        """
        phenomenon = self._get_phenomenon_by_id(phenomenon_id)
        if phenomenon:
            self.session.symptom.add_observation(
                description=phenomenon.get("description", phenomenon_id),
                source="confirmed",
                matched_phenomenon_id=phenomenon_id,
                match_score=1.0,  # 确认推荐的现象，完全匹配
            )
            self._report_progress(f"已确认: {phenomenon.get('description', phenomenon_id)[:30]}...")

    def _handle_denial(self, phenomenon_id: str) -> None:
        """处理现象否认

        将否认的现象及其关联根因加入阻塞列表。
        """
        related_root_causes = self.confidence_calculator.get_related_root_causes(
            phenomenon_id
        )
        self.session.symptom.block_phenomenon(phenomenon_id, related_root_causes)
        self._report_progress(f"已排除: {phenomenon_id} 及其关联的 {len(related_root_causes)} 个根因")

    def _process_new_observations(self, observations: List[str]) -> Dict[str, Any]:
        """处理新观察

        1. 多目标匹配（phenomena, root_causes, tickets）
        2. 添加到症状
        3. 计算置信度并决策
        """
        self._report_progress("匹配观察到现象、根因、工单...")

        # 聚合所有观察的匹配结果
        aggregated_match = MatchResult()

        for obs_text in observations:
            match_result = self.observation_matcher.match_all(obs_text)

            # 聚合匹配结果
            aggregated_match.phenomena.extend(match_result.phenomena)
            aggregated_match.root_causes.extend(match_result.root_causes)
            aggregated_match.tickets.extend(match_result.tickets)

            # 基于最佳现象匹配添加到症状
            best_phenomenon = match_result.best_phenomenon
            if best_phenomenon:
                self.session.symptom.add_observation(
                    description=obs_text,
                    source="user_input",
                    matched_phenomenon_id=best_phenomenon.phenomenon_id,
                    match_score=best_phenomenon.score,
                )
                self._report_progress(
                    f"匹配成功: {obs_text[:20]}... → {best_phenomenon.phenomenon_id} ({best_phenomenon.score:.0%})"
                )
                # 报告其他匹配
                if match_result.root_causes:
                    self._report_progress(f"  直接匹配根因: {len(match_result.root_causes)} 个")
                if match_result.tickets:
                    self._report_progress(f"  相似工单: {len(match_result.tickets)} 个")
            else:
                # 未匹配现象，但可能有根因或工单匹配
                self.session.symptom.add_observation(
                    description=obs_text,
                    source="user_input",
                )
                if match_result.root_causes or match_result.tickets:
                    self._report_progress(
                        f"未匹配现象，但匹配到 {len(match_result.root_causes)} 个根因, {len(match_result.tickets)} 个工单"
                    )
                else:
                    self._report_progress(f"未找到匹配: {obs_text[:30]}...")

        return self._calculate_and_decide(aggregated_match)

    def _calculate_and_decide(
        self, match_result: Optional[MatchResult] = None
    ) -> Dict[str, Any]:
        """计算置信度并做出决策

        Args:
            match_result: 多目标匹配结果，用于新观察的置信度计算
        """
        self._report_progress("计算根因置信度...")

        # 计算置信度
        if match_result and match_result.has_matches:
            # 使用多目标匹配结果计算置信度
            self.session.hypotheses = self.confidence_calculator.calculate_with_match_result(
                self.session.symptom, match_result
            )
        else:
            # 仅基于 symptom 中的观察计算
            self.session.hypotheses = self.confidence_calculator.calculate(
                self.session.symptom
            )

        top = self.session.top_hypothesis

        # 决策
        if top and top.confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            self._report_progress("置信度达标，生成诊断报告...")
            return self._generate_diagnosis(top)

        if not self.session.hypotheses:
            return self._ask_for_more_info()

        self._report_progress("推荐下一步观察...")
        return self._generate_recommendation()

    def _generate_diagnosis(self, hypothesis: HypothesisV2) -> Dict[str, Any]:
        """生成诊断结果"""
        root_cause = self._root_cause_dao.get_by_id(hypothesis.root_cause_id)

        # 收集观察到的现象
        observed_phenomena = []
        for obs in self.session.symptom.observations:
            if obs.matched_phenomenon_id in hypothesis.contributing_phenomena:
                observed_phenomena.append(obs.description)

        return {
            "action": "diagnose",
            "root_cause_id": hypothesis.root_cause_id,
            "root_cause": root_cause.get("description", hypothesis.root_cause_id) if root_cause else hypothesis.root_cause_id,
            "confidence": hypothesis.confidence,
            "observed_phenomena": observed_phenomena,
            "solution": root_cause.get("solution", "") if root_cause else "",
            "session": self.session,
        }

    def _generate_recommendation(self) -> Dict[str, Any]:
        """生成推荐现象"""
        # 获取 top 假设关联的现象
        recommended = []
        recommended_ids = []

        for hyp in self.session.hypotheses[:3]:  # Top 3 假设
            # 获取根因描述用于推荐原因
            root_cause = self._root_cause_dao.get_by_id(hyp.root_cause_id)
            root_cause_desc = root_cause.get("description", hyp.root_cause_id) if root_cause else hyp.root_cause_id

            phenomena_ids = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
                hyp.root_cause_id
            )
            for pid in phenomena_ids:
                # 跳过已匹配、已阻塞的现象
                if pid in self.session.symptom.get_matched_phenomenon_ids():
                    continue
                if self.session.symptom.is_phenomenon_blocked(pid):
                    continue
                if pid in recommended_ids:
                    continue

                phenomenon = self._get_phenomenon_by_id(pid)
                if phenomenon:
                    recommended.append({
                        "phenomenon_id": pid,
                        "description": phenomenon.get("description", ""),
                        "observation_method": phenomenon.get("observation_method", ""),
                        "related_hypothesis": hyp.root_cause_id,
                        "reason": f"与假设\"{root_cause_desc}\"相关",
                    })
                    recommended_ids.append(pid)

                if len(recommended) >= self.RECOMMEND_TOP_N:
                    break

            if len(recommended) >= self.RECOMMEND_TOP_N:
                break

        # 更新会话中的推荐列表
        self.session.recommended_phenomenon_ids = recommended_ids

        return {
            "action": "recommend",
            "hypotheses": self.session.hypotheses,
            "recommendations": recommended,
            "session": self.session,
        }

    def _ask_for_more_info(self) -> Dict[str, Any]:
        """请求更多信息"""
        return {
            "action": "ask_more_info",
            "message": "请提供更多关于问题的详细信息。",
            "session": self.session,
        }

    def _get_phenomenon_by_id(self, phenomenon_id: str) -> Optional[dict]:
        """根据 ID 获取现象"""
        return self._phenomenon_dao.get_by_id(phenomenon_id)

    def _get_phenomenon_descriptions(self, phenomenon_ids: List[str]) -> Dict[str, str]:
        """获取现象描述映射"""
        result = {}
        for pid in phenomenon_ids:
            phenomenon = self._get_phenomenon_by_id(pid)
            if phenomenon:
                result[pid] = phenomenon.get("description", pid)
        return result

    def get_session(self) -> Optional[SessionStateV2]:
        """获取当前会话"""
        return self.session

    def reset(self) -> None:
        """重置会话"""
        self.session = None
