"""置信度计算器单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from dbdiag.core.gar2.models import Symptom, HypothesisV2
from dbdiag.core.gar2.confidence_calculator import ConfidenceCalculator


class TestConfidenceCalculator:
    """ConfidenceCalculator 测试"""

    def _create_mock_calculator(
        self,
        phenomenon_root_causes: dict = None,
        root_cause_phenomena: dict = None,
    ):
        """创建带 mock 的置信度计算器

        Args:
            phenomenon_root_causes: {phenomenon_id: {root_cause_id: ticket_count}}
            root_cause_phenomena: {root_cause_id: [phenomenon_ids]}
        """
        phenomenon_root_causes = phenomenon_root_causes or {}
        root_cause_phenomena = root_cause_phenomena or {}

        with patch.object(ConfidenceCalculator, "__init__", lambda self, *args: None):
            calc = ConfidenceCalculator.__new__(ConfidenceCalculator)
            calc._phenomenon_root_cause_dao = MagicMock()
            calc._root_cause_dao = MagicMock()

            # Mock get_root_causes_with_ticket_count
            def get_rc_with_count(pid):
                return phenomenon_root_causes.get(pid, {})

            calc._phenomenon_root_cause_dao.get_root_causes_with_ticket_count = get_rc_with_count

            # Mock get_phenomena_by_root_cause_id
            def get_phenomena_by_rc(rc_id):
                return set(root_cause_phenomena.get(rc_id, []))

            calc._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id = get_phenomena_by_rc

            # Mock get_root_causes_by_phenomenon_id
            def get_rc_by_phenomenon(pid):
                return set(phenomenon_root_causes.get(pid, {}).keys())

            calc._phenomenon_root_cause_dao.get_root_causes_by_phenomenon_id = get_rc_by_phenomenon

        return calc

    def test_empty_symptom(self):
        """空症状返回空假设列表"""
        calc = self._create_mock_calculator()
        symptom = Symptom()
        hypotheses = calc.calculate(symptom)
        assert hypotheses == []

    def test_single_observation_single_root_cause(self):
        """单个观察对应单个根因"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={"P-001": {"RC-001": 5}},
            root_cause_phenomena={"RC-001": ["P-001"]},
        )

        symptom = Symptom()
        symptom.add_observation(
            "wait_io 高",
            "confirmed",
            matched_phenomenon_id="P-001",
            match_score=1.0,
        )

        hypotheses = calc.calculate(symptom)
        assert len(hypotheses) == 1
        assert hypotheses[0].root_cause_id == "RC-001"
        assert hypotheses[0].confidence == 1.0  # 1 / 1

    def test_partial_match_score(self):
        """部分匹配度影响置信度"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={"P-001": {"RC-001": 5}},
            root_cause_phenomena={"RC-001": ["P-001"]},
        )

        symptom = Symptom()
        symptom.add_observation(
            "wait_io 似乎有点高",
            "user_input",
            matched_phenomenon_id="P-001",
            match_score=0.8,
        )

        hypotheses = calc.calculate(symptom)
        assert len(hypotheses) == 1
        assert hypotheses[0].confidence == 0.8  # 0.8 / 1

    def test_multiple_observations_same_root_cause(self):
        """多个观察对应同一根因"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={
                "P-001": {"RC-001": 5},
                "P-002": {"RC-001": 3},
            },
            root_cause_phenomena={"RC-001": ["P-001", "P-002"]},
        )

        symptom = Symptom()
        symptom.add_observation("obs1", "confirmed", "P-001", 1.0)
        symptom.add_observation("obs2", "confirmed", "P-002", 1.0)

        hypotheses = calc.calculate(symptom)
        assert len(hypotheses) == 1
        assert hypotheses[0].root_cause_id == "RC-001"
        # weight(P-001) = 5/5 = 1.0, weight(P-002) = 3/5 = 0.6
        # raw_score = 1.0 * 1.0 + 1.0 * 0.6 = 1.6
        # confidence = 1.6 / 2 = 0.8
        assert 0.7 < hypotheses[0].confidence < 0.9

    def test_multiple_root_causes_sorted(self):
        """多个根因按置信度排序"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={
                "P-001": {"RC-001": 5, "RC-002": 2},
            },
            root_cause_phenomena={
                "RC-001": ["P-001"],
                "RC-002": ["P-001", "P-002", "P-003"],  # 更多现象，置信度更低
            },
        )

        symptom = Symptom()
        symptom.add_observation("obs1", "confirmed", "P-001", 1.0)

        hypotheses = calc.calculate(symptom)
        assert len(hypotheses) == 2
        # RC-001 应该排在前面（归一化后置信度更高）
        assert hypotheses[0].root_cause_id == "RC-001"
        assert hypotheses[0].confidence > hypotheses[1].confidence

    def test_blocked_root_cause_excluded(self):
        """被阻塞的根因不参与计算"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={
                "P-001": {"RC-001": 5, "RC-002": 3},
            },
            root_cause_phenomena={
                "RC-001": ["P-001"],
                "RC-002": ["P-001"],
            },
        )

        symptom = Symptom()
        symptom.add_observation("obs1", "confirmed", "P-001", 1.0)
        symptom.block_phenomenon("P-999", ["RC-002"])  # 阻塞 RC-002

        hypotheses = calc.calculate(symptom)
        assert len(hypotheses) == 1
        assert hypotheses[0].root_cause_id == "RC-001"

    def test_observation_without_match_ignored(self):
        """未匹配的观察被忽略"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={"P-001": {"RC-001": 5}},
            root_cause_phenomena={"RC-001": ["P-001"]},
        )

        symptom = Symptom()
        symptom.add_observation("未匹配的观察", "user_input")  # 无 matched_phenomenon_id
        symptom.add_observation("匹配的观察", "confirmed", "P-001", 1.0)

        hypotheses = calc.calculate(symptom)
        assert len(hypotheses) == 1
        assert len(hypotheses[0].contributing_observations) == 1

    def test_contributing_details(self):
        """记录贡献的观察和现象"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={
                "P-001": {"RC-001": 5},
                "P-002": {"RC-001": 3},
            },
            root_cause_phenomena={"RC-001": ["P-001", "P-002"]},
        )

        symptom = Symptom()
        obs1 = symptom.add_observation("obs1", "confirmed", "P-001", 1.0)
        obs2 = symptom.add_observation("obs2", "confirmed", "P-002", 0.9)

        hypotheses = calc.calculate(symptom)
        assert len(hypotheses) == 1
        assert set(hypotheses[0].contributing_observations) == {obs1.id, obs2.id}
        assert set(hypotheses[0].contributing_phenomena) == {"P-001", "P-002"}

    def test_get_related_root_causes(self):
        """获取现象关联的根因"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={"P-001": {"RC-001": 5, "RC-002": 3}},
        )

        related = calc.get_related_root_causes("P-001")
        assert set(related) == {"RC-001", "RC-002"}
