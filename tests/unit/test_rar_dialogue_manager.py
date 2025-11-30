"""RARDialogueManager 单元测试"""
import pytest
import sqlite3
import tempfile
import os
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.scripts.init_db import init_database
from dbdiag.models.rar import RARSessionState


class TestRARDialogueManager:
    """RAR 对话管理器测试"""

    @pytest.fixture
    def temp_db_with_data(self):
        """创建带数据的临时数据库"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            # 插入测试数据到 rar_raw_tickets
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Mock embedding (768 维)
            import struct
            mock_embedding_1 = struct.pack("768f", *([0.1] * 768))
            mock_embedding_2 = struct.pack("768f", *([0.2] * 768))

            cursor.executemany(
                """
                INSERT INTO rar_raw_tickets
                (ticket_id, description, root_cause, solution, combined_text, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "T-0001",
                        "查询变慢，wait_io 事件占比高",
                        "索引膨胀",
                        "REINDEX",
                        "问题描述: 查询变慢\n根因: 索引膨胀\n解决方案: REINDEX",
                        mock_embedding_1,
                    ),
                    (
                        "T-0002",
                        "连接数过多导致性能下降",
                        "连接泄露",
                        "检查连接池配置",
                        "问题描述: 连接数过多\n根因: 连接泄露\n解决方案: 检查连接池",
                        mock_embedding_2,
                    ),
                ],
            )
            conn.commit()
            conn.close()

            yield db_path

    @pytest.fixture
    def mock_services(self):
        """创建 mock 服务"""
        mock_llm = Mock()
        mock_embedding = Mock()
        mock_embedding.encode.return_value = [0.1] * 768
        return mock_llm, mock_embedding

    def test_start_session(self, temp_db_with_data, mock_services):
        """测试:启动新会话"""
        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        mock_llm, mock_embedding = mock_services
        manager = RARDialogueManager(temp_db_with_data, mock_llm, mock_embedding)

        session_id = manager.start_session("查询变慢")

        assert session_id is not None
        assert manager.state.user_problem == "查询变慢"
        assert manager.state.dialogue_turns == 0

    def test_process_message_recommend(self, temp_db_with_data, mock_services):
        """测试:处理消息返回推荐"""
        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        mock_llm, mock_embedding = mock_services

        # Mock LLM 返回推荐模式
        mock_llm.generate_simple.return_value = json.dumps({
            "action": "recommend",
            "confidence": 0.45,
            "reasoning": "需要更多信息",
            "recommendations": [
                {
                    "observation": "wait_io 事件占比",
                    "method": "SELECT wait_event_type FROM pg_stat_activity",
                    "why": "高 IO 等待通常与索引膨胀相关",
                    "related_root_causes": ["索引膨胀"]
                }
            ]
        })

        manager = RARDialogueManager(temp_db_with_data, mock_llm, mock_embedding)
        manager.start_session("查询变慢")

        response = manager.process_message("有什么异常吗？")

        assert response is not None
        assert response["action"] == "recommend"
        assert len(response["recommendations"]) >= 1

    def test_process_message_diagnose(self, temp_db_with_data, mock_services):
        """测试:处理消息返回诊断"""
        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        mock_llm, mock_embedding = mock_services

        # Mock LLM 返回诊断模式
        mock_llm.generate_simple.return_value = json.dumps({
            "action": "diagnose",
            "confidence": 0.85,
            "root_cause": "索引膨胀",
            "reasoning": "用户确认了 wait_io 高",
            "observed_phenomena": ["wait_io 占比 65%"],
            "solution": "REINDEX",
            "cited_tickets": ["T-0001"]
        })

        manager = RARDialogueManager(temp_db_with_data, mock_llm, mock_embedding)
        manager.start_session("查询变慢")

        response = manager.process_message("wait_io 确实很高")

        assert response is not None
        assert response["action"] == "diagnose"
        assert "root_cause" in response

    def test_increment_turn_on_process(self, temp_db_with_data, mock_services):
        """测试:处理消息后轮次增加"""
        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        mock_llm, mock_embedding = mock_services
        mock_llm.generate_simple.return_value = json.dumps({
            "action": "recommend",
            "confidence": 0.3,
            "reasoning": "需要信息",
            "recommendations": []
        })

        manager = RARDialogueManager(temp_db_with_data, mock_llm, mock_embedding)
        manager.start_session("查询变慢")

        assert manager.state.dialogue_turns == 0

        manager.process_message("test")
        assert manager.state.dialogue_turns == 1

        manager.process_message("test2")
        assert manager.state.dialogue_turns == 2

    def test_confirm_observation(self, temp_db_with_data, mock_services):
        """测试:确认观察"""
        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        mock_llm, mock_embedding = mock_services
        manager = RARDialogueManager(temp_db_with_data, mock_llm, mock_embedding)
        manager.start_session("查询变慢")

        manager.confirm_observation("wait_io 高")

        assert "wait_io 高" in manager.state.confirmed_observations

    def test_deny_observation(self, temp_db_with_data, mock_services):
        """测试:否定观察"""
        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        mock_llm, mock_embedding = mock_services
        manager = RARDialogueManager(temp_db_with_data, mock_llm, mock_embedding)
        manager.start_session("查询变慢")

        manager.deny_observation("CPU 高")

        assert "CPU 高" in manager.state.denied_observations

    def test_force_diagnose_after_max_turns(self, temp_db_with_data, mock_services):
        """测试:超过最大轮次强制诊断"""
        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        mock_llm, mock_embedding = mock_services

        # LLM 总是返回推荐
        mock_llm.generate_simple.return_value = json.dumps({
            "action": "recommend",
            "confidence": 0.3,
            "reasoning": "需要信息",
            "recommendations": [{"observation": "test", "method": "test", "why": "test", "related_root_causes": []}]
        })

        manager = RARDialogueManager(temp_db_with_data, mock_llm, mock_embedding, max_turns=3)
        manager.start_session("查询变慢")

        # 模拟多轮对话
        for i in range(4):
            response = manager.process_message(f"test{i}")

        # 第 4 轮应该强制诊断或有提示
        assert manager.state.dialogue_turns >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
