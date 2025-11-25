"""下一步推荐引擎

基于当前假设状态决定下一步行动
"""
import sqlite3
from typing import Optional, List, Dict, Set
from collections import defaultdict

from app.models.session import SessionState, Hypothesis
from app.models.step import DiagnosticStep


class RecommendationEngine:
    """推荐引擎"""

    def __init__(self, db_path: str):
        """
        初始化推荐引擎

        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path

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

        # 只排除已执行的步骤（用户做过的），不排除仅推荐过的步骤
        excluded_step_ids = {s.step_id for s in session.executed_steps}

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
                excluded_step_ids,
            )

            if next_step:
                return self._generate_step_recommendation(session, next_step)

        # 阶段 3: 低置信度 -> 多假设投票或主动询问
        common_steps = self._find_common_recommended_steps(
            session.active_hypotheses[:3],
            excluded_step_ids,
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
        executed_step_ids: Set[str],
    ) -> Optional[DiagnosticStep]:
        """
        找到能区分两个假设的步骤

        Args:
            hypothesis1: 假设 1
            hypothesis2: 假设 2（可选）
            executed_step_ids: 已执行的步骤 ID

        Returns:
            区分性步骤
        """
        if not hypothesis2:
            # 只有一个假设，沿着该路径继续
            return self._get_next_unexecuted_step(hypothesis1, executed_step_ids)

        # 找到 hypothesis1 独有的步骤
        unique_steps_h1 = set(hypothesis1.supporting_step_ids) - set(
            hypothesis2.supporting_step_ids
        )

        # 选择还未执行的步骤
        for step_id in unique_steps_h1:
            if step_id not in executed_step_ids:
                step = self._get_step_by_id(step_id)
                if step:
                    return step

        # 如果没有独有步骤，返回 hypothesis1 的下一步
        return self._get_next_unexecuted_step(hypothesis1, executed_step_ids)

    def _find_common_recommended_steps(
        self, hypotheses: List[Hypothesis], executed_step_ids: Set[str]
    ) -> List[DiagnosticStep]:
        """
        从多个假设中找到共同推荐的步骤（投票）

        Args:
            hypotheses: 假设列表
            executed_step_ids: 已执行的步骤 ID

        Returns:
            按投票数排序的步骤列表
        """
        step_votes = defaultdict(lambda: {"step": None, "weighted_votes": 0.0})

        for hyp in hypotheses:
            next_step = self._get_next_unexecuted_step(hyp, executed_step_ids)
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
        self, hypothesis: Hypothesis, executed_step_ids: Set[str]
    ) -> Optional[DiagnosticStep]:
        """获取假设的下一个未执行步骤"""
        if hypothesis.next_recommended_step_id:
            if hypothesis.next_recommended_step_id not in executed_step_ids:
                return self._get_step_by_id(hypothesis.next_recommended_step_id)

        # 遍历支持步骤，找到第一个未执行的
        for step_id in hypothesis.supporting_step_ids:
            if step_id not in executed_step_ids:
                step = self._get_step_by_id(step_id)
                if step:
                    return step

        return None

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
