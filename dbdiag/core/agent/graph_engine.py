"""GraphEngine - 确定性诊断核心

提供贝叶斯推理、信息增益计算等确定性算法。
"""

from typing import List, Dict, Set, Optional, Tuple

from dbdiag.dao import PhenomenonDAO, RootCauseDAO, PhenomenonRootCauseDAO, TicketPhenomenonDAO
from dbdiag.core.agent.models import (
    SessionState,
    DiagnoseInput,
    DiagnoseOutput,
    QueryProgressOutput,
    QueryHypothesesInput,
    QueryHypothesesOutput,
    QueryRelationsInput,
    QueryRelationsOutput,
    Hypothesis,
    HypothesisDetail,
    Recommendation,
    Diagnosis,
    GraphRelation,
    MatchedPhenomenon,
    ConfirmedObservation,
)


class GraphEngine:
    """诊断图谱引擎

    职责：
    1. 计算假设置信度（贝叶斯推理）
    2. 推荐下一步确认的现象（信息增益排序）
    3. 查询诊断进展和假设详情
    4. 查询图谱关系

    所有方法都是纯确定性的，不依赖 LLM。
    """

    # 阈值常量
    HIGH_CONFIDENCE_THRESHOLD = 0.95   # 高置信度，可以给出诊断
    MEDIUM_CONFIDENCE_THRESHOLD = 0.50  # 中等置信度
    RECOMMEND_TOP_N = 5                 # 推荐现象数量
    STUCK_ROUNDS_THRESHOLD = 3          # 卡住检测轮数

    def __init__(self, db_path: str):
        """初始化图谱引擎

        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        self._phenomenon_dao = PhenomenonDAO(db_path)
        self._root_cause_dao = RootCauseDAO(db_path)
        self._phenomenon_root_cause_dao = PhenomenonRootCauseDAO(db_path)
        self._ticket_phenomenon_dao = TicketPhenomenonDAO(db_path)

    def diagnose(
        self,
        session: SessionState,
        input: DiagnoseInput,
    ) -> Tuple[DiagnoseOutput, SessionState]:
        """执行诊断

        Args:
            session: 当前会话状态
            input: 诊断输入（确认/否认的现象）

        Returns:
            (诊断结果, 更新后的 session)
        """
        # 1. 更新 session 状态
        new_session = self._update_session(session, input)

        # 2. 计算假设置信度
        hypotheses = self._calculate_hypotheses(new_session)
        new_session.hypotheses = hypotheses

        # 3. 检查是否完成诊断
        diagnosis_complete = False
        diagnosis = None
        if hypotheses and hypotheses[0].confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            diagnosis_complete = True
            diagnosis = self._create_diagnosis(hypotheses[0], new_session)

        # 4. 生成推荐现象（如果未完成诊断）
        recommendations = []
        if not diagnosis_complete:
            recommendations = self._generate_recommendations(new_session, hypotheses)
            new_session.recommendations = recommendations

        # 5. 更新轮次
        new_session.rounds += 1

        output = DiagnoseOutput(
            diagnosis_complete=diagnosis_complete,
            hypotheses=hypotheses,
            recommendations=recommendations,
            diagnosis=diagnosis,
        )

        return output, new_session

    def query_progress(
        self,
        session: SessionState,
    ) -> QueryProgressOutput:
        """查询诊断进展

        Args:
            session: 当前会话状态

        Returns:
            诊断进展信息
        """
        # 确定诊断状态
        status, status_description = self._determine_status(session)

        top_hypothesis_desc = None
        top_confidence = 0.0
        if session.hypotheses:
            top = session.hypotheses[0]
            top_hypothesis_desc = top.root_cause_description
            top_confidence = top.confidence

        return QueryProgressOutput(
            rounds=session.rounds,
            confirmed_count=session.confirmed_count,
            denied_count=session.denied_count,
            hypotheses_count=len(session.hypotheses),
            top_hypothesis=top_hypothesis_desc,
            top_confidence=top_confidence,
            status=status,
            status_description=status_description,
        )

    def query_hypotheses(
        self,
        session: SessionState,
        top_k: int = 5,
    ) -> QueryHypothesesOutput:
        """查询假设详情

        Args:
            session: 当前会话状态
            top_k: 返回前 K 个假设

        Returns:
            假设详情列表
        """
        details = []
        for i, hyp in enumerate(session.hypotheses[:top_k]):
            # 获取尚未确认但相关的现象
            missing_phenomena = self._get_missing_phenomena(
                hyp.root_cause_id,
                session.get_confirmed_phenomenon_ids()
            )

            # 获取相关工单
            related_tickets = self._get_related_tickets(hyp.root_cause_id)

            details.append(HypothesisDetail(
                root_cause_id=hyp.root_cause_id,
                root_cause_description=hyp.root_cause_description,
                confidence=hyp.confidence,
                rank=i + 1,
                contributing_phenomena=hyp.contributing_phenomena,
                missing_phenomena=missing_phenomena,
                related_tickets=related_tickets,
            ))

        return QueryHypothesesOutput(
            hypotheses=details,
            total_count=len(session.hypotheses),
        )

    def query_relations(
        self,
        input: QueryRelationsInput,
    ) -> QueryRelationsOutput:
        """查询图谱关系

        Args:
            input: 查询输入

        Returns:
            图谱关系列表
        """
        results = []
        source_id = ""
        source_desc = ""

        if input.query_type == "phenomenon_to_root_causes" and input.phenomenon_id:
            source_id = input.phenomenon_id
            phenomenon = self._phenomenon_dao.get_by_id(input.phenomenon_id)
            source_desc = phenomenon.get("description", "") if phenomenon else ""

            # 获取关联的根因
            root_cause_ids = self._phenomenon_root_cause_dao.get_root_causes_by_phenomenon_id(
                input.phenomenon_id
            )
            for rc_id in root_cause_ids:
                rc = self._root_cause_dao.get_by_id(rc_id)
                if rc:
                    # 获取关联强度（基于 ticket_count）
                    ticket_counts = self._phenomenon_root_cause_dao.get_root_causes_with_ticket_count(
                        input.phenomenon_id
                    )
                    ticket_count = ticket_counts.get(rc_id, 0)
                    max_count = max(ticket_counts.values()) if ticket_counts else 1
                    strength = ticket_count / max_count if max_count > 0 else 0

                    results.append(GraphRelation(
                        entity_id=rc_id,
                        entity_description=rc.get("description", ""),
                        relation_strength=strength,
                        supporting_ticket_count=ticket_count,
                    ))

        elif input.query_type == "root_cause_to_phenomena" and input.root_cause_id:
            source_id = input.root_cause_id
            root_cause = self._root_cause_dao.get_by_id(input.root_cause_id)
            source_desc = root_cause.get("description", "") if root_cause else ""

            # 获取关联的现象
            phenomenon_ids = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
                input.root_cause_id
            )
            for p_id in phenomenon_ids:
                p = self._phenomenon_dao.get_by_id(p_id)
                if p:
                    # 获取关联强度
                    ticket_counts = self._phenomenon_root_cause_dao.get_root_causes_with_ticket_count(p_id)
                    ticket_count = ticket_counts.get(input.root_cause_id, 0)
                    max_count = max(ticket_counts.values()) if ticket_counts else 1
                    strength = ticket_count / max_count if max_count > 0 else 0

                    results.append(GraphRelation(
                        entity_id=p_id,
                        entity_description=p.get("description", ""),
                        relation_strength=strength,
                        supporting_ticket_count=ticket_count,
                    ))

        return QueryRelationsOutput(
            query_type=input.query_type,
            source_entity_id=source_id,
            source_entity_description=source_desc,
            results=results,
        )

    # ============================================================
    # 内部方法
    # ============================================================

    def _update_session(
        self,
        session: SessionState,
        input: DiagnoseInput,
    ) -> SessionState:
        """更新会话状态"""
        from datetime import datetime

        # 创建新的 session（不修改原 session）
        new_session = session.model_copy(deep=True)
        new_session.updated_at = datetime.now()

        # 添加确认的现象
        for matched in input.confirmed_phenomena:
            # 检查是否已存在
            existing_ids = {obs.phenomenon_id for obs in new_session.confirmed_observations}
            if matched.phenomenon_id not in existing_ids:
                new_session.confirmed_observations.append(
                    ConfirmedObservation(
                        phenomenon_id=matched.phenomenon_id,
                        phenomenon_description=matched.phenomenon_description,
                        user_observation=matched.user_observation,
                        match_score=matched.match_score,
                    )
                )

        # 添加否认的现象
        for denied_id in input.denied_phenomena:
            new_session.denied_phenomenon_ids.add(denied_id)

        return new_session

    def _calculate_hypotheses(
        self,
        session: SessionState,
    ) -> List[Hypothesis]:
        """计算假设置信度

        使用贝叶斯推理，基于已确认现象计算各根因的置信度。
        """
        if not session.confirmed_observations:
            return []

        # 收集所有确认的现象 ID 及其分数
        confirmed_phenomena: Dict[str, float] = {}
        for obs in session.confirmed_observations:
            confirmed_phenomena[obs.phenomenon_id] = obs.match_score

        # 计算每个根因的得分
        root_cause_scores: Dict[str, float] = {}
        root_cause_phenomena: Dict[str, Set[str]] = {}

        for phenomenon_id, match_score in confirmed_phenomena.items():
            # 获取关联的根因
            root_causes_with_count = self._phenomenon_root_cause_dao.get_root_causes_with_ticket_count(
                phenomenon_id
            )

            for root_cause_id, ticket_count in root_causes_with_count.items():
                # 跳过被否认现象关联的根因（可选策略）
                # 这里暂不实现阻塞逻辑

                # 计算贡献
                max_count = self._get_max_ticket_count_for_root_cause(root_cause_id)
                weight = ticket_count / max_count if max_count > 0 else 1.0
                contribution = match_score * weight

                if root_cause_id not in root_cause_scores:
                    root_cause_scores[root_cause_id] = 0.0
                    root_cause_phenomena[root_cause_id] = set()

                root_cause_scores[root_cause_id] += contribution
                root_cause_phenomena[root_cause_id].add(phenomenon_id)

        # 归一化并创建假设
        hypotheses = []
        for root_cause_id, raw_score in root_cause_scores.items():
            # 获取根因信息
            root_cause = self._root_cause_dao.get_by_id(root_cause_id)
            if not root_cause:
                continue

            # 归一化因子：该根因关联的所有现象数
            all_phenomena = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
                root_cause_id
            )
            normalization = len(all_phenomena) if all_phenomena else 1
            confidence = min(raw_score / normalization, 1.0)

            hypotheses.append(Hypothesis(
                root_cause_id=root_cause_id,
                root_cause_description=root_cause.get("description", ""),
                confidence=confidence,
                contributing_phenomena=list(root_cause_phenomena[root_cause_id]),
            ))

        # 按置信度排序
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return hypotheses

    def _get_max_ticket_count_for_root_cause(self, root_cause_id: str) -> int:
        """获取根因关联的最大 ticket_count"""
        phenomena_ids = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
            root_cause_id
        )
        if not phenomena_ids:
            return 1

        max_count = 0
        for pid in phenomena_ids:
            counts = self._phenomenon_root_cause_dao.get_root_causes_with_ticket_count(pid)
            count = counts.get(root_cause_id, 0)
            max_count = max(max_count, count)

        return max_count if max_count > 0 else 1

    def _generate_recommendations(
        self,
        session: SessionState,
        hypotheses: List[Hypothesis],
    ) -> List[Recommendation]:
        """生成推荐现象

        基于信息增益排序，推荐能最有效区分当前假设的现象。
        """
        if not hypotheses:
            return []

        # 已确认和否认的现象
        confirmed_ids = session.get_confirmed_phenomenon_ids()
        denied_ids = session.denied_phenomenon_ids

        # 收集候选现象（前几个假设关联的现象）
        candidate_phenomenon_ids: Set[str] = set()
        for hyp in hypotheses[:3]:  # 只考虑前 3 个假设
            phenomena_ids = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
                hyp.root_cause_id
            )
            candidate_phenomenon_ids.update(phenomena_ids)

        # 排除已确认和已否认的
        candidate_phenomenon_ids -= confirmed_ids
        candidate_phenomenon_ids -= denied_ids

        # 计算每个候选现象的信息增益
        recommendations = []
        for p_id in candidate_phenomenon_ids:
            phenomenon = self._phenomenon_dao.get_by_id(p_id)
            if not phenomenon:
                continue

            # 计算信息增益（简化版：与多少个假设相关）
            related_hypotheses = []
            for hyp in hypotheses:
                if p_id in self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(hyp.root_cause_id):
                    related_hypotheses.append(hyp.root_cause_id)

            # 信息增益 = 关联的假设数 / 总假设数
            info_gain = len(related_hypotheses) / len(hypotheses) if hypotheses else 0

            recommendations.append(Recommendation(
                phenomenon_id=p_id,
                description=phenomenon.get("description", ""),
                observation_method=phenomenon.get("observation_method", ""),
                reason=f"与 {len(related_hypotheses)} 个假设相关，可有效缩小范围",
                related_hypotheses=related_hypotheses,
                information_gain=info_gain,
            ))

        # 按信息增益排序
        recommendations.sort(key=lambda r: r.information_gain, reverse=True)
        return recommendations[:self.RECOMMEND_TOP_N]

    def _create_diagnosis(
        self,
        top_hypothesis: Hypothesis,
        session: SessionState,
    ) -> Diagnosis:
        """创建诊断结论"""
        # 获取观察到的现象描述
        observed = [obs.phenomenon_description for obs in session.confirmed_observations]

        # 获取解决方案（从根因信息中获取）
        root_cause = self._root_cause_dao.get_by_id(top_hypothesis.root_cause_id)
        solution = root_cause.get("solution", "") if root_cause else ""

        # 获取参考工单
        reference_tickets = self._get_related_tickets(top_hypothesis.root_cause_id)

        return Diagnosis(
            root_cause_id=top_hypothesis.root_cause_id,
            root_cause_description=top_hypothesis.root_cause_description,
            confidence=top_hypothesis.confidence,
            observed_phenomena=observed,
            solution=solution,
            reference_tickets=reference_tickets[:3],  # 最多 3 个
            reasoning=f"基于 {len(observed)} 个确认现象的贝叶斯推理",
        )

    def _determine_status(
        self,
        session: SessionState,
    ) -> Tuple[str, str]:
        """确定诊断状态"""
        if not session.hypotheses:
            return "exploring", "刚开始诊断，需要收集更多信息"

        top_confidence = session.hypotheses[0].confidence

        if top_confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            return "confirming", f"置信度达到 {top_confidence:.0%}，接近确认诊断结论"
        elif top_confidence >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            return "narrowing", f"置信度 {top_confidence:.0%}，正在缩小范围"
        elif session.rounds >= self.STUCK_ROUNDS_THRESHOLD and top_confidence < 0.3:
            return "stuck", "进行了多轮但置信度仍然较低，可能需要换个方向"
        else:
            return "exploring", "正在收集信息，继续确认现象"

    def _get_missing_phenomena(
        self,
        root_cause_id: str,
        confirmed_ids: Set[str],
    ) -> List[str]:
        """获取尚未确认但相关的现象描述"""
        all_phenomena_ids = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
            root_cause_id
        )
        missing_ids = set(all_phenomena_ids) - confirmed_ids

        descriptions = []
        for p_id in list(missing_ids)[:5]:  # 最多 5 个
            p = self._phenomenon_dao.get_by_id(p_id)
            if p:
                descriptions.append(p.get("description", ""))

        return descriptions

    def _get_related_tickets(self, root_cause_id: str) -> List[str]:
        """获取与根因相关的工单 ID"""
        # 这里简化实现，实际可能需要查询 tickets 表
        return []
