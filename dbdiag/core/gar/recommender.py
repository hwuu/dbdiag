"""下一步推荐引擎

基于当前假设状态决定下一步行动
"""
from typing import Optional, List, Dict, Set

from dbdiag.models import SessionState, Hypothesis, Phenomenon
from dbdiag.dao import PhenomenonDAO, RootCauseDAO, TicketPhenomenonDAO, PhenomenonRootCauseDAO
from dbdiag.services.llm_service import LLMService
from dbdiag.utils.config import RecommenderConfig


class PhenomenonRecommendationEngine:
    """基于现象的推荐引擎

    使用 phenomena 表进行下一步推荐。
    """

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        config: RecommenderConfig = None,
    ):
        """
        初始化推荐引擎

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务实例（单例）
            config: 推荐引擎配置
        """
        self.db_path = db_path
        self.llm_service = llm_service
        self.config = config or RecommenderConfig()
        self._phenomenon_dao = PhenomenonDAO(db_path)
        self._root_cause_dao = RootCauseDAO(db_path)
        self._ticket_phenomenon_dao = TicketPhenomenonDAO(db_path)
        self._phenomenon_root_cause_dao = PhenomenonRootCauseDAO(db_path)
        # 缓存 max_ticket_count
        self._max_ticket_count: Optional[int] = None

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

        # 阶段 1: 高置信度 -> 确认根因
        if top_hypothesis.confidence >= self.config.high_confidence_threshold:
            return self._generate_root_cause_confirmation(session, top_hypothesis)

        # 阶段 2 & 3: 收集多个现象进行批量推荐
        phenomena_to_recommend = self._collect_phenomena_for_recommendation(
            session, max_count=self.config.recommend_top_n
        )

        if phenomena_to_recommend:
            return self._generate_phenomena_recommendation(session, phenomena_to_recommend)

        # 阶段 4: 没有更多现象可推荐，但置信度中等 -> 也确认根因
        if top_hypothesis.confidence >= self.config.medium_confidence_threshold:
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
            "root_cause": hypothesis.root_cause_id,
            "confidence": hypothesis.confidence,
            "supporting_phenomenon_ids": hypothesis.supporting_phenomenon_ids,
            "supporting_ticket_ids": hypothesis.supporting_ticket_ids,
            "message": f"根因已定位：{hypothesis.root_cause_id} (置信度: {hypothesis.confidence:.0%})",
        }

    def _collect_phenomena_for_recommendation(
        self, session: SessionState, max_count: int = 3
    ) -> List[Dict]:
        """
        收集多个现象进行批量推荐

        策略：
        1. 从活跃假设获取相关根因集合（已在 hypothesis_tracker 中检索过）
        2. 扩展：获取这些根因的所有关联现象
        3. 过滤：排除已确认/已否认的现象
        4. 打分：计算每个现象的推荐得分
        5. 返回 top-n 现象

        Args:
            session: 会话状态
            max_count: 最大推荐数量

        Returns:
            现象信息列表，每项包含 phenomenon 和 related_hypotheses
        """
        if not session.active_hypotheses:
            return []

        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}
        denied_ids = set(session.denied_phenomenon_ids)

        # 1. 从活跃假设获取相关根因集合
        relevant_root_causes = {h.root_cause_id for h in session.active_hypotheses}

        # 2. 扩展：获取这些根因的所有关联现象
        candidate_phenomenon_ids: Set[str] = set()
        for root_cause_id in relevant_root_causes:
            phenomenon_ids = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
                root_cause_id
            )
            candidate_phenomenon_ids.update(phenomenon_ids)

        # 3. 过滤：排除已确认/已否认的现象
        candidate_phenomenon_ids -= confirmed_ids
        candidate_phenomenon_ids -= denied_ids

        if not candidate_phenomenon_ids:
            return []

        # 4. 打分：计算每个现象的推荐得分
        scored_phenomena = []
        for phenomenon_id in candidate_phenomenon_ids:
            phenomenon = self._get_phenomenon_by_id(phenomenon_id)
            if not phenomenon:
                continue

            # 获取现象关联的根因
            related_root_cause_ids = self._phenomenon_root_cause_dao.get_root_causes_by_phenomenon_id(
                phenomenon_id
            )

            # 计算得分
            score = self._calculate_phenomenon_score(
                phenomenon_id=phenomenon_id,
                related_root_cause_ids=related_root_cause_ids,
                session=session,
            )

            # 构建关联假设信息
            related_hypotheses = self._build_related_hypotheses(
                related_root_cause_ids, session
            )

            scored_phenomena.append({
                "phenomenon": phenomenon,
                "score": score,
                "related_hypotheses": related_hypotheses,
            })

        # 5. 排序并返回 top-n
        scored_phenomena.sort(key=lambda x: x["score"], reverse=True)
        return scored_phenomena[:max_count]

    def _calculate_phenomenon_score(
        self,
        phenomenon_id: str,
        related_root_cause_ids: Set[str],
        session: SessionState,
    ) -> float:
        """
        计算现象的推荐得分

        score = w1 * popularity + w2 * specificity + w3 * hypothesis_priority + w4 * information_gain

        Args:
            phenomenon_id: 现象 ID
            related_root_cause_ids: 关联的根因 ID 集合
            session: 会话状态

        Returns:
            推荐得分
        """
        weights = self.config.weights

        # 获取该现象与各根因的 ticket_count
        root_cause_ticket_counts = self._phenomenon_root_cause_dao.get_root_causes_with_ticket_count(
            phenomenon_id
        )

        popularity = self._calculate_popularity(related_root_cause_ids)
        specificity = self._calculate_specificity(related_root_cause_ids)
        hypothesis_priority = self._calculate_hypothesis_priority(
            related_root_cause_ids, session, root_cause_ticket_counts
        )
        information_gain = self._calculate_information_gain(
            phenomenon_id, related_root_cause_ids, session
        )

        score = (
            weights.popularity * popularity +
            weights.specificity * specificity +
            weights.hypothesis_priority * hypothesis_priority +
            weights.information_gain * information_gain
        )

        return score

    def _calculate_popularity(self, related_root_cause_ids: Set[str]) -> float:
        """
        计算流行度：关联根因中最高的流行度

        popularity = max(ticket_count(r) / max_ticket_count for r in R_p)
        """
        if not related_root_cause_ids:
            return 0.0

        max_ticket_count = self._get_max_ticket_count()
        if max_ticket_count == 0:
            return 0.0

        max_popularity = 0.0
        for root_cause_id in related_root_cause_ids:
            ticket_count = self._root_cause_dao.get_ticket_count(root_cause_id)
            popularity = ticket_count / max_ticket_count
            max_popularity = max(max_popularity, popularity)

        return max_popularity

    def _calculate_specificity(self, related_root_cause_ids: Set[str]) -> float:
        """
        计算特异性：关联根因越少，特异性越高

        specificity = 1 / len(R_p)
        """
        if not related_root_cause_ids:
            return 0.0

        return 1.0 / len(related_root_cause_ids)

    def _calculate_hypothesis_priority(
        self,
        related_root_cause_ids: Set[str],
        session: SessionState,
        root_cause_ticket_counts: Dict[str, int] = None,
    ) -> float:
        """
        计算假设优先级：关联根因的置信度，加权 ticket_count

        hypothesis_priority = max(confidence(r) * support_weight(r) for r in R_p)

        其中 support_weight 基于 ticket_count，票数越多支持越强。
        """
        if not related_root_cause_ids or not session.active_hypotheses:
            return 0.0

        root_cause_ticket_counts = root_cause_ticket_counts or {}

        # 计算 ticket_count 的归一化因子
        max_ticket_count = max(root_cause_ticket_counts.values()) if root_cause_ticket_counts else 1

        # 构建根因 -> 置信度映射
        confidence_map = {
            h.root_cause_id: h.confidence for h in session.active_hypotheses
        }

        max_priority = 0.0
        for root_cause_id in related_root_cause_ids:
            confidence = confidence_map.get(root_cause_id, 0.0)

            # 计算支持权重：ticket_count 越高，权重越大
            # 使用 sqrt 平滑，避免票数差异过大导致的极端影响
            ticket_count = root_cause_ticket_counts.get(root_cause_id, 1)
            support_weight = (ticket_count / max_ticket_count) ** 0.5 if max_ticket_count > 0 else 1.0

            # 综合得分 = 置信度 * 支持权重
            weighted_priority = confidence * (0.7 + 0.3 * support_weight)
            max_priority = max(max_priority, weighted_priority)

        return max_priority

    def _calculate_information_gain(
        self,
        phenomenon_id: str,
        related_root_cause_ids: Set[str],
        session: SessionState,
    ) -> float:
        """
        计算信息增益：确认收益 + 区分能力

        information_gain = 0.6 * confirmation_gain + 0.4 * discrimination_power
        """
        confirmation_gain = self._calculate_confirmation_gain(
            related_root_cause_ids, session
        )
        discrimination_power = self._calculate_discrimination_power(
            related_root_cause_ids, session
        )

        return (
            self.config.confirmation_gain_weight * confirmation_gain +
            self.config.discrimination_power_weight * discrimination_power
        )

    def _calculate_confirmation_gain(
        self, related_root_cause_ids: Set[str], session: SessionState
    ) -> float:
        """
        计算确认收益：确认该现象对 top 假设的置信度提升空间

        如果与 top 假设相关：return 1 - confirmed / total
        否则：return 0
        """
        if not session.active_hypotheses:
            return 0.0

        top_hypothesis = session.active_hypotheses[0]

        if top_hypothesis.root_cause_id not in related_root_cause_ids:
            return 0.0

        # 获取 top 假设的所有关联现象
        all_phenomena = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
            top_hypothesis.root_cause_id
        )
        total = len(all_phenomena) if all_phenomena else 1

        # 已确认的现象中，有多少与 top 假设相关
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}
        confirmed_relevant = len(confirmed_ids & all_phenomena)

        # 还有多少增长空间
        return 1.0 - (confirmed_relevant / total)

    def _calculate_discrimination_power(
        self, related_root_cause_ids: Set[str], session: SessionState
    ) -> float:
        """
        计算区分能力：该现象能否有效区分 top-1 和 top-2 假设

        - 只与 top1 相关：1.0（完美区分）
        - 只与 top2 相关：0.8（可排除）
        - 都相关：0.2（区分度低）
        - 都不相关：0.1
        """
        if len(session.active_hypotheses) < 2:
            return 0.0

        top1 = session.active_hypotheses[0]
        top2 = session.active_hypotheses[1]

        top1_related = top1.root_cause_id in related_root_cause_ids
        top2_related = top2.root_cause_id in related_root_cause_ids

        if top1_related and not top2_related:
            return 1.0  # 只与 top1 相关，完美区分
        elif not top1_related and top2_related:
            return 0.8  # 只与 top2 相关，可排除
        elif top1_related and top2_related:
            return 0.2  # 都相关，区分度低
        else:
            return 0.1  # 都不相关

    def _build_related_hypotheses(
        self, related_root_cause_ids: Set[str], session: SessionState
    ) -> List[Dict]:
        """构建关联假设信息列表"""
        related_hypotheses = []
        for h in session.active_hypotheses:
            if h.root_cause_id in related_root_cause_ids:
                related_hypotheses.append({
                    "root_cause": h.root_cause_id,
                    "confidence": h.confidence,
                })
        return related_hypotheses

    def _get_max_ticket_count(self) -> int:
        """获取最大 ticket 数量（带缓存）"""
        if self._max_ticket_count is None:
            self._max_ticket_count = self._root_cause_dao.get_max_ticket_count()
        return self._max_ticket_count

    def _get_root_cause_description(self, root_cause_id: str) -> str:
        """根据 ID 获取根因描述"""
        return self._root_cause_dao.get_description(root_cause_id)

    def _get_phenomenon_by_id(self, phenomenon_id: str) -> Optional[Phenomenon]:
        """根据 ID 获取现象"""
        row_dict = self._phenomenon_dao.get_by_id(phenomenon_id)
        if row_dict:
            return self._phenomenon_dao.dict_to_model(row_dict)
        return None

    def _generate_phenomena_recommendation(
        self, session: SessionState, phenomena_info: List[Dict]
    ) -> Dict:
        """生成批量现象推荐响应（包含关联假设信息）"""
        phenomena = [item["phenomenon"] for item in phenomena_info]

        # 为每个现象附加关联假设信息
        phenomena_with_reasons = []
        for item in phenomena_info:
            phenomenon = item["phenomenon"]
            related_hypotheses = item.get("related_hypotheses", [])

            # 构建原因说明
            if related_hypotheses:
                # 取置信度最高的假设作为主要原因
                top_hyp = max(related_hypotheses, key=lambda h: h["confidence"])
                # 获取根因描述
                root_cause_desc = self._get_root_cause_description(top_hyp['root_cause'])
                reason = f"可能与「{root_cause_desc}」相关"
            else:
                reason = ""

            phenomena_with_reasons.append({
                "phenomenon": phenomenon,
                "reason": reason,
                "related_hypotheses": related_hypotheses,
            })

        return {
            "action": "recommend_phenomenon",
            "phenomena": phenomena,  # 保持兼容
            "phenomena_with_reasons": phenomena_with_reasons,  # 新增：包含原因
            "phenomenon": phenomena[0] if phenomena else None,  # 兼容旧接口
            "message": f"建议确认以下 {len(phenomena)} 个现象",
        }

    def _ask_for_key_symptom(
        self, session: SessionState, hypothesis: Hypothesis
    ) -> Dict:
        """询问关键症状"""
        if hypothesis.missing_phenomena:
            missing_phenomenon = hypothesis.missing_phenomena[0]
            return {
                "action": "ask_symptom",
                "message": f"请确认是否观察到以下现象：{missing_phenomenon}",
            }

        return {
            "action": "ask_general",
            "message": "请提供更多关于问题的详细信息。",
        }
