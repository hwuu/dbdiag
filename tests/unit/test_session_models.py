"""Session 模型单元测试"""
import pytest
from pathlib import Path
import sys
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.models.session import (
    ConfirmedFact,
    Hypothesis,
    ExecutedStep,
    DialogueMessage,
    SessionState,
)


class TestConfirmedFact:
    """ConfirmedFact 模型测试"""

    def test_create_fact_from_user(self):
        """测试:创建用户提供的事实"""
        fact = ConfirmedFact(
            fact="CPU 使用率 95%",
            from_user_input=True,
        )

        assert fact.fact == "CPU 使用率 95%"
        assert fact.from_user_input is True
        assert fact.step_id is None
        assert fact.timestamp is not None

    def test_create_fact_from_system(self):
        """测试:创建系统观察的事实"""
        fact = ConfirmedFact(
            fact="查询执行时间超过 10 秒",
            from_user_input=False,
            step_id="step_001",
            observation_result="EXPLAIN ANALYZE 显示全表扫描",
        )

        assert fact.from_user_input is False
        assert fact.step_id == "step_001"
        assert fact.observation_result == "EXPLAIN ANALYZE 显示全表扫描"

    def test_fact_serialization(self):
        """测试:事实序列化"""
        fact = ConfirmedFact(
            fact="内存使用正常",
            from_user_input=True,
        )

        # 转为字典
        fact_dict = fact.model_dump()
        assert fact_dict["fact"] == "内存使用正常"

        # 从字典创建
        fact2 = ConfirmedFact(**fact_dict)
        assert fact2.fact == fact.fact


class TestHypothesis:
    """Hypothesis 模型测试"""

    def test_create_hypothesis(self):
        """测试:创建假设"""
        hyp = Hypothesis(
            root_cause="缺少索引",
            confidence=0.75,
            supporting_step_ids=["step_001", "step_002"],
            missing_facts=["需要确认查询执行计划"],
        )

        assert hyp.root_cause == "缺少索引"
        assert hyp.confidence == 0.75
        assert len(hyp.supporting_step_ids) == 2
        assert len(hyp.missing_facts) == 1
        assert hyp.next_recommended_step_id is None

    def test_hypothesis_with_recommended_step(self):
        """测试:带推荐步骤的假设"""
        hyp = Hypothesis(
            root_cause="连接泄漏",
            confidence=0.6,
            supporting_step_ids=["step_003"],
            missing_facts=["连接池配置"],
            next_recommended_step_id="step_004",
        )

        assert hyp.next_recommended_step_id == "step_004"

    def test_confidence_range_validation(self):
        """测试:置信度范围"""
        # 有效的置信度
        hyp1 = Hypothesis(
            root_cause="测试",
            confidence=0.0,
            supporting_step_ids=[],
            missing_facts=[],
        )
        assert hyp1.confidence == 0.0

        hyp2 = Hypothesis(
            root_cause="测试",
            confidence=1.0,
            supporting_step_ids=[],
            missing_facts=[],
        )
        assert hyp2.confidence == 1.0


class TestExecutedStep:
    """ExecutedStep 模型测试"""

    def test_create_executed_step(self):
        """测试:创建已执行步骤"""
        step = ExecutedStep(
            step_id="step_001",
            result_summary="查询执行计划显示全表扫描",
        )

        assert step.step_id == "step_001"
        assert step.result_summary == "查询执行计划显示全表扫描"
        assert step.executed_at is not None


class TestDialogueMessage:
    """DialogueMessage 模型测试"""

    def test_create_user_message(self):
        """测试:创建用户消息"""
        msg = DialogueMessage(
            role="user",
            content="数据库查询很慢",
        )

        assert msg.role == "user"
        assert msg.content == "数据库查询很慢"
        assert msg.timestamp is not None

    def test_create_assistant_message(self):
        """测试:创建助手消息"""
        msg = DialogueMessage(
            role="assistant",
            content="建议检查查询执行计划",
        )

        assert msg.role == "assistant"


class TestSessionState:
    """SessionState 模型测试"""

    def test_create_minimal_session(self):
        """测试:创建最小会话"""
        session = SessionState(
            session_id="sess_001",
            user_problem="查询性能下降",
        )

        assert session.session_id == "sess_001"
        assert session.user_problem == "查询性能下降"
        assert session.created_at is not None
        assert len(session.confirmed_facts) == 0
        assert len(session.active_hypotheses) == 0
        assert len(session.executed_steps) == 0
        assert len(session.dialogue_history) == 0

    def test_create_full_session(self):
        """测试:创建完整会话"""
        session = SessionState(
            session_id="sess_002",
            user_problem="连接数过多",
            confirmed_facts=[
                ConfirmedFact(fact="连接数 500", from_user_input=True)
            ],
            active_hypotheses=[
                Hypothesis(
                    root_cause="连接泄漏",
                    confidence=0.8,
                    supporting_step_ids=["step_001"],
                    missing_facts=["连接池配置"],
                )
            ],
            executed_steps=[
                ExecutedStep(step_id="step_001", result_summary="已检查连接数")
            ],
            dialogue_history=[
                DialogueMessage(role="user", content="连接数很多"),
                DialogueMessage(role="assistant", content="建议检查连接池"),
            ],
        )

        assert len(session.confirmed_facts) == 1
        assert len(session.active_hypotheses) == 1
        assert len(session.executed_steps) == 1
        assert len(session.dialogue_history) == 2

    def test_session_to_dict(self):
        """测试:会话转字典"""
        session = SessionState(
            session_id="sess_003",
            user_problem="CPU 高",
            confirmed_facts=[
                ConfirmedFact(fact="CPU 95%", from_user_input=True)
            ],
        )

        session_dict = session.to_dict()
        assert session_dict["session_id"] == "sess_003"
        assert session_dict["user_problem"] == "CPU 高"
        assert len(session_dict["confirmed_facts"]) == 1

        # 验证可以 JSON 序列化
        json_str = json.dumps(session_dict)
        assert "sess_003" in json_str

    def test_session_from_dict(self):
        """测试:从字典创建会话"""
        session_dict = {
            "session_id": "sess_004",
            "user_problem": "内存泄漏",
            "created_at": datetime.now().isoformat(),
            "confirmed_facts": [],
            "active_hypotheses": [],
            "executed_steps": [],
            "dialogue_history": [],
        }

        session = SessionState.from_dict(session_dict)
        assert session.session_id == "sess_004"
        assert session.user_problem == "内存泄漏"

    def test_session_serialization_roundtrip(self):
        """测试:会话序列化往返"""
        original = SessionState(
            session_id="sess_005",
            user_problem="死锁问题",
            confirmed_facts=[
                ConfirmedFact(fact="发生死锁", from_user_input=True),
                ConfirmedFact(fact="锁等待超时", from_user_input=False),
            ],
            active_hypotheses=[
                Hypothesis(
                    root_cause="事务冲突",
                    confidence=0.7,
                    supporting_step_ids=["step_001"],
                    missing_facts=["事务隔离级别"],
                )
            ],
        )

        # 转为字典
        session_dict = original.to_dict()

        # 从字典恢复
        restored = SessionState.from_dict(session_dict)

        # 验证数据一致
        assert restored.session_id == original.session_id
        assert restored.user_problem == original.user_problem
        assert len(restored.confirmed_facts) == len(original.confirmed_facts)
        assert len(restored.active_hypotheses) == len(original.active_hypotheses)
        assert restored.active_hypotheses[0].root_cause == "事务冲突"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
