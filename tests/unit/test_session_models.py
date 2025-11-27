"""Session 模型单元测试"""
import pytest
from pathlib import Path
import sys
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.models import (
    Hypothesis,
    DialogueMessage,
    SessionState,
    ConfirmedPhenomenon,
    DeniedPhenomenon,
    RecommendedPhenomenon,
)


class TestHypothesis:
    def test_create_hypothesis(self):
        hyp = Hypothesis(
            root_cause_id="RC-0001",
            confidence=0.75,
            missing_phenomena=["需要确认查询执行计划"],
            supporting_phenomenon_ids=["P-0001", "P-0002"],
            supporting_ticket_ids=["TICKET-001"],
        )
        assert hyp.root_cause_id == "RC-0001"
        assert hyp.confidence == 0.75
        assert len(hyp.missing_phenomena) == 1

    def test_hypothesis_default_values(self):
        hyp = Hypothesis(root_cause_id="RC-0001", confidence=0.5)
        assert hyp.missing_phenomena == []
        assert hyp.supporting_phenomenon_ids == []
        assert hyp.next_recommended_phenomenon_id is None


class TestConfirmedPhenomenon:
    def test_create_confirmed_phenomenon(self):
        cp = ConfirmedPhenomenon(
            phenomenon_id="P-0001",
            result_summary="确认 wait_io 占比 65%",
        )
        assert cp.phenomenon_id == "P-0001"
        assert cp.confirmed_at is not None


class TestDeniedPhenomenon:
    def test_create_denied_phenomenon(self):
        dp = DeniedPhenomenon(phenomenon_id="P-0003", reason="正常")
        assert dp.phenomenon_id == "P-0003"
        assert dp.reason == "正常"

    def test_denied_phenomenon_without_reason(self):
        dp = DeniedPhenomenon(phenomenon_id="P-0004")
        assert dp.reason is None


class TestRecommendedPhenomenon:
    def test_create_recommended_phenomenon(self):
        rp = RecommendedPhenomenon(phenomenon_id="P-0001", round_number=1)
        assert rp.phenomenon_id == "P-0001"
        assert rp.round_number == 1


class TestSessionState:
    def test_create_minimal_session(self):
        session = SessionState(
            session_id="sess_001",
            user_problem="查询性能下降",
        )
        assert session.session_id == "sess_001"
        assert len(session.recommended_phenomenon_ids) == 0
        assert len(session.denied_phenomenon_ids) == 0

    def test_create_full_session(self):
        session = SessionState(
            session_id="sess_002",
            user_problem="查询变慢",
            active_hypotheses=[
                Hypothesis(
                    root_cause_id="RC-0001",
                    confidence=0.88,
                    supporting_phenomenon_ids=["P-0001", "P-0002"],
                )
            ],
            denied_phenomena=[
                DeniedPhenomenon(phenomenon_id="P-0003", reason="正常"),
            ],
            recommended_phenomena=[
                RecommendedPhenomenon(phenomenon_id="P-0001", round_number=1),
            ],
        )
        assert len(session.recommended_phenomenon_ids) == 1
        assert len(session.denied_phenomenon_ids) == 1

    def test_session_serialization_roundtrip(self):
        original = SessionState(
            session_id="sess_005",
            user_problem="死锁问题",
            active_hypotheses=[
                Hypothesis(
                    root_cause_id="RC-0003",
                    confidence=0.7,
                    missing_phenomena=["事务隔离级别"],
                )
            ],
        )
        session_dict = original.to_dict()
        restored = SessionState.from_dict(session_dict)
        assert restored.session_id == original.session_id
        assert restored.active_hypotheses[0].root_cause_id == "RC-0003"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
