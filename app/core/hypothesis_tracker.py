"""多假设追踪器

维护并行的根因假设，动态计算置信度
"""
import sqlite3
import json
from typing import List, Set, Dict
from collections import defaultdict

from app.models.session import SessionState, Hypothesis, ConfirmedFact
from app.models.step import DiagnosticStep
from app.core.retriever import StepRetriever
from app.utils.config import Config


class HypothesisTracker:
    """假设追踪器"""

    def __init__(self, db_path: str, config: Config):
        """
        初始化假设追踪器

        Args:
            db_path: 数据库路径
            config: 配置对象
        """
        self.db_path = db_path
        self.config = config
        self.retriever = StepRetriever(db_path, config)

    def update_hypotheses(
        self,
        session: SessionState,
        new_facts: List[ConfirmedFact] = None,
    ) -> SessionState:
        """
        更新会话的假设列表

        Args:
            session: 当前会话状态
            new_facts: 新增的确认事实

        Returns:
            更新后的会话状态
        """
        if new_facts:
            session.confirmed_facts.extend(new_facts)

        # 1. 检索可能的根因（基于已确认事实）
        root_cause_candidates = self._retrieve_root_cause_candidates(session)

        # 2. 为每个根因构建假设
        hypotheses = []
        for root_cause, supporting_steps in root_cause_candidates.items():
            # 计算置信度
            confidence = self._compute_confidence(
                root_cause=root_cause,
                supporting_steps=supporting_steps,
                confirmed_facts=session.confirmed_facts,
                executed_steps=session.executed_steps,
            )

            # 识别缺失的关键事实
            missing_facts = self._identify_missing_facts(
                root_cause=root_cause,
                supporting_steps=supporting_steps,
                confirmed_facts=session.confirmed_facts,
            )

            # 推荐下一步
            next_step_id = self._recommend_next_step_for_hypothesis(
                supporting_steps=supporting_steps,
                executed_step_ids={s.step_id for s in session.executed_steps},
            )

            hypotheses.append(
                Hypothesis(
                    root_cause=root_cause,
                    confidence=confidence,
                    supporting_step_ids=[s.step_id for s in supporting_steps],
                    missing_facts=missing_facts,
                    next_recommended_step_id=next_step_id,
                )
            )

        # 3. 保留 Top-3 假设
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        session.active_hypotheses = hypotheses[:3]

        return session

    def _retrieve_root_cause_candidates(
        self, session: SessionState
    ) -> Dict[str, List[DiagnosticStep]]:
        """
        检索根因候选

        Args:
            session: 会话状态

        Returns:
            {根因: [支持该根因的步骤列表]}
        """
        # 构建查询上下文
        query_context = self._build_query_context(session)

        # 检索相关步骤
        excluded_step_ids = {s.step_id for s in session.executed_steps}
        retrieved_steps = self.retriever.retrieve(
            query=query_context,
            top_k=20,
            excluded_step_ids=excluded_step_ids,
        )

        # 按根因分组
        root_cause_map = defaultdict(list)
        for step, score in retrieved_steps:
            root_cause_map[step.ticket_root_cause].append(step)

        return dict(root_cause_map)

    def _build_query_context(self, session: SessionState) -> str:
        """
        构建查询上下文（用户问题 + 已确认事实）

        Args:
            session: 会话状态

        Returns:
            查询文本
        """
        parts = [session.user_problem]

        for fact in session.confirmed_facts:
            parts.append(fact.fact)

        return " ".join(parts)

    def _compute_confidence(
        self,
        root_cause: str,
        supporting_steps: List[DiagnosticStep],
        confirmed_facts: List[ConfirmedFact],
        executed_steps: List,
    ) -> float:
        """
        计算假设的置信度

        Args:
            root_cause: 根因
            supporting_steps: 支持该根因的步骤
            confirmed_facts: 已确认事实
            executed_steps: 已执行步骤

        Returns:
            置信度（0-1）
        """
        if not supporting_steps:
            return 0.0

        # 1. 事实匹配度（权重 50%）
        # 简化版：检查已确认事实中有多少能在步骤的 observed_fact 中找到
        fact_texts = [f.fact.lower() for f in confirmed_facts]
        matched_count = 0
        for step in supporting_steps:
            step_fact = step.observed_fact.lower()
            if any(fact in step_fact or step_fact in fact for fact in fact_texts):
                matched_count += 1

        fact_coverage = matched_count / len(supporting_steps) if supporting_steps else 0

        # 2. 步骤执行进度（权重 30%）
        executed_step_ids = {s.step_id for s in executed_steps}
        executed_count = sum(
            1 for step in supporting_steps if step.step_id in executed_step_ids
        )
        step_progress = executed_count / len(supporting_steps) if supporting_steps else 0

        # 3. 根因流行度（权重 10%）
        # 简化版：步骤数量越多，流行度越高
        frequency_score = min(len(supporting_steps) / 5, 1.0)

        # 4. 整体相关性（权重 10%）
        # 简化版：固定为 0.5
        relevance_score = 0.5

        # 综合计算
        confidence = (
            0.5 * fact_coverage
            + 0.3 * step_progress
            + 0.1 * frequency_score
            + 0.1 * relevance_score
        )

        return min(confidence, 1.0)

    def _identify_missing_facts(
        self,
        root_cause: str,
        supporting_steps: List[DiagnosticStep],
        confirmed_facts: List[ConfirmedFact],
    ) -> List[str]:
        """
        识别缺失的关键事实

        Args:
            root_cause: 根因
            supporting_steps: 支持该根因的步骤
            confirmed_facts: 已确认事实

        Returns:
            缺失事实列表
        """
        # 简化版：提取步骤中尚未确认的关键观察
        confirmed_texts = {f.fact.lower() for f in confirmed_facts}
        missing = []

        for step in supporting_steps[:3]:  # 只看前 3 个步骤
            fact = step.observed_fact
            # 简单判断：如果步骤的观察事实没有在已确认事实中出现
            if not any(confirmed in fact.lower() for confirmed in confirmed_texts):
                missing.append(fact)

        return missing[:3]  # 最多返回 3 个

    def _recommend_next_step_for_hypothesis(
        self,
        supporting_steps: List[DiagnosticStep],
        executed_step_ids: Set[str],
    ) -> str:
        """
        为假设推荐下一步

        Args:
            supporting_steps: 支持该根因的步骤
            executed_step_ids: 已执行的步骤 ID

        Returns:
            推荐的步骤 ID
        """
        # 按 step_index 排序，找到第一个未执行的步骤
        for step in sorted(supporting_steps, key=lambda s: s.step_index):
            if step.step_id not in executed_step_ids:
                return step.step_id

        return None
