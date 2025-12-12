"""GraphEngine 单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from dbdiag.core.agent.models import (
    SessionState,
    DiagnoseInput,
    MatchedPhenomenon,
    QueryRelationsInput,
)
from dbdiag.core.agent.graph_engine import GraphEngine


class TestGraphEngine:
    """GraphEngine 测试"""

    def _create_mock_engine(
        self,
        phenomenon_root_causes: dict = None,
        root_cause_phenomena: dict = None,
        phenomenon_info: dict = None,
        root_cause_info: dict = None,
    ):
        """创建带 mock 的 GraphEngine

        Args:
            phenomenon_root_causes: {phenomenon_id: {root_cause_id: ticket_count}}
            root_cause_phenomena: {root_cause_id: [phenomenon_ids]}
            phenomenon_info: {phenomenon_id: {"description": ..., "observation_method": ...}}
            root_cause_info: {root_cause_id: {"description": ..., "solution": ...}}
        """
        phenomenon_root_causes = phenomenon_root_causes or {}
        root_cause_phenomena = root_cause_phenomena or {}
        phenomenon_info = phenomenon_info or {}
        root_cause_info = root_cause_info or {}

        with patch.object(GraphEngine, "__init__", lambda self, *args: None):
            engine = GraphEngine.__new__(GraphEngine)
            engine._phenomenon_dao = MagicMock()
            engine._root_cause_dao = MagicMock()
            engine._phenomenon_root_cause_dao = MagicMock()
            engine._ticket_phenomenon_dao = MagicMock()

            # Mock get_root_causes_with_ticket_count
            def get_rc_with_count(pid):
                return phenomenon_root_causes.get(pid, {})

            engine._phenomenon_root_cause_dao.get_root_causes_with_ticket_count = get_rc_with_count

            # Mock get_phenomena_by_root_cause_id
            def get_phenomena_by_rc(rc_id):
                return root_cause_phenomena.get(rc_id, [])

            engine._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id = get_phenomena_by_rc

            # Mock get_root_causes_by_phenomenon_id
            def get_rc_by_phenomenon(pid):
                return list(phenomenon_root_causes.get(pid, {}).keys())

            engine._phenomenon_root_cause_dao.get_root_causes_by_phenomenon_id = get_rc_by_phenomenon

            # Mock phenomenon_dao.get_by_id
            def get_phenomenon(pid):
                return phenomenon_info.get(pid)

            engine._phenomenon_dao.get_by_id = get_phenomenon

            # Mock root_cause_dao.get_by_id
            def get_root_cause(rc_id):
                return root_cause_info.get(rc_id)

            engine._root_cause_dao.get_by_id = get_root_cause

        return engine

    def test_diagnose_empty_input(self):
        """空输入返回无假设"""
        engine = self._create_mock_engine()
        session = SessionState(session_id="test")
        input = DiagnoseInput()

        output, new_session = engine.diagnose(session, input)

        assert output.diagnosis_complete is False
        assert len(output.hypotheses) == 0
        assert output.diagnosis is None

    def test_diagnose_single_phenomenon(self):
        """单个现象生成假设"""
        engine = self._create_mock_engine(
            phenomenon_root_causes={
                "P-0001": {"RC-0001": 5},
            },
            root_cause_phenomena={
                "RC-0001": ["P-0001"],
            },
            root_cause_info={
                "RC-0001": {"description": "索引膨胀", "solution": "执行 VACUUM"},
            },
        )

        session = SessionState(session_id="test")
        input = DiagnoseInput(
            confirmed_phenomena=[
                MatchedPhenomenon(
                    phenomenon_id="P-0001",
                    phenomenon_description="wait_io 高",
                    user_observation="IO 很高",
                    match_score=1.0,
                ),
            ],
        )

        output, new_session = engine.diagnose(session, input)

        assert len(output.hypotheses) == 1
        assert output.hypotheses[0].root_cause_id == "RC-0001"
        assert output.hypotheses[0].confidence == 1.0  # 1.0 / 1 = 1.0

    def test_diagnose_partial_match_score(self):
        """部分匹配度影响置信度"""
        engine = self._create_mock_engine(
            phenomenon_root_causes={
                "P-0001": {"RC-0001": 5},
            },
            root_cause_phenomena={
                "RC-0001": ["P-0001"],
            },
            root_cause_info={
                "RC-0001": {"description": "索引膨胀"},
            },
        )

        session = SessionState(session_id="test")
        input = DiagnoseInput(
            confirmed_phenomena=[
                MatchedPhenomenon(
                    phenomenon_id="P-0001",
                    phenomenon_description="wait_io 高",
                    user_observation="IO 似乎有点高",
                    match_score=0.8,
                ),
            ],
        )

        output, new_session = engine.diagnose(session, input)

        assert len(output.hypotheses) == 1
        assert output.hypotheses[0].confidence == 0.8

    def test_diagnose_multiple_phenomena_same_root_cause(self):
        """多个现象对应同一根因"""
        engine = self._create_mock_engine(
            phenomenon_root_causes={
                "P-0001": {"RC-0001": 5},
                "P-0002": {"RC-0001": 5},
            },
            root_cause_phenomena={
                "RC-0001": ["P-0001", "P-0002"],
            },
            root_cause_info={
                "RC-0001": {"description": "索引膨胀"},
            },
        )

        session = SessionState(session_id="test")
        input = DiagnoseInput(
            confirmed_phenomena=[
                MatchedPhenomenon(
                    phenomenon_id="P-0001",
                    phenomenon_description="wait_io 高",
                    user_observation="IO 高",
                    match_score=1.0,
                ),
                MatchedPhenomenon(
                    phenomenon_id="P-0002",
                    phenomenon_description="索引增长",
                    user_observation="索引很大",
                    match_score=1.0,
                ),
            ],
        )

        output, new_session = engine.diagnose(session, input)

        assert len(output.hypotheses) == 1
        assert output.hypotheses[0].root_cause_id == "RC-0001"
        # 2 个现象 / 2 总现象数 = 1.0
        assert output.hypotheses[0].confidence == 1.0

    def test_diagnose_high_confidence_complete(self):
        """高置信度触发诊断完成"""
        engine = self._create_mock_engine(
            phenomenon_root_causes={
                "P-0001": {"RC-0001": 5},
            },
            root_cause_phenomena={
                "RC-0001": ["P-0001"],
            },
            root_cause_info={
                "RC-0001": {"description": "索引膨胀", "solution": "执行 VACUUM FULL"},
            },
        )

        session = SessionState(session_id="test")
        input = DiagnoseInput(
            confirmed_phenomena=[
                MatchedPhenomenon(
                    phenomenon_id="P-0001",
                    phenomenon_description="wait_io 高",
                    user_observation="IO 很高",
                    match_score=1.0,
                ),
            ],
        )

        output, new_session = engine.diagnose(session, input)

        # 置信度 1.0 >= 0.95，应触发完成
        assert output.diagnosis_complete is True
        assert output.diagnosis is not None
        assert output.diagnosis.root_cause_id == "RC-0001"
        assert output.diagnosis.solution == "执行 VACUUM FULL"

    def test_diagnose_generates_recommendations(self):
        """未完成诊断时生成推荐"""
        engine = self._create_mock_engine(
            phenomenon_root_causes={
                "P-0001": {"RC-0001": 5},
            },
            root_cause_phenomena={
                "RC-0001": ["P-0001", "P-0002", "P-0003"],  # 3 个现象
            },
            root_cause_info={
                "RC-0001": {"description": "索引膨胀"},
            },
            phenomenon_info={
                "P-0002": {"description": "磁盘 IOPS 高", "observation_method": "检查 iostat"},
                "P-0003": {"description": "表空间增长", "observation_method": "检查 pg_stat_user_tables"},
            },
        )

        session = SessionState(session_id="test")
        input = DiagnoseInput(
            confirmed_phenomena=[
                MatchedPhenomenon(
                    phenomenon_id="P-0001",
                    phenomenon_description="wait_io 高",
                    user_observation="IO 高",
                    match_score=0.5,  # 低匹配度，置信度不足
                ),
            ],
        )

        output, new_session = engine.diagnose(session, input)

        # 置信度 0.5 / 3 = 0.167，未达到阈值
        assert output.diagnosis_complete is False
        assert len(output.recommendations) > 0

    def test_diagnose_updates_session(self):
        """诊断更新会话状态"""
        engine = self._create_mock_engine(
            phenomenon_root_causes={
                "P-0001": {"RC-0001": 5},
            },
            root_cause_phenomena={
                "RC-0001": ["P-0001"],
            },
            root_cause_info={
                "RC-0001": {"description": "索引膨胀"},
            },
        )

        session = SessionState(session_id="test", rounds=0)
        input = DiagnoseInput(
            confirmed_phenomena=[
                MatchedPhenomenon(
                    phenomenon_id="P-0001",
                    phenomenon_description="wait_io 高",
                    user_observation="IO 高",
                    match_score=1.0,
                ),
            ],
        )

        output, new_session = engine.diagnose(session, input)

        # 验证会话更新
        assert new_session.rounds == 1
        assert len(new_session.confirmed_observations) == 1
        assert new_session.confirmed_observations[0].phenomenon_id == "P-0001"

    def test_diagnose_denied_phenomena(self):
        """否认的现象被记录到会话"""
        engine = self._create_mock_engine()

        session = SessionState(session_id="test")
        input = DiagnoseInput(
            denied_phenomena=["P-0001", "P-0002"],
        )

        output, new_session = engine.diagnose(session, input)

        assert "P-0001" in new_session.denied_phenomenon_ids
        assert "P-0002" in new_session.denied_phenomenon_ids


class TestQueryProgress:
    """query_progress 测试"""

    def _create_mock_engine(self):
        with patch.object(GraphEngine, "__init__", lambda self, *args: None):
            engine = GraphEngine.__new__(GraphEngine)
            engine._phenomenon_dao = MagicMock()
            engine._root_cause_dao = MagicMock()
            engine._phenomenon_root_cause_dao = MagicMock()
            engine._ticket_phenomenon_dao = MagicMock()
        return engine

    def test_query_progress_initial(self):
        """初始状态"""
        engine = self._create_mock_engine()
        session = SessionState(session_id="test")

        output = engine.query_progress(session)

        assert output.rounds == 0
        assert output.confirmed_count == 0
        assert output.status == "exploring"

    def test_query_progress_with_hypotheses(self):
        """有假设时的状态"""
        from dbdiag.core.agent.models import Hypothesis

        engine = self._create_mock_engine()
        session = SessionState(
            session_id="test",
            rounds=3,
            hypotheses=[
                Hypothesis(
                    root_cause_id="RC-0001",
                    root_cause_description="索引膨胀",
                    confidence=0.72,
                ),
            ],
        )

        output = engine.query_progress(session)

        assert output.rounds == 3
        assert output.top_hypothesis == "索引膨胀"
        assert output.top_confidence == 0.72
        assert output.status == "narrowing"  # 0.5 <= 0.72 < 0.95


class TestQueryRelations:
    """query_relations 测试"""

    def _create_mock_engine(
        self,
        phenomenon_root_causes: dict = None,
        root_cause_phenomena: dict = None,
        phenomenon_info: dict = None,
        root_cause_info: dict = None,
    ):
        phenomenon_root_causes = phenomenon_root_causes or {}
        root_cause_phenomena = root_cause_phenomena or {}
        phenomenon_info = phenomenon_info or {}
        root_cause_info = root_cause_info or {}

        with patch.object(GraphEngine, "__init__", lambda self, *args: None):
            engine = GraphEngine.__new__(GraphEngine)
            engine._phenomenon_dao = MagicMock()
            engine._root_cause_dao = MagicMock()
            engine._phenomenon_root_cause_dao = MagicMock()
            engine._ticket_phenomenon_dao = MagicMock()

            def get_rc_with_count(pid):
                return phenomenon_root_causes.get(pid, {})

            engine._phenomenon_root_cause_dao.get_root_causes_with_ticket_count = get_rc_with_count

            def get_phenomena_by_rc(rc_id):
                return root_cause_phenomena.get(rc_id, [])

            engine._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id = get_phenomena_by_rc

            def get_rc_by_phenomenon(pid):
                return list(phenomenon_root_causes.get(pid, {}).keys())

            engine._phenomenon_root_cause_dao.get_root_causes_by_phenomenon_id = get_rc_by_phenomenon

            def get_phenomenon(pid):
                return phenomenon_info.get(pid)

            engine._phenomenon_dao.get_by_id = get_phenomenon

            def get_root_cause(rc_id):
                return root_cause_info.get(rc_id)

            engine._root_cause_dao.get_by_id = get_root_cause

        return engine

    def test_query_phenomenon_to_root_causes(self):
        """查询现象关联的根因"""
        engine = self._create_mock_engine(
            phenomenon_root_causes={
                "P-0001": {"RC-0001": 10, "RC-0002": 5},
            },
            phenomenon_info={
                "P-0001": {"description": "wait_io 高"},
            },
            root_cause_info={
                "RC-0001": {"description": "索引膨胀"},
                "RC-0002": {"description": "锁等待"},
            },
        )

        input = QueryRelationsInput(
            query_type="phenomenon_to_root_causes",
            phenomenon_id="P-0001",
        )

        output = engine.query_relations(input)

        assert output.query_type == "phenomenon_to_root_causes"
        assert output.source_entity_id == "P-0001"
        assert len(output.results) == 2

    def test_query_root_cause_to_phenomena(self):
        """查询根因关联的现象"""
        engine = self._create_mock_engine(
            phenomenon_root_causes={
                "P-0001": {"RC-0001": 10},
                "P-0002": {"RC-0001": 5},
            },
            root_cause_phenomena={
                "RC-0001": ["P-0001", "P-0002"],
            },
            root_cause_info={
                "RC-0001": {"description": "索引膨胀"},
            },
            phenomenon_info={
                "P-0001": {"description": "wait_io 高"},
                "P-0002": {"description": "索引增长"},
            },
        )

        input = QueryRelationsInput(
            query_type="root_cause_to_phenomena",
            root_cause_id="RC-0001",
        )

        output = engine.query_relations(input)

        assert output.query_type == "root_cause_to_phenomena"
        assert output.source_entity_id == "RC-0001"
        assert len(output.results) == 2
