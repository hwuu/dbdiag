"""Agent 数据模型单元测试"""

import pytest
from datetime import datetime

from dbdiag.core.agent.models import (
    ToolOutput,
    ConfirmedObservation,
    SessionState,
    RawObservation,
    MatchPhenomenaInput,
    MatchPhenomenaOutput,
    CandidatePhenomenon,
    MatchedPhenomenon,
    InterpretedObservation,
    ClarificationOption,
    DiagnoseInput,
    DiagnoseOutput,
    Hypothesis,
    Recommendation,
    Diagnosis,
    QueryProgressOutput,
    QueryHypothesesInput,
    QueryHypothesesOutput,
    HypothesisDetail,
    QueryRelationsInput,
    QueryRelationsOutput,
    GraphRelation,
    CallResult,
    CallError,
    ResponseDetails,
    AgentResponse,
    AgentDecision,
)


class TestToolOutput:
    """ToolOutput 模型测试"""

    def test_create_success(self):
        output = ToolOutput(success=True)
        assert output.success is True
        assert output.error_message is None

    def test_create_failure(self):
        output = ToolOutput(success=False, error_message="测试错误")
        assert output.success is False
        assert output.error_message == "测试错误"


class TestConfirmedObservation:
    """ConfirmedObservation 模型测试"""

    def test_create_observation(self):
        obs = ConfirmedObservation(
            phenomenon_id="P-0001",
            phenomenon_description="wait_io 占比高",
            user_observation="IO 很高",
            match_score=0.85,
        )
        assert obs.phenomenon_id == "P-0001"
        assert obs.phenomenon_description == "wait_io 占比高"
        assert obs.user_observation == "IO 很高"
        assert obs.match_score == 0.85
        assert isinstance(obs.confirmed_at, datetime)


class TestSessionState:
    """SessionState 模型测试"""

    def test_create_session(self):
        session = SessionState(
            session_id="test-session",
            user_problem="数据库慢",
        )
        assert session.session_id == "test-session"
        assert session.user_problem == "数据库慢"
        assert session.confirmed_count == 0
        assert session.denied_count == 0
        assert session.top_hypothesis is None

    def test_session_with_observations(self):
        session = SessionState(
            session_id="test",
            confirmed_observations=[
                ConfirmedObservation(
                    phenomenon_id="P-0001",
                    phenomenon_description="test",
                    user_observation="test",
                    match_score=0.9,
                ),
                ConfirmedObservation(
                    phenomenon_id="P-0002",
                    phenomenon_description="test2",
                    user_observation="test2",
                    match_score=0.8,
                ),
            ],
        )
        assert session.confirmed_count == 2
        assert session.get_confirmed_phenomenon_ids() == {"P-0001", "P-0002"}

    def test_session_denied_phenomena(self):
        session = SessionState(
            session_id="test",
            denied_phenomenon_ids={"P-0003", "P-0004"},
        )
        assert session.denied_count == 2
        assert session.is_phenomenon_denied("P-0003")
        assert not session.is_phenomenon_denied("P-0001")

    def test_session_with_hypotheses(self):
        session = SessionState(
            session_id="test",
            hypotheses=[
                Hypothesis(
                    root_cause_id="RC-0001",
                    root_cause_description="索引膨胀",
                    confidence=0.85,
                ),
                Hypothesis(
                    root_cause_id="RC-0002",
                    root_cause_description="锁等待",
                    confidence=0.65,
                ),
            ],
        )
        assert session.top_hypothesis is not None
        assert session.top_hypothesis.root_cause_id == "RC-0001"
        assert session.top_hypothesis.confidence == 0.85


class TestHypothesis:
    """Hypothesis 模型测试"""

    def test_create_hypothesis(self):
        hyp = Hypothesis(
            root_cause_id="RC-0001",
            root_cause_description="索引膨胀",
            confidence=0.85,
            contributing_phenomena=["P-0001", "P-0002"],
        )
        assert hyp.root_cause_id == "RC-0001"
        assert hyp.root_cause_description == "索引膨胀"
        assert hyp.confidence == 0.85
        assert len(hyp.contributing_phenomena) == 2


class TestRecommendation:
    """Recommendation 模型测试"""

    def test_create_recommendation(self):
        rec = Recommendation(
            phenomenon_id="P-0005",
            description="磁盘 IOPS 高",
            observation_method="检查 iostat",
            reason="与 2 个假设相关",
            related_hypotheses=["RC-0001", "RC-0002"],
            information_gain=0.6,
        )
        assert rec.phenomenon_id == "P-0005"
        assert rec.information_gain == 0.6


class TestDiagnosis:
    """Diagnosis 模型测试"""

    def test_create_diagnosis(self):
        diag = Diagnosis(
            root_cause_id="RC-0001",
            root_cause_description="索引膨胀",
            confidence=0.95,
            observed_phenomena=["wait_io 高", "索引增长"],
            solution="执行 VACUUM FULL",
            reference_tickets=["T-001", "T-002"],
            reasoning="基于 2 个现象的贝叶斯推理",
        )
        assert diag.root_cause_id == "RC-0001"
        assert diag.confidence == 0.95
        assert len(diag.observed_phenomena) == 2


class TestMatchPhenomenaModels:
    """现象匹配相关模型测试"""

    def test_raw_observation(self):
        obs = RawObservation(
            description="IO 很高",
            context="用户在回应上轮推荐",
        )
        assert obs.description == "IO 很高"
        assert obs.context == "用户在回应上轮推荐"

    def test_candidate_phenomenon(self):
        candidate = CandidatePhenomenon(
            phenomenon_id="P-0012",
            description="wait_io 占比高",
            observation_method="执行 top",
            similarity_score=0.88,
        )
        assert candidate.phenomenon_id == "P-0012"
        assert candidate.similarity_score == 0.88

    def test_matched_phenomenon(self):
        matched = MatchedPhenomenon(
            phenomenon_id="P-0012",
            phenomenon_description="wait_io 占比高",
            user_observation="IO 很高",
            match_score=0.88,
            extracted_value="65%",
        )
        assert matched.phenomenon_id == "P-0012"
        assert matched.match_score == 0.88
        assert matched.extracted_value == "65%"

    def test_clarification_option(self):
        option = ClarificationOption(
            phenomenon_id="P-0031",
            description="查询响应时间长",
            observation_method="检查慢查询日志",
        )
        assert option.phenomenon_id == "P-0031"

    def test_interpreted_observation_matched(self):
        interp = InterpretedObservation(
            raw_description="IO 很高",
            matched_phenomenon=MatchedPhenomenon(
                phenomenon_id="P-0012",
                phenomenon_description="wait_io 占比高",
                user_observation="IO 很高",
                match_score=0.88,
            ),
        )
        assert not interp.needs_clarification
        assert interp.matched_phenomenon is not None

    def test_interpreted_observation_needs_clarification(self):
        interp = InterpretedObservation(
            raw_description="数据库有点慢",
            needs_clarification=True,
            clarification_question="你说的'慢'是指哪种情况？",
            clarification_options=[
                ClarificationOption(
                    phenomenon_id="P-0031",
                    description="查询响应时间长",
                    observation_method="检查慢查询日志",
                ),
            ],
        )
        assert interp.needs_clarification
        assert len(interp.clarification_options) == 1


class TestDiagnoseModels:
    """诊断相关模型测试"""

    def test_diagnose_input(self):
        input = DiagnoseInput(
            confirmed_phenomena=[
                MatchedPhenomenon(
                    phenomenon_id="P-0001",
                    phenomenon_description="test",
                    user_observation="test",
                    match_score=0.9,
                ),
            ],
            denied_phenomena=["P-0003"],
        )
        assert len(input.confirmed_phenomena) == 1
        assert len(input.denied_phenomena) == 1

    def test_diagnose_output_incomplete(self):
        output = DiagnoseOutput(
            diagnosis_complete=False,
            hypotheses=[
                Hypothesis(
                    root_cause_id="RC-0001",
                    root_cause_description="索引膨胀",
                    confidence=0.72,
                ),
            ],
            recommendations=[
                Recommendation(
                    phenomenon_id="P-0005",
                    description="磁盘 IOPS 高",
                    observation_method="检查 iostat",
                    reason="与假设相关",
                    information_gain=0.5,
                ),
            ],
        )
        assert not output.diagnosis_complete
        assert output.diagnosis is None

    def test_diagnose_output_complete(self):
        output = DiagnoseOutput(
            diagnosis_complete=True,
            hypotheses=[
                Hypothesis(
                    root_cause_id="RC-0001",
                    root_cause_description="索引膨胀",
                    confidence=0.95,
                ),
            ],
            diagnosis=Diagnosis(
                root_cause_id="RC-0001",
                root_cause_description="索引膨胀",
                confidence=0.95,
            ),
        )
        assert output.diagnosis_complete
        assert output.diagnosis is not None


class TestQueryModels:
    """查询相关模型测试"""

    def test_query_progress_output(self):
        output = QueryProgressOutput(
            rounds=3,
            confirmed_count=5,
            denied_count=2,
            hypotheses_count=4,
            top_hypothesis="索引膨胀",
            top_confidence=0.72,
            status="narrowing",
            status_description="置信度 72%，正在缩小范围",
        )
        assert output.rounds == 3
        assert output.status == "narrowing"

    def test_hypothesis_detail(self):
        detail = HypothesisDetail(
            root_cause_id="RC-0001",
            root_cause_description="索引膨胀",
            confidence=0.85,
            rank=1,
            contributing_phenomena=["P-0001", "P-0002"],
            missing_phenomena=["磁盘 IOPS 高"],
            related_tickets=["T-001"],
        )
        assert detail.rank == 1
        assert len(detail.contributing_phenomena) == 2

    def test_graph_relation(self):
        relation = GraphRelation(
            entity_id="RC-0001",
            entity_description="索引膨胀",
            relation_strength=0.8,
            supporting_ticket_count=15,
        )
        assert relation.entity_id == "RC-0001"
        assert relation.relation_strength == 0.8


class TestAgentDecision:
    """AgentDecision 模型测试"""

    def test_decision_call(self):
        decision = AgentDecision(
            decision="call",
            tool="diagnose",
            tool_input={"confirmed_phenomena": []},
            reasoning="需要执行诊断",
        )
        assert decision.decision == "call"
        assert decision.tool == "diagnose"

    def test_decision_respond(self):
        decision = AgentDecision(
            decision="respond",
            response_context={"type": "diagnosis_result"},
            reasoning="诊断完成，需要回复用户",
        )
        assert decision.decision == "respond"
        assert decision.response_context is not None


class TestAgentResponse:
    """AgentResponse 模型测试"""

    def test_agent_response_simple(self):
        response = AgentResponse(
            message="好的，已记录你的反馈。目前最可能是索引膨胀（72%）。",
        )
        assert response.message is not None
        assert response.details is None

    def test_agent_response_with_details(self):
        response = AgentResponse(
            message="诊断完成",
            details=ResponseDetails(
                status="confirming",
                top_hypothesis="索引膨胀",
                top_confidence=0.95,
                diagnosis=Diagnosis(
                    root_cause_id="RC-0001",
                    root_cause_description="索引膨胀",
                    confidence=0.95,
                ),
            ),
        )
        assert response.details is not None
        assert response.details.diagnosis is not None
