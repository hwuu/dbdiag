"""RARSessionState 单元测试"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.core.rar_session_state import RARSessionState


class TestRARSessionState:
    """RAR 会话状态测试"""

    def test_create_session_state(self):
        """测试:创建会话状态"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        assert state.session_id == "test-001"
        assert state.user_problem == "查询变慢"
        assert state.dialogue_turns == 0
        assert state.confirmed_observations == []
        assert state.denied_observations == []
        assert state.asked_observations == []
        assert state.relevant_ticket_ids == set()

    def test_confirm_observation(self):
        """测试:确认观察"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        state.confirm_observation("wait_io 事件占比高")

        assert "wait_io 事件占比高" in state.confirmed_observations
        assert "wait_io 事件占比高" in state.asked_observations

    def test_deny_observation(self):
        """测试:否定观察"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        state.deny_observation("CPU 使用率高")

        assert "CPU 使用率高" in state.denied_observations
        assert "CPU 使用率高" in state.asked_observations

    def test_add_asked_observation(self):
        """测试:添加已问过的观察"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        state.add_asked_observation("索引膨胀")

        assert "索引膨胀" in state.asked_observations
        assert "索引膨胀" not in state.confirmed_observations
        assert "索引膨胀" not in state.denied_observations

    def test_add_relevant_ticket_ids(self):
        """测试:添加相关工单ID"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        state.add_relevant_ticket_ids(["T-0001", "T-0002"])

        assert "T-0001" in state.relevant_ticket_ids
        assert "T-0002" in state.relevant_ticket_ids

    def test_increment_turn(self):
        """测试:增加对话轮次"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        assert state.dialogue_turns == 0

        state.increment_turn()
        assert state.dialogue_turns == 1

        state.increment_turn()
        assert state.dialogue_turns == 2

    def test_is_observation_asked(self):
        """测试:判断观察是否已问过"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        assert not state.is_observation_asked("wait_io 高")

        state.add_asked_observation("wait_io 高")
        assert state.is_observation_asked("wait_io 高")

    def test_get_status_summary(self):
        """测试:获取状态摘要"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        state.confirm_observation("wait_io 高")
        state.deny_observation("CPU 高")
        state.increment_turn()

        summary = state.get_status_summary()

        assert "已确认" in summary
        assert "wait_io 高" in summary
        assert "已否定" in summary
        assert "CPU 高" in summary

    def test_to_dict(self):
        """测试:序列化为字典"""
        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        state.confirm_observation("wait_io 高")
        state.add_relevant_ticket_ids(["T-0001"])

        data = state.to_dict()

        assert data["session_id"] == "test-001"
        assert data["user_problem"] == "查询变慢"
        assert "wait_io 高" in data["confirmed_observations"]
        assert "T-0001" in data["relevant_ticket_ids"]

    def test_from_dict(self):
        """测试:从字典反序列化"""
        data = {
            "session_id": "test-001",
            "user_problem": "查询变慢",
            "dialogue_turns": 2,
            "confirmed_observations": ["wait_io 高"],
            "denied_observations": ["CPU 高"],
            "asked_observations": ["wait_io 高", "CPU 高"],
            "relevant_ticket_ids": ["T-0001"],
        }

        state = RARSessionState.from_dict(data)

        assert state.session_id == "test-001"
        assert state.user_problem == "查询变慢"
        assert state.dialogue_turns == 2
        assert "wait_io 高" in state.confirmed_observations
        assert "T-0001" in state.relevant_ticket_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
