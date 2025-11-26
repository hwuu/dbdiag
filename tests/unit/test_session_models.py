"""Session 模型单元测试"""
import pytest
from pathlib import Path
import sys
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.models.session import (
    Hypothesis,
    DialogueMessage,
    SessionState,
    ConfirmedPhenomenon,
)


class TestHypothesis:
    """Hypothesis 模型测试"""

    def test_create_hypothesis(self):
        """测试:创建假设"""
        hyp = Hypothesis(
            root_cause="缺少索引",
            confidence=0.75,
            missing_facts=["需要确认查询执行计划"],
            supporting_phenomenon_ids=["P-0001", "P-0002"],
            supporting_ticket_ids=["TICKET-001"],
        )

        assert hyp.root_cause == "缺少索引"
        assert hyp.confidence == 0.75
        assert len(hyp.missing_facts) == 1
        assert len(hyp.supporting_phenomenon_ids) == 2
        assert hyp.next_recommended_phenomenon_id is None

    def test_hypothesis_with_recommended_phenomenon(self):
        """测试:带推荐现象的假设"""
        hyp = Hypothesis(
            root_cause="连接泄漏",
            confidence=0.6,
            missing_facts=["连接池配置"],
            supporting_phenomenon_ids=["P-0003"],
            next_recommended_phenomenon_id="P-0004",
        )

        assert hyp.next_recommended_phenomenon_id == "P-0004"

    def test_confidence_range_validation(self):
        """测试:置信度范围"""
        # 有效的置信度
        hyp1 = Hypothesis(
            root_cause="测试",
            confidence=0.0,
            missing_facts=[],
        )
        assert hyp1.confidence == 0.0

        hyp2 = Hypothesis(
            root_cause="测试",
            confidence=1.0,
            missing_facts=[],
        )
        assert hyp2.confidence == 1.0

    def test_hypothesis_default_values(self):
        """测试:字段默认值"""
        hyp = Hypothesis(
            root_cause="测试",
            confidence=0.5,
            missing_facts=[],
        )

        # 字段应有默认值
        assert hyp.supporting_phenomenon_ids == []
        assert hyp.supporting_ticket_ids == []
        assert hyp.next_recommended_phenomenon_id is None


class TestConfirmedPhenomenon:
    """ConfirmedPhenomenon 模型测试"""

    def test_create_confirmed_phenomenon(self):
        """测试:创建已确认现象"""
        cp = ConfirmedPhenomenon(
            phenomenon_id="P-0001",
            result_summary="确认 wait_io 占比 65%",
        )

        assert cp.phenomenon_id == "P-0001"
        assert cp.result_summary == "确认 wait_io 占比 65%"
        assert cp.confirmed_at is not None

    def test_confirmed_phenomenon_serialization(self):
        """测试:已确认现象序列化"""
        cp = ConfirmedPhenomenon(
            phenomenon_id="P-0002",
            result_summary="索引大小正常",
        )

        cp_dict = cp.model_dump()
        assert cp_dict["phenomenon_id"] == "P-0002"
        assert cp_dict["result_summary"] == "索引大小正常"

        # 从字典创建
        cp2 = ConfirmedPhenomenon(**cp_dict)
        assert cp2.phenomenon_id == cp.phenomenon_id


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
        assert len(session.active_hypotheses) == 0
        assert len(session.dialogue_history) == 0
        assert len(session.confirmed_phenomena) == 0
        assert len(session.recommended_phenomenon_ids) == 0

    def test_create_full_session(self):
        """测试:创建完整会话"""
        session = SessionState(
            session_id="sess_002",
            user_problem="查询变慢",
            active_hypotheses=[
                Hypothesis(
                    root_cause="索引膨胀导致 IO 瓶颈",
                    confidence=0.88,
                    missing_facts=[],
                    supporting_phenomenon_ids=["P-0001", "P-0002"],
                    supporting_ticket_ids=["TICKET-001"],
                )
            ],
            confirmed_phenomena=[
                ConfirmedPhenomenon(
                    phenomenon_id="P-0001",
                    result_summary="确认 wait_io 占比 65%",
                )
            ],
            recommended_phenomenon_ids=["P-0001", "P-0002"],
            dialogue_history=[
                DialogueMessage(role="user", content="查询很慢"),
                DialogueMessage(role="assistant", content="建议检查 IO"),
            ],
        )

        assert session.session_id == "sess_002"
        assert len(session.confirmed_phenomena) == 1
        assert session.confirmed_phenomena[0].phenomenon_id == "P-0001"
        assert len(session.recommended_phenomenon_ids) == 2
        assert session.active_hypotheses[0].supporting_phenomenon_ids == ["P-0001", "P-0002"]
        assert len(session.dialogue_history) == 2

    def test_session_to_dict(self):
        """测试:会话转字典"""
        session = SessionState(
            session_id="sess_003",
            user_problem="CPU 高",
            confirmed_phenomena=[
                ConfirmedPhenomenon(phenomenon_id="P-0001", result_summary="CPU 95%")
            ],
        )

        session_dict = session.to_dict()
        assert session_dict["session_id"] == "sess_003"
        assert session_dict["user_problem"] == "CPU 高"
        assert len(session_dict["confirmed_phenomena"]) == 1

        # 验证可以 JSON 序列化
        json_str = json.dumps(session_dict)
        assert "sess_003" in json_str

    def test_session_from_dict(self):
        """测试:从字典创建会话"""
        session_dict = {
            "session_id": "sess_004",
            "user_problem": "内存泄漏",
            "created_at": datetime.now().isoformat(),
            "active_hypotheses": [],
            "dialogue_history": [],
            "confirmed_phenomena": [],
            "recommended_phenomenon_ids": [],
        }

        session = SessionState.from_dict(session_dict)
        assert session.session_id == "sess_004"
        assert session.user_problem == "内存泄漏"

    def test_session_serialization_roundtrip(self):
        """测试:会话序列化往返"""
        original = SessionState(
            session_id="sess_005",
            user_problem="死锁问题",
            confirmed_phenomena=[
                ConfirmedPhenomenon(phenomenon_id="P-0001", result_summary="发生死锁"),
                ConfirmedPhenomenon(phenomenon_id="P-0002", result_summary="锁等待超时"),
            ],
            active_hypotheses=[
                Hypothesis(
                    root_cause="事务冲突",
                    confidence=0.7,
                    missing_facts=["事务隔离级别"],
                    supporting_phenomenon_ids=["P-0001"],
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
        assert len(restored.confirmed_phenomena) == len(original.confirmed_phenomena)
        assert len(restored.active_hypotheses) == len(original.active_hypotheses)
        assert restored.active_hypotheses[0].root_cause == "事务冲突"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
