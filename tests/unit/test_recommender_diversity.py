"""推荐引擎多样性约束测试"""
import pytest
from unittest.mock import MagicMock, patch

from dbdiag.core.gar.recommender import PhenomenonRecommendationEngine
from dbdiag.models import SessionState, Hypothesis, ConfirmedPhenomenon
from dbdiag.utils.config import RecommenderConfig


class TestDiversityConstraint:
    """多样性约束测试"""

    def _create_mock_engine(self, config: RecommenderConfig = None):
        """创建带 mock 的推荐引擎"""
        config = config or RecommenderConfig()
        with patch.object(PhenomenonRecommendationEngine, "__init__", lambda self, *args, **kwargs: None):
            engine = PhenomenonRecommendationEngine.__new__(PhenomenonRecommendationEngine)
            engine.config = config
        return engine

    def _create_session(
        self,
        confirmed_count: int = 0,
        top_confidence: float = 0.3,
        hypotheses: list = None,
    ) -> SessionState:
        """创建测试用会话"""
        if hypotheses is None:
            hypotheses = [
                Hypothesis(
                    root_cause_id="RC1",
                    confidence=top_confidence,
                    missing_phenomena=[],
                    supporting_phenomenon_ids=[],
                    supporting_ticket_ids=[],
                ),
                Hypothesis(
                    root_cause_id="RC2",
                    confidence=top_confidence * 0.8,
                    missing_phenomena=[],
                    supporting_phenomenon_ids=[],
                    supporting_ticket_ids=[],
                ),
            ]

        confirmed = [
            ConfirmedPhenomenon(
                phenomenon_id=f"P_confirmed_{i}",
                description=f"Confirmed phenomenon {i}",
                result_summary="confirmed",
            )
            for i in range(confirmed_count)
        ]

        return SessionState(
            session_id="test_session",
            user_problem="test problem",
            active_hypotheses=hypotheses,
            confirmed_phenomena=confirmed,
            denied_phenomenon_ids=[],
            recommended_phenomenon_ids=[],
        )

    def _create_scored_phenomena(self, count: int, root_cause_pattern: list) -> list:
        """
        创建评分后的现象列表

        Args:
            count: 现象数量
            root_cause_pattern: 每个现象关联的根因 ID 列表
                               例如 ["RC1", "RC1", "RC2", "RC1", "RC2"]
        """
        result = []
        for i in range(count):
            root_cause_id = root_cause_pattern[i % len(root_cause_pattern)]
            result.append({
                "phenomenon": MagicMock(phenomenon_id=f"P{i}"),
                "score": 1.0 - i * 0.1,  # 递减得分
                "score_details": {},
                "related_hypotheses": [
                    {"root_cause": root_cause_id, "confidence": 0.5}
                ],
            })
        return result

    # ===== 早期阶段测试 =====

    def test_early_phase_max_one_per_root_cause(self):
        """早期阶段：每根因最多 1 个现象"""
        engine = self._create_mock_engine()
        session = self._create_session(confirmed_count=0)

        # 5 个现象，前 3 个属于 RC1，后 2 个属于 RC2
        scored = self._create_scored_phenomena(5, ["RC1", "RC1", "RC1", "RC2", "RC2"])

        result = engine._apply_diversity_constraint(scored, session, max_count=5)

        # 早期阶段每根因最多 1 个，所以应该选 P0(RC1) 和 P3(RC2)
        assert len(result) == 2
        assert result[0]["phenomenon"].phenomenon_id == "P0"
        assert result[1]["phenomenon"].phenomenon_id == "P3"

    def test_early_phase_respects_max_count(self):
        """早期阶段：即使有多样性，也尊重 max_count"""
        engine = self._create_mock_engine()
        session = self._create_session(confirmed_count=0)

        # 每个现象属于不同根因
        scored = self._create_scored_phenomena(10, ["RC1", "RC2", "RC3", "RC4", "RC5"] * 2)

        result = engine._apply_diversity_constraint(scored, session, max_count=3)

        # 虽然有 5 个不同根因，但 max_count=3
        assert len(result) == 3

    # ===== 中期阶段测试 =====

    def test_mid_phase_max_two_per_root_cause(self):
        """中期阶段：每根因最多 2 个现象"""
        config = RecommenderConfig(mid_confirmed_threshold=3)
        engine = self._create_mock_engine(config)
        session = self._create_session(confirmed_count=3)  # 刚好进入中期

        # 6 个现象，全部属于 RC1
        scored = self._create_scored_phenomena(6, ["RC1"])

        result = engine._apply_diversity_constraint(scored, session, max_count=5)

        # 中期阶段每根因最多 2 个
        assert len(result) == 2
        assert result[0]["phenomenon"].phenomenon_id == "P0"
        assert result[1]["phenomenon"].phenomenon_id == "P1"

    def test_mid_phase_mixed_root_causes(self):
        """中期阶段：混合根因"""
        config = RecommenderConfig(mid_confirmed_threshold=3)
        engine = self._create_mock_engine(config)
        session = self._create_session(confirmed_count=4)

        # 交替 RC1 和 RC2
        scored = self._create_scored_phenomena(6, ["RC1", "RC2"])

        result = engine._apply_diversity_constraint(scored, session, max_count=5)

        # 每根因最多 2 个，所以 RC1: P0, P2; RC2: P1, P3
        assert len(result) == 4

    # ===== 晚期阶段测试 =====

    def test_late_phase_no_diversity_constraint(self):
        """晚期阶段：不应用多样性约束"""
        config = RecommenderConfig(high_confidence_threshold=0.8)
        engine = self._create_mock_engine(config)
        session = self._create_session(top_confidence=0.85)  # 高置信度

        # 5 个现象全属于 RC1
        scored = self._create_scored_phenomena(5, ["RC1"])

        result = engine._apply_diversity_constraint(scored, session, max_count=5)

        # 晚期阶段不限制，返回全部
        assert len(result) == 5

    # ===== 边界情况测试 =====

    def test_empty_input(self):
        """空输入"""
        engine = self._create_mock_engine()
        session = self._create_session()

        result = engine._apply_diversity_constraint([], session, max_count=5)

        assert result == []

    def test_no_hypotheses_in_session(self):
        """会话中没有假设"""
        engine = self._create_mock_engine()
        session = self._create_session(hypotheses=[])

        scored = self._create_scored_phenomena(3, ["RC1", "RC2", "RC3"])

        result = engine._apply_diversity_constraint(scored, session, max_count=5)

        # 没有假设时，top_confidence = 0，进入早期阶段
        assert len(result) <= 3

    def test_phenomenon_without_related_hypotheses(self):
        """现象没有关联假设"""
        engine = self._create_mock_engine()
        session = self._create_session(confirmed_count=0)

        scored = [
            {
                "phenomenon": MagicMock(phenomenon_id="P0"),
                "score": 1.0,
                "score_details": {},
                "related_hypotheses": [],  # 没有关联假设
            },
            {
                "phenomenon": MagicMock(phenomenon_id="P1"),
                "score": 0.9,
                "score_details": {},
                "related_hypotheses": [{"root_cause": "RC1", "confidence": 0.5}],
            },
        ]

        result = engine._apply_diversity_constraint(scored, session, max_count=5)

        # P0 没有关联假设，应该直接加入
        assert len(result) == 2
        assert result[0]["phenomenon"].phenomenon_id == "P0"
        assert result[1]["phenomenon"].phenomenon_id == "P1"

    def test_custom_config_values(self):
        """自定义配置值"""
        config = RecommenderConfig(
            early_max_per_root_cause=2,
            mid_max_per_root_cause=3,
            mid_confirmed_threshold=5,
        )
        engine = self._create_mock_engine(config)
        session = self._create_session(confirmed_count=2)  # 早期

        # 6 个现象全属于 RC1
        scored = self._create_scored_phenomena(6, ["RC1"])

        result = engine._apply_diversity_constraint(scored, session, max_count=5)

        # 自定义早期 max=2
        assert len(result) == 2
