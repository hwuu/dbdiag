"""GAR2 数据模型单元测试"""

import pytest
from datetime import datetime

from dbdiag.core.gar2.models import (
    Observation,
    Symptom,
    HypothesisV2,
    SessionStateV2,
    PhenomenonMatch,
    RootCauseMatch,
    TicketMatch,
    MatchResult,
)


class TestObservation:
    """Observation 模型测试"""

    def test_create_observation(self):
        obs = Observation(
            id="obs-001",
            description="wait_io 占比 65%",
            source="user_input",
            matched_phenomenon_id="P-001",
            match_score=0.92,
        )
        assert obs.id == "obs-001"
        assert obs.description == "wait_io 占比 65%"
        assert obs.source == "user_input"
        assert obs.matched_phenomenon_id == "P-001"
        assert obs.match_score == 0.92

    def test_observation_default_values(self):
        obs = Observation(
            id="obs-001",
            description="test",
            source="confirmed",
        )
        assert obs.matched_phenomenon_id is None
        assert obs.match_score == 0.0
        assert isinstance(obs.created_at, datetime)


class TestSymptom:
    """Symptom 模型测试"""

    def test_add_observation(self):
        symptom = Symptom()
        obs = symptom.add_observation(
            description="wait_io 占比 65%",
            source="user_input",
            matched_phenomenon_id="P-001",
            match_score=0.92,
        )
        assert obs.id == "obs-001"
        assert len(symptom.observations) == 1
        assert symptom.observations[0].description == "wait_io 占比 65%"

    def test_add_multiple_observations(self):
        symptom = Symptom()
        obs1 = symptom.add_observation("观察1", "user_input")
        obs2 = symptom.add_observation("观察2", "confirmed")
        assert obs1.id == "obs-001"
        assert obs2.id == "obs-002"
        assert len(symptom.observations) == 2

    def test_block_phenomenon(self):
        symptom = Symptom()
        symptom.block_phenomenon("P-001", ["RC-001", "RC-002"])

        assert symptom.is_phenomenon_blocked("P-001")
        assert not symptom.is_phenomenon_blocked("P-002")
        assert symptom.is_root_cause_blocked("RC-001")
        assert symptom.is_root_cause_blocked("RC-002")
        assert not symptom.is_root_cause_blocked("RC-003")

    def test_get_matched_phenomenon_ids(self):
        symptom = Symptom()
        symptom.add_observation("obs1", "user_input", "P-001", 0.9)
        symptom.add_observation("obs2", "confirmed", "P-002", 1.0)
        symptom.add_observation("obs3", "user_input")  # 无匹配

        matched = symptom.get_matched_phenomenon_ids()
        assert matched == {"P-001", "P-002"}

    def test_get_observation_by_phenomenon(self):
        symptom = Symptom()
        symptom.add_observation("obs1", "user_input", "P-001", 0.9)
        symptom.add_observation("obs2", "confirmed", "P-002", 1.0)

        obs = symptom.get_observation_by_phenomenon("P-001")
        assert obs is not None
        assert obs.description == "obs1"

        obs = symptom.get_observation_by_phenomenon("P-999")
        assert obs is None

    def test_update_observation(self):
        symptom = Symptom()
        symptom.add_observation("原始描述", "user_input")

        success = symptom.update_observation(
            "obs-001",
            description="更新后的描述",
            match_score=0.85,
        )
        assert success
        assert symptom.observations[0].description == "更新后的描述"
        assert symptom.observations[0].match_score == 0.85

    def test_update_observation_not_found(self):
        symptom = Symptom()
        success = symptom.update_observation("obs-999", description="test")
        assert not success

    def test_remove_observation(self):
        symptom = Symptom()
        symptom.add_observation("obs1", "user_input")
        symptom.add_observation("obs2", "confirmed")

        success = symptom.remove_observation("obs-001")
        assert success
        assert len(symptom.observations) == 1
        assert symptom.observations[0].id == "obs-002"

    def test_remove_observation_not_found(self):
        symptom = Symptom()
        success = symptom.remove_observation("obs-999")
        assert not success


class TestHypothesisV2:
    """HypothesisV2 模型测试"""

    def test_create_hypothesis(self):
        hyp = HypothesisV2(
            root_cause_id="RC-001",
            confidence=0.85,
            contributing_observations=["obs-001", "obs-002"],
            contributing_phenomena=["P-001", "P-002"],
        )
        assert hyp.root_cause_id == "RC-001"
        assert hyp.confidence == 0.85
        assert len(hyp.contributing_observations) == 2
        assert len(hyp.contributing_phenomena) == 2

    def test_hypothesis_default_values(self):
        hyp = HypothesisV2(root_cause_id="RC-001")
        assert hyp.confidence == 0.0
        assert hyp.contributing_observations == []
        assert hyp.contributing_phenomena == []


class TestSessionStateV2:
    """SessionStateV2 模型测试"""

    def test_create_session(self):
        session = SessionStateV2(
            session_id="test-session",
            user_problem="查询变慢",
        )
        assert session.session_id == "test-session"
        assert session.user_problem == "查询变慢"
        assert session.observation_count == 0
        assert session.blocked_count == 0
        assert session.top_hypothesis is None

    def test_session_with_hypotheses(self):
        session = SessionStateV2(
            session_id="test",
            hypotheses=[
                HypothesisV2(root_cause_id="RC-001", confidence=0.85),
                HypothesisV2(root_cause_id="RC-002", confidence=0.65),
            ],
        )
        assert session.top_hypothesis is not None
        assert session.top_hypothesis.root_cause_id == "RC-001"
        assert session.top_hypothesis.confidence == 0.85

    def test_session_observation_count(self):
        session = SessionStateV2(session_id="test")
        session.symptom.add_observation("obs1", "user_input")
        session.symptom.add_observation("obs2", "confirmed")
        assert session.observation_count == 2

    def test_session_blocked_count(self):
        session = SessionStateV2(session_id="test")
        session.symptom.block_phenomenon("P-001", ["RC-001", "RC-002"])
        assert session.blocked_count == 2


class TestMatchResult:
    """MatchResult 模型测试"""

    def test_create_match_result_empty(self):
        result = MatchResult()
        assert result.phenomena == []
        assert result.root_causes == []
        assert result.tickets == []
        assert result.best_phenomenon is None
        assert not result.has_matches

    def test_create_match_result_with_matches(self):
        result = MatchResult(
            phenomena=[
                PhenomenonMatch(phenomenon_id="P-001", score=0.92),
                PhenomenonMatch(phenomenon_id="P-002", score=0.85),
            ],
            root_causes=[
                RootCauseMatch(root_cause_id="RC-001", score=0.88),
            ],
            tickets=[
                TicketMatch(ticket_id="T-001", root_cause_id="RC-001", score=0.80),
            ],
        )
        assert len(result.phenomena) == 2
        assert len(result.root_causes) == 1
        assert len(result.tickets) == 1
        assert result.has_matches

    def test_best_phenomenon(self):
        result = MatchResult(
            phenomena=[
                PhenomenonMatch(phenomenon_id="P-001", score=0.85),
                PhenomenonMatch(phenomenon_id="P-002", score=0.92),
                PhenomenonMatch(phenomenon_id="P-003", score=0.78),
            ],
        )
        best = result.best_phenomenon
        assert best is not None
        assert best.phenomenon_id == "P-002"
        assert best.score == 0.92

    def test_has_matches_only_root_causes(self):
        result = MatchResult(
            root_causes=[RootCauseMatch(root_cause_id="RC-001", score=0.88)],
        )
        assert result.has_matches
        assert result.best_phenomenon is None

    def test_has_matches_only_tickets(self):
        result = MatchResult(
            tickets=[TicketMatch(ticket_id="T-001", root_cause_id="RC-001", score=0.80)],
        )
        assert result.has_matches
        assert result.best_phenomenon is None


class TestPhenomenonMatch:
    """PhenomenonMatch 模型测试"""

    def test_create_phenomenon_match(self):
        match = PhenomenonMatch(phenomenon_id="P-001", score=0.92)
        assert match.phenomenon_id == "P-001"
        assert match.score == 0.92


class TestRootCauseMatch:
    """RootCauseMatch 模型测试"""

    def test_create_root_cause_match(self):
        match = RootCauseMatch(root_cause_id="RC-001", score=0.88)
        assert match.root_cause_id == "RC-001"
        assert match.score == 0.88


class TestTicketMatch:
    """TicketMatch 模型测试"""

    def test_create_ticket_match(self):
        match = TicketMatch(
            ticket_id="T-001",
            root_cause_id="RC-001",
            score=0.80,
        )
        assert match.ticket_id == "T-001"
        assert match.root_cause_id == "RC-001"
        assert match.score == 0.80
