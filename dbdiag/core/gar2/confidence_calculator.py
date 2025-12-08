"""置信度计算器

通过图传播计算根因置信度。

GAR2 多目标匹配置信度计算：
- phenomena 匹配贡献权重: 0.5
- root_cause 直接匹配贡献权重: 0.3
- ticket 匹配贡献权重: 0.2

公式：
confidence(RC) = Σ contribution / normalization_factor

contribution 来自三个来源：
1. phenomenon: obs.match_score × phenomenon_root_cause_weight(P, RC) × 0.5
2. root_cause: direct_match_score × 0.3
3. ticket: ticket_match_score × 0.2
"""

from typing import List, Dict, Set, Optional

from dbdiag.core.gar2.models import Symptom, HypothesisV2, MatchResult
from dbdiag.dao import PhenomenonRootCauseDAO, RootCauseDAO


class ConfidenceCalculator:
    """置信度计算器

    通过图传播计算根因置信度：
    1. 从观察出发，找到匹配的现象
    2. 从现象出发，找到关联的根因
    3. 累加每个观察对根因的贡献（包括现象、根因、工单三种来源）
    4. 归一化得到置信度
    """

    # 多目标匹配权重
    PHENOMENON_WEIGHT = 0.5   # 现象匹配权重
    ROOT_CAUSE_WEIGHT = 0.3   # 根因直接匹配权重
    TICKET_WEIGHT = 0.2       # 工单匹配权重

    def __init__(self, db_path: str):
        """初始化置信度计算器

        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        self._phenomenon_root_cause_dao = PhenomenonRootCauseDAO(db_path)
        self._root_cause_dao = RootCauseDAO(db_path)

    def calculate(self, symptom: Symptom) -> List[HypothesisV2]:
        """计算所有根因的置信度

        Args:
            symptom: 症状（观察列表 + 阻塞列表）

        Returns:
            假设列表，按置信度降序排列
        """
        # 1. 收集所有匹配的现象 ID
        matched_phenomenon_ids = symptom.get_matched_phenomenon_ids()
        if not matched_phenomenon_ids:
            return []

        # 2. 找到所有关联的根因
        root_cause_scores: Dict[str, float] = {}
        root_cause_observations: Dict[str, List[str]] = {}
        root_cause_phenomena: Dict[str, Set[str]] = {}

        for obs in symptom.observations:
            if not obs.matched_phenomenon_id:
                continue

            phenomenon_id = obs.matched_phenomenon_id

            # 获取该现象关联的根因及其 ticket_count
            root_causes_with_count = self._phenomenon_root_cause_dao.get_root_causes_with_ticket_count(
                phenomenon_id
            )

            for root_cause_id, ticket_count in root_causes_with_count.items():
                # 跳过被阻塞的根因
                if symptom.is_root_cause_blocked(root_cause_id):
                    continue

                # 计算贡献
                # weight = ticket_count 归一化（相对于该根因的最大 ticket_count）
                max_count = self._get_max_ticket_count_for_root_cause(root_cause_id)
                weight = ticket_count / max_count if max_count > 0 else 1.0

                contribution = obs.match_score * weight

                # 累加
                if root_cause_id not in root_cause_scores:
                    root_cause_scores[root_cause_id] = 0.0
                    root_cause_observations[root_cause_id] = []
                    root_cause_phenomena[root_cause_id] = set()

                root_cause_scores[root_cause_id] += contribution
                root_cause_observations[root_cause_id].append(obs.id)
                root_cause_phenomena[root_cause_id].add(phenomenon_id)

        # 3. 归一化置信度
        hypotheses = []
        for root_cause_id, raw_score in root_cause_scores.items():
            # 获取该根因关联的所有现象数量作为归一化因子
            all_phenomena = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
                root_cause_id
            )
            normalization = len(all_phenomena) if all_phenomena else 1

            # 置信度 = 累计贡献 / 可能的最大贡献
            # 最大贡献 = 所有现象都以 match_score=1.0 确认
            confidence = min(raw_score / normalization, 1.0)

            hypotheses.append(
                HypothesisV2(
                    root_cause_id=root_cause_id,
                    confidence=confidence,
                    contributing_observations=root_cause_observations[root_cause_id],
                    contributing_phenomena=list(root_cause_phenomena[root_cause_id]),
                )
            )

        # 4. 按置信度排序
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return hypotheses

    def _get_max_ticket_count_for_root_cause(self, root_cause_id: str) -> int:
        """获取根因关联的最大 ticket_count

        用于 phenomenon_root_cause_weight 的归一化。
        """
        # 获取该根因下所有现象的 ticket_count
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

    def get_related_root_causes(self, phenomenon_id: str) -> List[str]:
        """获取现象关联的根因 ID 列表

        用于否定时阻塞相关根因。

        Args:
            phenomenon_id: 现象 ID

        Returns:
            根因 ID 列表
        """
        return list(
            self._phenomenon_root_cause_dao.get_root_causes_by_phenomenon_id(phenomenon_id)
        )

    def calculate_with_match_result(
        self, symptom: Symptom, match_result: MatchResult
    ) -> List[HypothesisV2]:
        """基于多目标匹配结果计算置信度

        综合 phenomena、root_causes、tickets 三种匹配结果：
        - phenomena 匹配通过 phenomenon_root_causes 传播到 root_cause
        - root_cause 匹配直接贡献
        - ticket 匹配通过 ticket.root_cause_id 传播

        Args:
            symptom: 症状（观察列表 + 阻塞列表）
            match_result: 多目标匹配结果

        Returns:
            假设列表，按置信度降序排列
        """
        root_cause_scores: Dict[str, float] = {}
        root_cause_observations: Dict[str, List[str]] = {}
        root_cause_phenomena: Dict[str, Set[str]] = {}

        # 1. 处理 phenomena 匹配（权重 0.5）
        for pm in match_result.phenomena:
            phenomenon_id = pm.phenomenon_id
            match_score = pm.score

            # 获取该现象关联的根因
            root_causes_with_count = self._phenomenon_root_cause_dao.get_root_causes_with_ticket_count(
                phenomenon_id
            )

            for root_cause_id, ticket_count in root_causes_with_count.items():
                if symptom.is_root_cause_blocked(root_cause_id):
                    continue

                # 计算贡献
                max_count = self._get_max_ticket_count_for_root_cause(root_cause_id)
                weight = ticket_count / max_count if max_count > 0 else 1.0
                contribution = match_score * weight * self.PHENOMENON_WEIGHT

                self._accumulate_score(
                    root_cause_id, contribution,
                    f"phenomenon:{phenomenon_id}",
                    phenomenon_id,
                    root_cause_scores, root_cause_observations, root_cause_phenomena
                )

        # 2. 处理 root_cause 直接匹配（权重 0.3）
        for rcm in match_result.root_causes:
            root_cause_id = rcm.root_cause_id
            if symptom.is_root_cause_blocked(root_cause_id):
                continue

            contribution = rcm.score * self.ROOT_CAUSE_WEIGHT

            self._accumulate_score(
                root_cause_id, contribution,
                f"root_cause:{root_cause_id}",
                None,
                root_cause_scores, root_cause_observations, root_cause_phenomena
            )

        # 3. 处理 ticket 匹配（权重 0.2）
        for tm in match_result.tickets:
            root_cause_id = tm.root_cause_id
            if not root_cause_id or symptom.is_root_cause_blocked(root_cause_id):
                continue

            contribution = tm.score * self.TICKET_WEIGHT

            self._accumulate_score(
                root_cause_id, contribution,
                f"ticket:{tm.ticket_id}",
                None,
                root_cause_scores, root_cause_observations, root_cause_phenomena
            )

        # 4. 加上 symptom 中已确认观察的贡献
        hypotheses = self._add_symptom_contributions(
            symptom, root_cause_scores, root_cause_observations, root_cause_phenomena
        )

        # 5. 归一化并生成假设列表
        if not hypotheses:
            hypotheses = self._normalize_and_create_hypotheses(
                root_cause_scores, root_cause_observations, root_cause_phenomena
            )

        # 6. 按置信度排序
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return hypotheses

    def _accumulate_score(
        self,
        root_cause_id: str,
        contribution: float,
        obs_id: str,
        phenomenon_id: Optional[str],
        root_cause_scores: Dict[str, float],
        root_cause_observations: Dict[str, List[str]],
        root_cause_phenomena: Dict[str, Set[str]],
    ) -> None:
        """累加根因分数"""
        if root_cause_id not in root_cause_scores:
            root_cause_scores[root_cause_id] = 0.0
            root_cause_observations[root_cause_id] = []
            root_cause_phenomena[root_cause_id] = set()

        root_cause_scores[root_cause_id] += contribution
        root_cause_observations[root_cause_id].append(obs_id)
        if phenomenon_id:
            root_cause_phenomena[root_cause_id].add(phenomenon_id)

    def _add_symptom_contributions(
        self,
        symptom: Symptom,
        root_cause_scores: Dict[str, float],
        root_cause_observations: Dict[str, List[str]],
        root_cause_phenomena: Dict[str, Set[str]],
    ) -> List[HypothesisV2]:
        """添加 symptom 中已确认观察的贡献并返回假设列表"""
        for obs in symptom.observations:
            if not obs.matched_phenomenon_id:
                continue

            phenomenon_id = obs.matched_phenomenon_id
            root_causes_with_count = self._phenomenon_root_cause_dao.get_root_causes_with_ticket_count(
                phenomenon_id
            )

            for root_cause_id, ticket_count in root_causes_with_count.items():
                if symptom.is_root_cause_blocked(root_cause_id):
                    continue

                max_count = self._get_max_ticket_count_for_root_cause(root_cause_id)
                weight = ticket_count / max_count if max_count > 0 else 1.0
                contribution = obs.match_score * weight * self.PHENOMENON_WEIGHT

                self._accumulate_score(
                    root_cause_id, contribution,
                    obs.id,
                    phenomenon_id,
                    root_cause_scores, root_cause_observations, root_cause_phenomena
                )

        return self._normalize_and_create_hypotheses(
            root_cause_scores, root_cause_observations, root_cause_phenomena
        )

    def _normalize_and_create_hypotheses(
        self,
        root_cause_scores: Dict[str, float],
        root_cause_observations: Dict[str, List[str]],
        root_cause_phenomena: Dict[str, Set[str]],
    ) -> List[HypothesisV2]:
        """归一化分数并创建假设列表"""
        hypotheses = []
        for root_cause_id, raw_score in root_cause_scores.items():
            all_phenomena = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
                root_cause_id
            )
            normalization = len(all_phenomena) if all_phenomena else 1
            confidence = min(raw_score / normalization, 1.0)

            hypotheses.append(
                HypothesisV2(
                    root_cause_id=root_cause_id,
                    confidence=confidence,
                    contributing_observations=root_cause_observations[root_cause_id],
                    contributing_phenomena=list(root_cause_phenomena[root_cause_id]),
                )
            )
        return hypotheses
