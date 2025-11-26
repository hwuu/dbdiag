"""多假设追踪器

维护并行的根因假设，动态计算置信度

V2 架构变更：
- PhenomenonHypothesisTracker: 基于现象的假设追踪（推荐）
- HypothesisTracker: V1 基于步骤的追踪（deprecated）
"""
import sqlite3
import json
import warnings
from typing import List, Set, Dict, Optional
from collections import defaultdict

from dbdiag.models.session import SessionState, Hypothesis, ConfirmedFact
from dbdiag.models.step import DiagnosticStep
from dbdiag.models.phenomenon import Phenomenon
from dbdiag.core.retriever import StepRetriever, PhenomenonRetriever
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService


class HypothesisTracker:
    """假设追踪器

    DEPRECATED: 请使用 PhenomenonHypothesisTracker 替代。
    """

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService = None,
    ):
        """
        初始化假设追踪器

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务实例（单例）
            embedding_service: Embedding 服务实例（单例，可选）
        """
        warnings.warn(
            "HypothesisTracker is deprecated. Use PhenomenonHypothesisTracker instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.db_path = db_path
        self.llm_service = llm_service
        self.retriever = StepRetriever(db_path, embedding_service) if embedding_service else StepRetriever(db_path)

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

        # 引入假设排他性：如果 Top-1 假设的置信度显著高于其他假设，降低其他假设的置信度
        if len(hypotheses) > 1 and hypotheses[0].confidence > 0.45:
            confidence_gap = hypotheses[0].confidence - hypotheses[1].confidence

            # 如果 Top-1 领先（差距 > 0.04），降低其他假设
            if confidence_gap > 0.04:
                penalty_factor = 0.7  # 降低到原来的 70%
                for i in range(1, len(hypotheses)):
                    hypotheses[i] = Hypothesis(
                        root_cause=hypotheses[i].root_cause,
                        confidence=hypotheses[i].confidence * penalty_factor,
                        supporting_step_ids=hypotheses[i].supporting_step_ids,
                        missing_facts=hypotheses[i].missing_facts,
                        next_recommended_step_id=hypotheses[i].next_recommended_step_id,
                    )

        # 重新排序
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
        # 使用 LLM 判断事实是支持还是反对该假设
        fact_score = self._evaluate_facts_for_hypothesis(
            root_cause, supporting_steps, confirmed_facts
        )

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
            0.5 * fact_score
            + 0.3 * step_progress
            + 0.1 * frequency_score
            + 0.1 * relevance_score
        )

        return min(max(confidence, 0.0), 1.0)

    def _evaluate_facts_for_hypothesis(
        self,
        root_cause: str,
        supporting_steps: List[DiagnosticStep],
        confirmed_facts: List[ConfirmedFact],
    ) -> float:
        """
        使用 LLM 评估已确认事实对假设的支持程度

        Args:
            root_cause: 根因
            supporting_steps: 支持该根因的步骤
            confirmed_facts: 已确认事实

        Returns:
            事实评分（0-1），>0.5 表示支持，<0.5 表示反对
        """
        if not confirmed_facts:
            return 0.5  # 无事实时返回中性分数

        # 构建评估提示
        system_prompt = """你是数据库诊断专家。请评估已确认的事实是否支持某个根因假设。

规则:
1. 正面事实（支持假设）：如果事实表明该根因可能存在，给正分（0.6-1.0）
2. 负面事实（反对假设）：如果事实表明该根因不太可能，给负分（0.0-0.4）
3. 中性事实（无关或不确定）：给中性分（0.5）
4. 考虑多个事实的综合影响

输出格式: 单个浮点数（0.0-1.0）
例如: 0.8 表示强烈支持，0.2 表示强烈反对，0.5 表示中性"""

        # 构建关键诊断步骤描述（用于提供上下文）
        step_descriptions = []
        for step in supporting_steps[:3]:  # 只取前 3 个步骤作为上下文
            step_descriptions.append(f"- {step.observation_method}（期望观察: {step.observed_fact}）")

        user_prompt = f"""根因假设: {root_cause}

相关诊断步骤:
{chr(10).join(step_descriptions)}

已确认事实:
{chr(10).join(f"- {fact.fact}" for fact in confirmed_facts)}

请评估这些已确认事实对该根因假设的支持程度（0.0-1.0）:"""

        try:
            # 调用 LLM
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=system_prompt,
            )

            # 解析评分
            score_text = response.strip()
            score = float(score_text)
            return min(max(score, 0.0), 1.0)

        except Exception as e:
            # LLM 调用失败时的回退逻辑：使用简单的关键词匹配
            return self._fallback_fact_evaluation(
                root_cause, supporting_steps, confirmed_facts
            )

    def _fallback_fact_evaluation(
        self,
        root_cause: str,
        supporting_steps: List[DiagnosticStep],
        confirmed_facts: List[ConfirmedFact],
    ) -> float:
        """
        回退方案：使用关键词匹配评估事实

        Args:
            root_cause: 根因
            supporting_steps: 支持该根因的步骤
            confirmed_facts: 已确认事实

        Returns:
            事实评分（0-1）
        """
        # 提取根因关键词（简化版：取根因中的名词）
        root_cause_keywords = set(root_cause.lower().split())

        positive_count = 0
        negative_count = 0

        for fact in confirmed_facts:
            fact_lower = fact.fact.lower()

            # 检查是否是负面表述
            is_negative = any(
                keyword in fact_lower
                for keyword in ["正常", "没问题", "不存在", "无", "ok", "good"]
            )

            # 检查是否提到根因关键词
            mentions_root_cause = any(
                keyword in fact_lower for keyword in root_cause_keywords
            )

            if mentions_root_cause:
                if is_negative:
                    negative_count += 1  # 提到根因但说正常 -> 反对假设
                else:
                    positive_count += 1  # 提到根因且不正常 -> 支持假设

        # 计算分数
        total = positive_count + negative_count
        if total == 0:
            return 0.5  # 没有相关事实

        # 负面事实降低分数
        score = 0.5 + 0.3 * (positive_count - negative_count) / total
        return min(max(score, 0.0), 1.0)

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


class PhenomenonHypothesisTracker:
    """基于现象的假设追踪器 (V2)

    从 phenomena 和 ticket_anomalies 关联表中检索根因假设。
    """

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService = None,
        progress_callback: Optional[callable] = None,
    ):
        """
        初始化假设追踪器

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务实例（单例）
            embedding_service: Embedding 服务实例（单例，可选）
            progress_callback: 进度回调函数，签名为 callback(message: str)
        """
        self.db_path = db_path
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self.progress_callback = progress_callback
        self.retriever = PhenomenonRetriever(db_path, embedding_service)

    def _report_progress(self, message: str) -> None:
        """报告进度"""
        if self.progress_callback:
            self.progress_callback(message)

    def update_hypotheses(
        self,
        session: SessionState,
    ) -> SessionState:
        """
        更新会话的假设列表 (V2: 基于 confirmed_phenomena)

        Args:
            session: 当前会话状态

        Returns:
            更新后的会话状态
        """
        # 1. 检索可能的根因（基于现象和 ticket 关联）
        self._report_progress("检索根因候选...")
        root_cause_candidates = self._retrieve_root_cause_candidates(session)

        # 2. 为每个根因构建假设
        hypotheses = []
        total_candidates = len(root_cause_candidates)
        for idx, (root_cause, supporting_data) in enumerate(root_cause_candidates.items(), 1):
            # 显示评估进度（截取根因前20个字符）
            root_cause_short = root_cause[:20] + "..." if len(root_cause) > 20 else root_cause
            self._report_progress(f"评估假设 ({idx}/{total_candidates}): {root_cause_short}")

            phenomena = supporting_data["phenomena"]
            ticket_ids = supporting_data["ticket_ids"]

            # 计算置信度（V2: 基于 confirmed_phenomena）
            confidence = self._compute_confidence(
                root_cause=root_cause,
                supporting_phenomena=phenomena,
                confirmed_phenomena=session.confirmed_phenomena,
            )

            # 识别缺失的现象
            missing_phenomena = self._identify_missing_phenomena(
                supporting_phenomena=phenomena,
                confirmed_phenomena=session.confirmed_phenomena,
            )

            # 推荐下一个现象
            next_phenomenon_id = self._recommend_next_phenomenon(
                supporting_phenomena=phenomena,
                confirmed_phenomenon_ids={
                    p.phenomenon_id for p in session.confirmed_phenomena
                },
            )

            hypotheses.append(
                Hypothesis(
                    root_cause=root_cause,
                    confidence=confidence,
                    supporting_step_ids=[],  # V1 字段，保持兼容
                    missing_facts=missing_phenomena,  # 复用字段存储 missing_phenomena
                    next_recommended_step_id=None,  # V1 字段，保持兼容
                    # V2 新字段
                    supporting_phenomenon_ids=[p.phenomenon_id for p in phenomena],
                    supporting_ticket_ids=ticket_ids,
                    next_recommended_phenomenon_id=next_phenomenon_id,
                )
            )

        # 3. 保留 Top-3 假设
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        # 假设排他性处理
        if len(hypotheses) > 1 and hypotheses[0].confidence > 0.45:
            confidence_gap = hypotheses[0].confidence - hypotheses[1].confidence
            if confidence_gap > 0.04:
                penalty_factor = 0.7
                for i in range(1, len(hypotheses)):
                    hypotheses[i] = Hypothesis(
                        root_cause=hypotheses[i].root_cause,
                        confidence=hypotheses[i].confidence * penalty_factor,
                        supporting_step_ids=hypotheses[i].supporting_step_ids,
                        missing_facts=hypotheses[i].missing_facts,
                        next_recommended_step_id=hypotheses[i].next_recommended_step_id,
                        supporting_phenomenon_ids=hypotheses[i].supporting_phenomenon_ids,
                        supporting_ticket_ids=hypotheses[i].supporting_ticket_ids,
                        next_recommended_phenomenon_id=hypotheses[i].next_recommended_phenomenon_id,
                    )

        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        session.active_hypotheses = hypotheses[:3]

        return session

    def _retrieve_root_cause_candidates(
        self, session: SessionState
    ) -> Dict[str, Dict]:
        """
        检索根因候选

        Args:
            session: 会话状态

        Returns:
            {根因: {"phenomena": [...], "ticket_ids": [...]}}
        """
        # 构建查询上下文（只用 user_problem，保持稳定）
        query_context = session.user_problem

        # 检索相关现象（不排除已确认的，保持假设稳定性）
        retrieved_phenomena = self.retriever.retrieve(
            query=query_context,
            top_k=20,
            excluded_phenomenon_ids=set(),  # 不排除任何现象
        )

        # 从 ticket_anomalies 获取关联的 ticket 信息
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            root_cause_map = defaultdict(lambda: {"phenomena": [], "ticket_ids": set()})

            for phenomenon, score in retrieved_phenomena:
                # 查找关联的 tickets
                cursor.execute("""
                    SELECT DISTINCT ta.ticket_id, rt.root_cause
                    FROM ticket_anomalies ta
                    JOIN raw_tickets rt ON ta.ticket_id = rt.ticket_id
                    WHERE ta.phenomenon_id = ?
                """, (phenomenon.phenomenon_id,))

                for row in cursor.fetchall():
                    root_cause = row["root_cause"]
                    ticket_id = row["ticket_id"]

                    root_cause_map[root_cause]["phenomena"].append(phenomenon)
                    root_cause_map[root_cause]["ticket_ids"].add(ticket_id)

            # 转换 set 为 list
            for root_cause in root_cause_map:
                root_cause_map[root_cause]["ticket_ids"] = list(
                    root_cause_map[root_cause]["ticket_ids"]
                )

            return dict(root_cause_map)

        finally:
            conn.close()

    def _build_query_context(self, session: SessionState) -> str:
        """
        构建查询上下文 (V2: 基于 user_problem + confirmed_phenomena)

        Args:
            session: 会话状态

        Returns:
            查询文本
        """
        parts = [session.user_problem]

        # 添加已确认现象的描述
        for cp in session.confirmed_phenomena:
            if cp.result_summary:
                parts.append(cp.result_summary)

        return " ".join(parts)

    def _compute_confidence(
        self,
        root_cause: str,
        supporting_phenomena: List[Phenomenon],
        confirmed_phenomena: List,
    ) -> float:
        """
        计算假设的置信度 (V2: 基于 confirmed_phenomena)

        Args:
            root_cause: 根因
            supporting_phenomena: 支持该根因的现象
            confirmed_phenomena: 已确认现象

        Returns:
            置信度（0-1）
        """
        if not supporting_phenomena:
            return 0.0

        # 1. 现象确认进度（权重 60%）
        # 改进：查询数据库找出该根因关联的所有现象，而不是只看 supporting_phenomena
        confirmed_ids = {p.phenomenon_id for p in confirmed_phenomena}

        # 查询该根因关联的所有现象 ID
        related_phenomenon_ids = self._get_phenomena_for_root_cause(root_cause)

        # 计算确认的现象中有多少与该根因相关
        confirmed_relevant_count = len(confirmed_ids & related_phenomenon_ids)

        # 进度 = 确认的相关现象数 / 该根因的总现象数（至少1）
        total_for_root_cause = max(len(related_phenomenon_ids), 1)
        progress = confirmed_relevant_count / total_for_root_cause

        # 2. 根因流行度（权重 20%）- 支持该根因的现象越多，流行度越高
        frequency_score = min(len(supporting_phenomena) / 5, 1.0)

        # 3. 基础相关性（权重 20%）- 基础分数
        relevance_score = 0.5

        confidence = (
            0.6 * progress
            + 0.2 * frequency_score
            + 0.2 * relevance_score
        )

        return min(max(confidence, 0.0), 1.0)

    def _get_phenomena_for_root_cause(self, root_cause: str) -> Set[str]:
        """
        获取与某个根因关联的所有现象 ID

        Args:
            root_cause: 根因描述

        Returns:
            现象 ID 集合
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT DISTINCT ta.phenomenon_id
                FROM ticket_anomalies ta
                JOIN raw_tickets rt ON ta.ticket_id = rt.ticket_id
                WHERE rt.root_cause = ?
            """, (root_cause,))

            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def _identify_missing_phenomena(
        self,
        supporting_phenomena: List[Phenomenon],
        confirmed_phenomena: List,
    ) -> List[str]:
        """
        识别缺失的关键现象 (V2)

        Args:
            supporting_phenomena: 支持该根因的现象
            confirmed_phenomena: 已确认现象

        Returns:
            缺失现象描述列表
        """
        confirmed_ids = {p.phenomenon_id for p in confirmed_phenomena}
        missing = []

        for p in supporting_phenomena[:5]:
            if p.phenomenon_id not in confirmed_ids:
                missing.append(p.description)

        return missing[:3]

    def _recommend_next_phenomenon(
        self,
        supporting_phenomena: List[Phenomenon],
        confirmed_phenomenon_ids: Set[str],
    ) -> Optional[str]:
        """
        推荐下一个要确认的现象

        Args:
            supporting_phenomena: 支持该根因的现象
            confirmed_phenomenon_ids: 已确认的现象 ID

        Returns:
            推荐的现象 ID
        """
        for p in supporting_phenomena:
            if p.phenomenon_id not in confirmed_phenomenon_ids:
                return p.phenomenon_id

        return None
