"""下一步推荐引擎

基于当前假设状态决定下一步行动

V2 架构变更：
- PhenomenonRecommendationEngine: 基于现象的推荐（推荐）
- RecommendationEngine: V1 基于步骤的推荐（deprecated）
"""
import sqlite3
import json
import warnings
from typing import Optional, List, Dict, Set
from collections import defaultdict

from dbdiag.models.session import SessionState, Hypothesis
from dbdiag.models.step import DiagnosticStep
from dbdiag.models.phenomenon import Phenomenon
from dbdiag.services.llm_service import LLMService


class RecommendationEngine:
    """推荐引擎

    DEPRECATED: 请使用 PhenomenonRecommendationEngine 替代。
    """

    def __init__(self, db_path: str, llm_service: LLMService):
        """
        初始化推荐引擎

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务实例（单例）
        """
        warnings.warn(
            "RecommendationEngine is deprecated. Use PhenomenonRecommendationEngine instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.db_path = db_path
        self.llm_service = llm_service

    def recommend_next_action(
        self, session: SessionState
    ) -> Dict[str, any]:
        """
        推荐下一步行动

        Args:
            session: 会话状态

        Returns:
            推荐动作字典 {"action": "...", "step": ..., "reason": "..."}
        """
        if not session.active_hypotheses:
            return self._ask_for_initial_info(session)

        top_hypothesis = session.active_hypotheses[0]

        # 阶段 1: 高置信度 -> 确认根因
        if top_hypothesis.confidence > 0.85:
            return self._generate_root_cause_confirmation(session, top_hypothesis)

        # 阶段 2: 中置信度 -> 推荐验证步骤
        if top_hypothesis.confidence > 0.50:
            # 找到能区分 Top1 和 Top2 假设的步骤
            hypothesis2 = (
                session.active_hypotheses[1]
                if len(session.active_hypotheses) > 1
                else None
            )
            next_step = self._find_discriminating_step(
                session.active_hypotheses[0],
                hypothesis2,
                session,
            )

            if next_step:
                return self._generate_step_recommendation(session, next_step)

        # 阶段 3: 低置信度 -> 多假设投票或主动询问
        common_steps = self._find_common_recommended_steps(
            session.active_hypotheses[:3],
            session,
        )

        if common_steps:
            # 多个假设都推荐的步骤（高价值）
            return self._generate_step_recommendation(session, common_steps[0])

        # 兜底：询问关键信息
        return self._ask_for_key_symptom(session, top_hypothesis)

    def _ask_for_initial_info(self, session: SessionState) -> Dict:
        """询问初始信息"""
        return {
            "action": "ask_initial_info",
            "message": "请描述您遇到的数据库问题，包括具体症状和表现。",
        }

    def _generate_root_cause_confirmation(
        self, session: SessionState, hypothesis: Hypothesis
    ) -> Dict:
        """生成根因确认响应"""
        return {
            "action": "confirm_root_cause",
            "root_cause": hypothesis.root_cause,
            "confidence": hypothesis.confidence,
            "supporting_step_ids": hypothesis.supporting_step_ids,
            "message": f"根因已定位：{hypothesis.root_cause} (置信度: {hypothesis.confidence:.0%})",
        }

    def _find_discriminating_step(
        self,
        hypothesis1: Hypothesis,
        hypothesis2: Optional[Hypothesis],
        session: SessionState,
    ) -> Optional[DiagnosticStep]:
        """
        找到能区分两个假设的步骤

        Args:
            hypothesis1: 假设 1
            hypothesis2: 假设 2（可选）
            session: 会话状态

        Returns:
            区分性步骤
        """
        executed_step_ids = {s.step_id for s in session.executed_steps}

        if not hypothesis2:
            # 只有一个假设，沿着该路径继续
            return self._get_next_unexecuted_step(hypothesis1, session)

        # 找到 hypothesis1 独有的步骤
        unique_steps_h1 = set(hypothesis1.supporting_step_ids) - set(
            hypothesis2.supporting_step_ids
        )

        # 选择还未执行的步骤
        for step_id in unique_steps_h1:
            if step_id not in executed_step_ids:
                step = self._get_step_by_id(step_id)
                if step and not self._is_similar_to_executed_steps(step, session):
                    return step

        # 如果没有独有步骤，返回 hypothesis1 的下一步
        return self._get_next_unexecuted_step(hypothesis1, session)

    def _find_common_recommended_steps(
        self, hypotheses: List[Hypothesis], session: SessionState
    ) -> List[DiagnosticStep]:
        """
        从多个假设中找到共同推荐的步骤（投票）

        Args:
            hypotheses: 假设列表
            session: 会话状态

        Returns:
            按投票数排序的步骤列表
        """
        step_votes = defaultdict(lambda: {"step": None, "weighted_votes": 0.0})

        for hyp in hypotheses:
            next_step = self._get_next_unexecuted_step(hyp, session)
            if not next_step:
                continue

            step_id = next_step.step_id

            if step_votes[step_id]["step"] is None:
                step_votes[step_id]["step"] = next_step

            # 加权投票（按假设置信度加权）
            step_votes[step_id]["weighted_votes"] += hyp.confidence

        # 按投票数排序
        ranked = sorted(
            step_votes.values(),
            key=lambda x: x["weighted_votes"],
            reverse=True,
        )

        return [v["step"] for v in ranked if v["step"]]

    def _get_next_unexecuted_step(
        self, hypothesis: Hypothesis, session: SessionState
    ) -> Optional[DiagnosticStep]:
        """获取假设的下一个未执行步骤（包含语义去重）"""
        executed_step_ids = {s.step_id for s in session.executed_steps}

        if hypothesis.next_recommended_step_id:
            if hypothesis.next_recommended_step_id not in executed_step_ids:
                step = self._get_step_by_id(hypothesis.next_recommended_step_id)
                if step and not self._is_similar_to_executed_steps(step, session):
                    return step

        # 遍历支持步骤，找到第一个未执行的
        for step_id in hypothesis.supporting_step_ids:
            if step_id not in executed_step_ids:
                step = self._get_step_by_id(step_id)
                if step and not self._is_similar_to_executed_steps(step, session):
                    return step

        return None

    def _is_similar_to_executed_steps(
        self, candidate_step: DiagnosticStep, session: SessionState
    ) -> bool:
        """
        判断候选步骤是否与已执行步骤语义相似

        Args:
            candidate_step: 候选步骤
            session: 会话状态

        Returns:
            True 如果相似，False 否则
        """
        if not session.executed_steps:
            return False

        # 获取已执行步骤的详细信息
        executed_step_facts = []
        for exec_step in session.executed_steps:
            step = self._get_step_by_id(exec_step.step_id)
            if step:
                executed_step_facts.append(step.observed_fact)

        if not executed_step_facts:
            return False

        # 使用 LLM 判断语义相似性
        system_prompt = """你是一个数据库诊断专家。判断两个诊断步骤的观察目标是否语义相似。

语义相似的标准：
1. 检查的是同一个系统指标或现象（如都是检查 IO 等待、都是检查 CPU 使用率）
2. 即使具体的 SQL 命令不同，但目的相同（如都是查看慢查询）
3. 即使阈值或具体数值不同，但检查的对象相同

不相似的情况：
1. 检查不同的指标（IO vs CPU）
2. 检查不同的对象（索引 vs 表）
3. 不同的诊断层面（系统层面 vs 应用层面）

输出格式: 只输出 "yes" 或 "no"
- yes: 语义相似，不应重复推荐
- no: 不相似，可以推荐"""

        user_prompt = f"""候选步骤的观察目标: {candidate_step.observed_fact}

已执行步骤的观察目标:
{chr(10).join([f"- {fact}" for fact in executed_step_facts])}

候选步骤是否与任一已执行步骤语义相似？"""

        try:
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=system_prompt,
            )

            is_similar = response.strip().lower() in ["yes", "是"]
            return is_similar

        except Exception as e:
            # LLM 调用失败时的回退逻辑：使用简单的关键词匹配
            candidate_keywords = set(candidate_step.observed_fact.lower().split())

            for executed_fact in executed_step_facts:
                executed_keywords = set(executed_fact.lower().split())
                # 如果有 50% 以上的关键词重叠，认为相似
                overlap = len(candidate_keywords & executed_keywords)
                if overlap >= len(candidate_keywords) * 0.5:
                    return True

            return False

    def _get_step_by_id(self, step_id: str) -> Optional[DiagnosticStep]:
        """根据 ID 获取步骤"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    step_id, ticket_id, step_index,
                    observed_fact, observation_method, analysis_result,
                    ticket_description, ticket_root_cause
                FROM diagnostic_steps
                WHERE step_id = ?
                """,
                (step_id,),
            )
            row = cursor.fetchone()

            if row:
                return DiagnosticStep(**dict(row))

            return None
        finally:
            conn.close()

    def _generate_step_recommendation(
        self, session: SessionState, step: DiagnosticStep
    ) -> Dict:
        """生成步骤推荐响应"""
        return {
            "action": "recommend_step",
            "step": step,
            "message": f"建议执行以下诊断步骤：\n\n观察目标：{step.observed_fact}\n\n操作方法：\n{step.observation_method}",
        }

    def _ask_for_key_symptom(
        self, session: SessionState, hypothesis: Hypothesis
    ) -> Dict:
        """询问关键症状"""
        if hypothesis.missing_facts:
            missing_fact = hypothesis.missing_facts[0]
            return {
                "action": "ask_symptom",
                "message": f"请确认是否观察到以下现象：{missing_fact}",
            }

        return {
            "action": "ask_general",
            "message": "请提供更多关于问题的详细信息。",
        }


class PhenomenonRecommendationEngine:
    """基于现象的推荐引擎 (V2)

    使用 phenomena 表进行下一步推荐。
    """

    def __init__(self, db_path: str, llm_service: LLMService):
        """
        初始化推荐引擎

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务实例（单例）
        """
        self.db_path = db_path
        self.llm_service = llm_service

    def recommend_next_action(
        self, session: SessionState
    ) -> Dict[str, any]:
        """
        推荐下一步行动（批量推荐多个现象）

        Args:
            session: 会话状态

        Returns:
            推荐动作字典 {"action": "...", "phenomena": [...], "reason": "..."}
        """
        if not session.active_hypotheses:
            return self._ask_for_initial_info(session)

        top_hypothesis = session.active_hypotheses[0]

        # 阶段 1: 高置信度 -> 确认根因（阈值 80%）
        if top_hypothesis.confidence >= 0.80:
            return self._generate_root_cause_confirmation(session, top_hypothesis)

        # 阶段 2 & 3: 收集多个现象进行批量推荐
        phenomena_to_recommend = self._collect_phenomena_for_recommendation(
            session, max_count=3
        )

        if phenomena_to_recommend:
            return self._generate_phenomena_recommendation(session, phenomena_to_recommend)

        # 阶段 4: 没有更多现象可推荐，但置信度中等 -> 也确认根因
        if top_hypothesis.confidence >= 0.50:
            return self._generate_root_cause_confirmation(session, top_hypothesis)

        # 兜底：询问关键信息
        return self._ask_for_key_symptom(session, top_hypothesis)

    def _ask_for_initial_info(self, session: SessionState) -> Dict:
        """询问初始信息"""
        return {
            "action": "ask_initial_info",
            "message": "请描述您遇到的数据库问题，包括具体症状和表现。",
        }

    def _generate_root_cause_confirmation(
        self, session: SessionState, hypothesis: Hypothesis
    ) -> Dict:
        """生成根因确认响应"""
        return {
            "action": "confirm_root_cause",
            "root_cause": hypothesis.root_cause,
            "confidence": hypothesis.confidence,
            "supporting_phenomenon_ids": hypothesis.supporting_phenomenon_ids,
            "supporting_ticket_ids": hypothesis.supporting_ticket_ids,
            "message": f"根因已定位：{hypothesis.root_cause} (置信度: {hypothesis.confidence:.0%})",
        }

    def _collect_phenomena_for_recommendation(
        self, session: SessionState, max_count: int = 3
    ) -> List[Phenomenon]:
        """
        收集多个现象进行批量推荐

        策略：
        1. 从每个活跃假设中收集未确认的现象
        2. 按投票权重排序（多个假设推荐的现象优先）
        3. 去重并返回 top-N

        Args:
            session: 会话状态
            max_count: 最大推荐数量

        Returns:
            现象列表
        """
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}
        recommended_ids = set(session.recommended_phenomenon_ids)

        # 收集所有候选现象及其权重
        phenomenon_scores: Dict[str, Dict] = {}

        for hyp in session.active_hypotheses[:3]:
            for phenomenon_id in hyp.supporting_phenomenon_ids:
                if phenomenon_id in confirmed_ids:
                    continue  # 跳过已确认的

                if phenomenon_id not in phenomenon_scores:
                    phenomenon = self._get_phenomenon_by_id(phenomenon_id)
                    if phenomenon:
                        phenomenon_scores[phenomenon_id] = {
                            "phenomenon": phenomenon,
                            "weight": 0.0,
                            "hypothesis_count": 0,
                            "already_recommended": phenomenon_id in recommended_ids,
                        }

                if phenomenon_id in phenomenon_scores:
                    # 权重 = 假设置信度（多假设推荐的现象权重更高）
                    phenomenon_scores[phenomenon_id]["weight"] += hyp.confidence
                    phenomenon_scores[phenomenon_id]["hypothesis_count"] += 1

        # 排序：优先推荐未推荐过的、被多个假设支持的
        ranked = sorted(
            phenomenon_scores.values(),
            key=lambda x: (
                not x["already_recommended"],  # 未推荐过的优先
                x["hypothesis_count"],          # 被多个假设支持的优先
                x["weight"],                    # 权重高的优先
            ),
            reverse=True,
        )

        return [item["phenomenon"] for item in ranked[:max_count]]

    def _find_discriminating_phenomenon(
        self,
        hypothesis1: Hypothesis,
        hypothesis2: Optional[Hypothesis],
        session: SessionState,
    ) -> Optional[Phenomenon]:
        """
        找到能区分两个假设的现象

        Args:
            hypothesis1: 假设 1
            hypothesis2: 假设 2（可选）
            session: 会话状态

        Returns:
            区分性现象
        """
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}

        if not hypothesis2:
            return self._get_next_unconfirmed_phenomenon(hypothesis1, session)

        # 找到 hypothesis1 独有的现象
        unique_phenomena_h1 = set(hypothesis1.supporting_phenomenon_ids) - set(
            hypothesis2.supporting_phenomenon_ids
        )

        # 选择还未确认的现象
        for phenomenon_id in unique_phenomena_h1:
            if phenomenon_id not in confirmed_ids:
                phenomenon = self._get_phenomenon_by_id(phenomenon_id)
                if phenomenon and not self._is_similar_to_confirmed(phenomenon, session):
                    return phenomenon

        return self._get_next_unconfirmed_phenomenon(hypothesis1, session)

    def _find_common_recommended_phenomena(
        self, hypotheses: List[Hypothesis], session: SessionState
    ) -> List[Phenomenon]:
        """
        从多个假设中找到共同推荐的现象（投票）

        Args:
            hypotheses: 假设列表
            session: 会话状态

        Returns:
            按投票数排序的现象列表
        """
        phenomenon_votes = defaultdict(lambda: {"phenomenon": None, "weighted_votes": 0.0})

        for hyp in hypotheses:
            next_phenomenon = self._get_next_unconfirmed_phenomenon(hyp, session)
            if not next_phenomenon:
                continue

            phenomenon_id = next_phenomenon.phenomenon_id

            if phenomenon_votes[phenomenon_id]["phenomenon"] is None:
                phenomenon_votes[phenomenon_id]["phenomenon"] = next_phenomenon

            phenomenon_votes[phenomenon_id]["weighted_votes"] += hyp.confidence

        ranked = sorted(
            phenomenon_votes.values(),
            key=lambda x: x["weighted_votes"],
            reverse=True,
        )

        return [v["phenomenon"] for v in ranked if v["phenomenon"]]

    def _get_next_unconfirmed_phenomenon(
        self, hypothesis: Hypothesis, session: SessionState
    ) -> Optional[Phenomenon]:
        """获取假设的下一个未确认现象"""
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}

        if hypothesis.next_recommended_phenomenon_id:
            if hypothesis.next_recommended_phenomenon_id not in confirmed_ids:
                phenomenon = self._get_phenomenon_by_id(hypothesis.next_recommended_phenomenon_id)
                if phenomenon and not self._is_similar_to_confirmed(phenomenon, session):
                    return phenomenon

        for phenomenon_id in hypothesis.supporting_phenomenon_ids:
            if phenomenon_id not in confirmed_ids:
                phenomenon = self._get_phenomenon_by_id(phenomenon_id)
                if phenomenon and not self._is_similar_to_confirmed(phenomenon, session):
                    return phenomenon

        return None

    def _is_similar_to_confirmed(
        self, candidate: Phenomenon, session: SessionState
    ) -> bool:
        """
        判断候选现象是否与已确认现象语义相似

        Args:
            candidate: 候选现象
            session: 会话状态

        Returns:
            True 如果相似，False 否则
        """
        if not session.confirmed_phenomena:
            return False

        confirmed_descriptions = []
        for cp in session.confirmed_phenomena:
            phenomenon = self._get_phenomenon_by_id(cp.phenomenon_id)
            if phenomenon:
                confirmed_descriptions.append(phenomenon.description)

        if not confirmed_descriptions:
            return False

        system_prompt = """你是一个数据库诊断专家。判断两个现象是否语义相似。

语义相似的标准：
1. 检查的是同一个系统指标或现象
2. 即使具体的 SQL 不同，但目的相同
3. 即使阈值不同，但检查的对象相同

输出格式: 只输出 "yes" 或 "no"
"""

        user_prompt = f"""候选现象: {candidate.description}

已确认现象:
{chr(10).join([f"- {desc}" for desc in confirmed_descriptions])}

候选现象是否与任一已确认现象语义相似？"""

        try:
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=system_prompt,
            )
            return response.strip().lower() in ["yes", "是"]

        except Exception:
            candidate_keywords = set(candidate.description.lower().split())
            for desc in confirmed_descriptions:
                desc_keywords = set(desc.lower().split())
                overlap = len(candidate_keywords & desc_keywords)
                if overlap >= len(candidate_keywords) * 0.5:
                    return True
            return False

    def _get_phenomenon_by_id(self, phenomenon_id: str) -> Optional[Phenomenon]:
        """根据 ID 获取现象"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    phenomenon_id, description, observation_method,
                    source_anomaly_ids, cluster_size
                FROM phenomena
                WHERE phenomenon_id = ?
                """,
                (phenomenon_id,),
            )
            row = cursor.fetchone()

            if row:
                source_ids = row["source_anomaly_ids"]
                if isinstance(source_ids, str):
                    source_ids = json.loads(source_ids)

                return Phenomenon(
                    phenomenon_id=row["phenomenon_id"],
                    description=row["description"],
                    observation_method=row["observation_method"],
                    source_anomaly_ids=source_ids,
                    cluster_size=row["cluster_size"],
                )

            return None
        finally:
            conn.close()

    def _generate_phenomena_recommendation(
        self, session: SessionState, phenomena: List[Phenomenon]
    ) -> Dict:
        """生成批量现象推荐响应"""
        return {
            "action": "recommend_phenomenon",
            "phenomena": phenomena,  # 复数
            "phenomenon": phenomena[0] if phenomena else None,  # 兼容旧接口
            "message": f"建议确认以下 {len(phenomena)} 个现象",
        }

    def _generate_phenomenon_recommendation(
        self, session: SessionState, phenomenon: Phenomenon
    ) -> Dict:
        """生成现象推荐响应"""
        return {
            "action": "recommend_phenomenon",
            "phenomenon": phenomenon,
            "message": f"建议确认以下现象：\n\n现象描述：{phenomenon.description}\n\n观察方法：\n{phenomenon.observation_method}",
        }

    def _ask_for_key_symptom(
        self, session: SessionState, hypothesis: Hypothesis
    ) -> Dict:
        """询问关键症状"""
        if hypothesis.missing_facts:
            missing_fact = hypothesis.missing_facts[0]
            return {
                "action": "ask_symptom",
                "message": f"请确认是否观察到以下现象：{missing_fact}",
            }

        return {
            "action": "ask_general",
            "message": "请提供更多关于问题的详细信息。",
        }
