"""置信度计算器单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from dbdiag.core.gar2.models import Symptom, HypothesisV2, MatchResult, PhenomenonMatch, TicketMatch
from dbdiag.core.gar2.confidence_calculator import ConfidenceCalculator


class TestConfidenceCalculator:
    """ConfidenceCalculator 测试"""

    def _create_mock_calculator(
        self,
        phenomenon_root_causes: dict = None,
        root_cause_phenomena: dict = None,
        ticket_phenomena_count: dict = None,
    ):
        """创建带 mock 的置信度计算器

        Args:
            phenomenon_root_causes: {phenomenon_id: {root_cause_id: ticket_count}}
            root_cause_phenomena: {root_cause_id: [phenomenon_ids]}
            ticket_phenomena_count: {ticket_id: phenomena_count}
        """
        phenomenon_root_causes = phenomenon_root_causes or {}
        root_cause_phenomena = root_cause_phenomena or {}
        ticket_phenomena_count = ticket_phenomena_count or {}

        with patch.object(ConfidenceCalculator, "__init__", lambda self, *args: None):
            calc = ConfidenceCalculator.__new__(ConfidenceCalculator)
            calc._phenomenon_root_cause_dao = MagicMock()
            calc._root_cause_dao = MagicMock()
            calc._ticket_phenomenon_dao = MagicMock()

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

            # Mock get_phenomena_count_by_ticket_id
            def get_phenomena_count(ticket_id):
                return ticket_phenomena_count.get(ticket_id, 0)

            calc._ticket_phenomenon_dao.get_phenomena_count_by_ticket_id = get_phenomena_count

            # 设置权重常量
            calc.PHENOMENON_WEIGHT = 0.5
            calc.ROOT_CAUSE_WEIGHT = 0.3
            calc.TICKET_WEIGHT = 0.2

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


class TestNormalizationFactor:
    """归一化因子策略测试（方案 B 改进版）"""

    def _create_mock_calculator(
        self,
        phenomenon_root_causes: dict = None,
        root_cause_phenomena: dict = None,
        ticket_phenomena_count: dict = None,
        best_ticket_by_phenomena: dict = None,
    ):
        """创建带 mock 的置信度计算器

        Args:
            best_ticket_by_phenomena: {(frozenset(phenomenon_ids), root_cause_id): ticket_id}
        """
        phenomenon_root_causes = phenomenon_root_causes or {}
        root_cause_phenomena = root_cause_phenomena or {}
        ticket_phenomena_count = ticket_phenomena_count or {}
        best_ticket_by_phenomena = best_ticket_by_phenomena or {}

        with patch.object(ConfidenceCalculator, "__init__", lambda self, *args: None):
            calc = ConfidenceCalculator.__new__(ConfidenceCalculator)
            calc._phenomenon_root_cause_dao = MagicMock()
            calc._root_cause_dao = MagicMock()
            calc._ticket_phenomenon_dao = MagicMock()

            def get_rc_with_count(pid):
                return phenomenon_root_causes.get(pid, {})

            calc._phenomenon_root_cause_dao.get_root_causes_with_ticket_count = get_rc_with_count

            def get_phenomena_by_rc(rc_id):
                return set(root_cause_phenomena.get(rc_id, []))

            calc._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id = get_phenomena_by_rc

            def get_rc_by_phenomenon(pid):
                return set(phenomenon_root_causes.get(pid, {}).keys())

            calc._phenomenon_root_cause_dao.get_root_causes_by_phenomenon_id = get_rc_by_phenomenon

            def get_phenomena_count(ticket_id):
                return ticket_phenomena_count.get(ticket_id, 0)

            calc._ticket_phenomenon_dao.get_phenomena_count_by_ticket_id = get_phenomena_count

            def get_best_ticket(phenomenon_ids, root_cause_id):
                key = (frozenset(phenomenon_ids), root_cause_id)
                return best_ticket_by_phenomena.get(key)

            calc._ticket_phenomenon_dao.get_best_ticket_by_phenomena = get_best_ticket

            calc.PHENOMENON_WEIGHT = 0.5
            calc.ROOT_CAUSE_WEIGHT = 0.3
            calc.TICKET_WEIGHT = 0.2

        return calc

    def test_normalization_uses_ticket_phenomena_count(self):
        """使用最匹配工单的现象数作为归一化因子

        场景：RC-001 关联 10 个现象，但 T-001 只包含 4 个现象
        当用户确认了 T-001 的全部 4 个现象时，置信度应接近 100%
        """
        calc = self._create_mock_calculator(
            phenomenon_root_causes={
                "P-001": {"RC-001": 1},
                "P-002": {"RC-001": 1},
                "P-003": {"RC-001": 1},
                "P-004": {"RC-001": 1},
            },
            root_cause_phenomena={
                # RC-001 总共关联 10 个现象（模拟真实场景）
                "RC-001": ["P-001", "P-002", "P-003", "P-004", "P-005",
                           "P-006", "P-007", "P-008", "P-009", "P-010"],
            },
            ticket_phenomena_count={
                "T-001": 4,  # T-001 只包含 4 个现象
            },
            best_ticket_by_phenomena={
                # 当确认了 P-001~P-004 时，最匹配的工单是 T-001
                (frozenset({"P-001", "P-002", "P-003", "P-004"}), "RC-001"): "T-001",
            },
        )

        # 创建症状：用户确认了 4 个现象
        symptom = Symptom()
        symptom.add_observation("obs1", "confirmed", "P-001", 1.0)
        symptom.add_observation("obs2", "confirmed", "P-002", 1.0)
        symptom.add_observation("obs3", "confirmed", "P-003", 1.0)
        symptom.add_observation("obs4", "confirmed", "P-004", 1.0)

        # 创建匹配结果：包含工单匹配
        match_result = MatchResult(
            phenomena=[
                PhenomenonMatch(phenomenon_id="P-001", score=1.0),
                PhenomenonMatch(phenomenon_id="P-002", score=1.0),
                PhenomenonMatch(phenomenon_id="P-003", score=1.0),
                PhenomenonMatch(phenomenon_id="P-004", score=1.0),
            ],
            tickets=[
                TicketMatch(ticket_id="T-001", root_cause_id="RC-001", score=0.9),
            ],
        )

        hypotheses = calc.calculate_with_match_result(symptom, match_result)

        assert len(hypotheses) == 1
        assert hypotheses[0].root_cause_id == "RC-001"
        # 归一化因子 = T-001 的现象数 × PHENOMENON_WEIGHT = 4 × 0.5 = 2.0
        # 贡献 = 4 × 1.0 × 0.5 = 2.0
        # 置信度 = 2.0 / 2.0 = 100%
        assert hypotheses[0].confidence > 0.9

    def test_normalization_without_ticket_uses_all_phenomena(self):
        """无工单匹配时，使用根因的所有现象数作为归一化因子"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={
                "P-001": {"RC-001": 1},
                "P-002": {"RC-001": 1},
            },
            root_cause_phenomena={
                "RC-001": ["P-001", "P-002", "P-003", "P-004", "P-005"],  # 5 个现象
            },
        )

        symptom = Symptom()
        symptom.add_observation("obs1", "confirmed", "P-001", 1.0)
        symptom.add_observation("obs2", "confirmed", "P-002", 1.0)

        # 无工单匹配
        match_result = MatchResult(
            phenomena=[
                PhenomenonMatch(phenomenon_id="P-001", score=1.0),
                PhenomenonMatch(phenomenon_id="P-002", score=1.0),
            ],
        )

        hypotheses = calc.calculate_with_match_result(symptom, match_result)

        assert len(hypotheses) == 1
        # 归一化因子 = 根因所有现象数 × PHENOMENON_WEIGHT = 5 × 0.5 = 2.5
        # 贡献 = 2 × 1.0 × 0.5 = 1.0（两个现象各贡献 0.5）
        # 置信度 = 1.0 / 2.5 = 0.4
        assert 0.3 < hypotheses[0].confidence < 0.5

    def test_normalization_fallback_to_all_phenomena(self):
        """无工单匹配且无确认现象时，使用根因的所有现象数"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={},
            root_cause_phenomena={
                "RC-001": ["P-001", "P-002", "P-003"],  # 3 个现象
            },
        )

        # 直接测试 _normalize_and_create_hypotheses
        root_cause_scores = {"RC-001": 0.75}  # 模拟贡献分数
        root_cause_observations = {"RC-001": ["obs-1"]}
        root_cause_phenomena = {"RC-001": set()}  # 空集

        hypotheses = calc._normalize_and_create_hypotheses(
            root_cause_scores,
            root_cause_observations,
            root_cause_phenomena,
            best_tickets_by_root_cause=None,
        )

        assert len(hypotheses) == 1
        # 归一化因子 = 根因的所有现象数 × PHENOMENON_WEIGHT = 3 × 0.5 = 1.5
        # 置信度 = 0.75 / 1.5 = 0.5
        assert hypotheses[0].confidence == 0.5

    def test_best_ticket_selection_by_confirmed_phenomena(self):
        """根据已确认现象选择最匹配的工单"""
        calc = self._create_mock_calculator(
            phenomenon_root_causes={
                "P-001": {"RC-001": 1},
            },
            root_cause_phenomena={
                "RC-001": ["P-001", "P-002", "P-003", "P-004", "P-005"],
            },
            ticket_phenomena_count={
                "T-001": 2,  # 包含 P-001 的小工单
                "T-002": 5,  # 不包含 P-001 的大工单
            },
            best_ticket_by_phenomena={
                # 当确认了 P-001 时，T-001 是最匹配的工单（因为它包含 P-001）
                (frozenset({"P-001"}), "RC-001"): "T-001",
            },
        )

        symptom = Symptom()
        symptom.add_observation("obs1", "confirmed", "P-001", 1.0)

        match_result = MatchResult(
            phenomena=[
                PhenomenonMatch(phenomenon_id="P-001", score=1.0),
            ],
        )

        hypotheses = calc.calculate_with_match_result(symptom, match_result)

        assert len(hypotheses) == 1
        # 归一化因子 = T-001 的现象数 × PHENOMENON_WEIGHT = 2 × 0.5 = 1.0
        # 贡献 = 1 × 1.0 × 0.5 = 0.5
        # 置信度 = 0.5 / 1.0 = 50%
        assert 0.4 < hypotheses[0].confidence < 0.6
