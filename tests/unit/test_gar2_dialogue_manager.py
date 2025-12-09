"""GAR2 对话管理器单元测试"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from dbdiag.core.gar2.models import (
    MatchResult, PhenomenonMatch, RootCauseMatch, TicketMatch
)


class TestGAR2DialogueManager:
    """GAR2DialogueManager 测试"""

    def _create_mock_manager(
        self,
        phenomena: dict = None,
        phenomenon_root_causes: dict = None,
        root_causes: dict = None,
    ):
        """创建带 mock 的对话管理器

        Args:
            phenomena: {phenomenon_id: {"description": ..., "observation_method": ...}}
            phenomenon_root_causes: {phenomenon_id: {root_cause_id: ticket_count}}
            root_causes: {root_cause_id: {"description": ..., "solution": ...}}
        """
        phenomena = phenomena or {}
        phenomenon_root_causes = phenomenon_root_causes or {}
        root_causes = root_causes or {}

        with patch("dbdiag.core.gar2.dialogue_manager.GAR2DialogueManager.__init__", lambda self, *args, **kwargs: None):
            from dbdiag.core.gar2.dialogue_manager import GAR2DialogueManager
            manager = GAR2DialogueManager.__new__(GAR2DialogueManager)

            # Mock 服务
            manager.llm_service = MagicMock()
            manager.embedding_service = MagicMock()
            manager._progress_callback = None

            # Mock DAO
            manager._phenomenon_dao = MagicMock()
            manager._phenomenon_root_cause_dao = MagicMock()
            manager._root_cause_dao = MagicMock()

            # Mock 子模块
            manager.intent_classifier = MagicMock()
            manager.observation_matcher = MagicMock()
            manager.confidence_calculator = MagicMock()

            # Mock phenomenon DAO
            def get_phenomenon(pid):
                return phenomena.get(pid)
            manager._phenomenon_dao.get_by_id = get_phenomenon

            # Mock root_cause DAO
            def get_root_cause(rcid):
                return root_causes.get(rcid)
            manager._root_cause_dao.get_by_id = get_root_cause

            # Mock phenomenon_root_cause DAO
            def get_phenomena_by_rc(rcid):
                result = []
                for pid, rcs in phenomenon_root_causes.items():
                    if rcid in rcs:
                        result.append(pid)
                return result
            manager._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id = get_phenomena_by_rc

            def get_rc_with_count(pid):
                return phenomenon_root_causes.get(pid, {})
            manager._phenomenon_root_cause_dao.get_root_causes_with_ticket_count = get_rc_with_count

            # 会话
            manager.session = None

        return manager

    # ===== start_conversation =====

    def test_start_conversation_creates_session(self):
        """start_conversation 创建新会话"""
        from dbdiag.core.intent.models import UserIntent

        manager = self._create_mock_manager()
        manager.intent_classifier.classify.return_value = UserIntent(
            new_observations=["数据库很慢"]
        )
        manager.observation_matcher.match_all.return_value = MatchResult()
        manager.confidence_calculator.calculate.return_value = []
        manager.confidence_calculator.calculate_with_match_result.return_value = []

        response = manager.start_conversation("数据库很慢")

        assert manager.session is not None
        assert manager.session.user_problem == "数据库很慢"
        assert manager.session.turn_count == 1

    def test_start_conversation_matches_observation(self):
        """start_conversation 匹配用户输入到现象"""
        from dbdiag.core.intent.models import UserIntent

        manager = self._create_mock_manager(
            phenomena={"P-001": {"description": "慢查询"}},
            phenomenon_root_causes={"P-001": {"RC-001": 5}},
        )
        manager.intent_classifier.classify.return_value = UserIntent(
            new_observations=["数据库很慢"]
        )
        match_result = MatchResult(
            phenomena=[PhenomenonMatch(phenomenon_id="P-001", score=0.85)],
        )
        manager.observation_matcher.match_all.return_value = match_result
        manager.confidence_calculator.calculate_with_match_result.return_value = []

        manager.start_conversation("数据库很慢")

        assert len(manager.session.symptom.observations) == 1
        obs = manager.session.symptom.observations[0]
        assert obs.matched_phenomenon_id == "P-001"
        assert obs.match_score == 0.85

    def test_start_conversation_unmatched_observation(self):
        """start_conversation 处理未匹配的观察"""
        from dbdiag.core.intent.models import UserIntent

        manager = self._create_mock_manager()
        manager.intent_classifier.classify.return_value = UserIntent(
            new_observations=["未知问题"]
        )
        manager.observation_matcher.match_all.return_value = MatchResult()
        manager.confidence_calculator.calculate.return_value = []

        manager.start_conversation("未知问题")

        assert len(manager.session.symptom.observations) == 1
        obs = manager.session.symptom.observations[0]
        assert obs.matched_phenomenon_id is None
        assert obs.match_score == 0.0

    def test_start_conversation_query_intent_guides_user(self):
        """start_conversation query 意图返回引导信息"""
        from dbdiag.core.intent.models import UserIntent, IntentType, QueryType

        manager = self._create_mock_manager()
        manager.intent_classifier.classify.return_value = UserIntent(
            intent_type=IntentType.QUERY,
            query_type=QueryType.PROGRESS,
        )

        response = manager.start_conversation("现在进行到哪里了？")

        assert response["action"] == "guide"
        assert "尚未开始诊断" in response["message"]

    def test_start_conversation_empty_feedback_guides_user(self):
        """start_conversation 无实质内容返回引导信息"""
        from dbdiag.core.intent.models import UserIntent, IntentType

        manager = self._create_mock_manager()
        manager.intent_classifier.classify.return_value = UserIntent(
            intent_type=IntentType.FEEDBACK,
            confirmations=["P-001"],  # 第一轮没有推荐，确认无意义
            new_observations=[],
        )

        response = manager.start_conversation("1确认")

        assert response["action"] == "guide"
        assert "请描述" in response["message"]

    # ===== continue_conversation =====

    def test_continue_conversation_no_session(self):
        """continue_conversation 无会话返回错误"""
        manager = self._create_mock_manager()
        manager.session = None

        response = manager.continue_conversation("确认")

        assert response["action"] == "error"

    def test_continue_conversation_increments_turn(self):
        """continue_conversation 增加轮次"""
        from dbdiag.core.gar2.models import SessionStateV2
        from dbdiag.core.intent.models import UserIntent

        manager = self._create_mock_manager()
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )
        manager.session.turn_count = 1

        manager.intent_classifier.classify.return_value = UserIntent()
        manager.confidence_calculator.calculate.return_value = []

        manager.continue_conversation("确认")

        assert manager.session.turn_count == 2

    # ===== _handle_confirmation =====

    def test_handle_confirmation_adds_observation(self):
        """确认现象添加观察到症状"""
        from dbdiag.core.gar2.models import SessionStateV2

        manager = self._create_mock_manager(
            phenomena={"P-001": {"description": "慢查询"}},
        )
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )

        manager._handle_confirmation("P-001")

        assert len(manager.session.symptom.observations) == 1
        obs = manager.session.symptom.observations[0]
        assert obs.matched_phenomenon_id == "P-001"
        assert obs.match_score == 1.0
        assert obs.source == "confirmed"

    def test_handle_confirmation_unknown_phenomenon(self):
        """确认未知现象不添加观察"""
        from dbdiag.core.gar2.models import SessionStateV2

        manager = self._create_mock_manager()
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )

        manager._handle_confirmation("P-UNKNOWN")

        assert len(manager.session.symptom.observations) == 0

    # ===== _handle_denial =====

    def test_handle_denial_blocks_phenomenon(self):
        """否认现象阻塞现象和相关根因"""
        from dbdiag.core.gar2.models import SessionStateV2

        manager = self._create_mock_manager()
        manager.confidence_calculator.get_related_root_causes.return_value = ["RC-001", "RC-002"]
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )

        manager._handle_denial("P-001")

        assert "P-001" in manager.session.symptom.blocked_phenomenon_ids
        assert "RC-001" in manager.session.symptom.blocked_root_cause_ids
        assert "RC-002" in manager.session.symptom.blocked_root_cause_ids

    # ===== _calculate_and_decide =====

    def test_calculate_and_decide_high_confidence_diagnose(self):
        """高置信度触发诊断"""
        from dbdiag.core.gar2.models import SessionStateV2, HypothesisV2

        manager = self._create_mock_manager(
            phenomena={"P-001": {"description": "观察1"}},
            root_causes={"RC-001": {"description": "磁盘故障", "solution": "更换磁盘"}},
        )
        manager._ticket_dao = MagicMock()
        manager._ticket_dao.get_by_root_cause_id.return_value = []
        manager.llm_service = MagicMock()
        manager.llm_service.generate_simple.return_value = "推导过程"
        manager.db_path = ":memory:"

        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )
        manager.session.symptom.add_observation("观察1", "confirmed", "P-001", 1.0)

        hyp = HypothesisV2(
            root_cause_id="RC-001",
            confidence=0.96,  # 超过 0.95 阈值
            contributing_phenomena=["P-001"],
        )
        manager.confidence_calculator.calculate.return_value = [hyp]

        response = manager._calculate_and_decide()

        assert response["action"] == "diagnose"
        assert response["root_cause_id"] == "RC-001"
        assert response["confidence"] == 0.96
        assert "reasoning" in response
        assert "unconfirmed_phenomena" in response
        assert "supporting_tickets" in response

    def test_calculate_and_decide_low_confidence_recommend(self):
        """低置信度推荐现象"""
        from dbdiag.core.gar2.models import SessionStateV2, HypothesisV2

        manager = self._create_mock_manager(
            phenomena={
                "P-001": {"description": "慢查询", "observation_method": "查看日志"},
                "P-002": {"description": "CPU高", "observation_method": "top"},
            },
            phenomenon_root_causes={
                "P-001": {"RC-001": 5},
                "P-002": {"RC-001": 3},
            },
        )
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )

        hyp = HypothesisV2(
            root_cause_id="RC-001",
            confidence=0.4,
            contributing_phenomena=["P-001"],
        )
        manager.confidence_calculator.calculate.return_value = [hyp]
        manager._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id.return_value = ["P-001", "P-002"]

        response = manager._calculate_and_decide()

        assert response["action"] == "recommend"
        assert len(response["recommendations"]) >= 1

    def test_calculate_and_decide_no_hypotheses_ask_more(self):
        """无假设请求更多信息"""
        from dbdiag.core.gar2.models import SessionStateV2

        manager = self._create_mock_manager()
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )
        manager.confidence_calculator.calculate.return_value = []

        response = manager._calculate_and_decide()

        assert response["action"] == "ask_more_info"

    # ===== _generate_recommendation =====

    def test_generate_recommendation_skips_matched(self):
        """推荐跳过已匹配的现象"""
        from dbdiag.core.gar2.models import SessionStateV2, HypothesisV2

        manager = self._create_mock_manager(
            phenomena={
                "P-001": {"description": "慢查询"},
                "P-002": {"description": "CPU高"},
            },
            phenomenon_root_causes={
                "P-001": {"RC-001": 5},
                "P-002": {"RC-001": 3},
            },
        )
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )
        # P-001 已匹配
        manager.session.symptom.add_observation("观察1", "confirmed", "P-001", 1.0)
        manager.session.hypotheses = [
            HypothesisV2(root_cause_id="RC-001", confidence=0.5)
        ]

        response = manager._generate_recommendation()

        recommended_ids = [r["phenomenon_id"] for r in response["recommendations"]]
        assert "P-001" not in recommended_ids
        assert "P-002" in recommended_ids

    def test_generate_recommendation_skips_blocked(self):
        """推荐跳过已阻塞的现象"""
        from dbdiag.core.gar2.models import SessionStateV2, HypothesisV2

        manager = self._create_mock_manager(
            phenomena={
                "P-001": {"description": "慢查询"},
                "P-002": {"description": "CPU高"},
            },
            phenomenon_root_causes={
                "P-001": {"RC-001": 5},
                "P-002": {"RC-001": 3},
            },
        )
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )
        # P-001 已阻塞
        manager.session.symptom.block_phenomenon("P-001", [])
        manager.session.hypotheses = [
            HypothesisV2(root_cause_id="RC-001", confidence=0.5)
        ]

        response = manager._generate_recommendation()

        recommended_ids = [r["phenomenon_id"] for r in response["recommendations"]]
        assert "P-001" not in recommended_ids
        assert "P-002" in recommended_ids

    # ===== get_session / reset =====

    def test_get_session(self):
        """get_session 返回当前会话"""
        from dbdiag.core.gar2.models import SessionStateV2

        manager = self._create_mock_manager()
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )

        assert manager.get_session() == manager.session

    def test_reset(self):
        """reset 清除会话"""
        from dbdiag.core.gar2.models import SessionStateV2

        manager = self._create_mock_manager()
        manager.session = SessionStateV2(
            session_id="test",
            user_problem="测试",
        )

        manager.reset()

        assert manager.session is None
