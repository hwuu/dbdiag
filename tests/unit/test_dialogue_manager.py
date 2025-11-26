"""dialogue_manager 单元测试"""
import pytest
import sqlite3
import tempfile
import os
import json
import warnings
from pathlib import Path
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.init_db import init_database
from dbdiag.utils.vector_utils import serialize_f32


class TestPhenomenonDialogueManager:
    """PhenomenonDialogueManager 测试"""

    def _setup_test_db(self, tmpdir: str) -> str:
        """创建测试数据库并插入测试数据"""
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 插入测试 phenomena
        phenomena = [
            ("P-0001", "wait_io 事件占比异常高", "SELECT wait_event FROM pg_stat_activity",
             json.dumps(["a1"]), 1, serialize_f32([0.1, 0.2, 0.3])),
            ("P-0002", "索引大小异常增长", "SELECT pg_relation_size(indexrelid)",
             json.dumps(["a2"]), 1, serialize_f32([0.4, 0.5, 0.6])),
        ]

        for p in phenomena:
            cursor.execute("""
                INSERT INTO phenomena (phenomenon_id, description, observation_method,
                                       source_anomaly_ids, cluster_size, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
            """, p)

        # 插入 raw_tickets
        cursor.execute("""
            INSERT INTO raw_tickets (ticket_id, description, root_cause, solution)
            VALUES ('T-001', '报表查询慢', 'IO 瓶颈', '优化磁盘')
        """)

        # 插入 ticket_anomalies
        cursor.execute("""
            INSERT INTO ticket_anomalies (id, ticket_id, phenomenon_id, why_relevant)
            VALUES ('ta1', 'T-001', 'P-0001', 'IO 等待高')
        """)

        conn.commit()
        conn.close()

        return db_path

    def test_start_conversation_returns_response(self):
        """测试:start_conversation 应返回响应"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()
            mock_llm.generate_simple.return_value = "0.5"

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            from dbdiag.core.dialogue_manager import PhenomenonDialogueManager
            manager = PhenomenonDialogueManager(db_path, mock_llm, mock_embedding)

            result = manager.start_conversation("查询很慢")

            assert "message" in result
            assert "session_id" in result

    def test_start_conversation_creates_session(self):
        """测试:start_conversation 应创建会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()
            mock_llm.generate_simple.return_value = "0.5"

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            from dbdiag.core.dialogue_manager import PhenomenonDialogueManager
            manager = PhenomenonDialogueManager(db_path, mock_llm, mock_embedding)

            result = manager.start_conversation("查询很慢")
            session_id = result["session_id"]

            session_info = manager.get_session(session_id)
            assert session_info is not None
            assert session_info["user_problem"] == "查询很慢"

    def test_continue_conversation_updates_session(self):
        """测试:continue_conversation 应更新会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()
            mock_llm.generate_simple.return_value = "0.5"

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            from dbdiag.core.dialogue_manager import PhenomenonDialogueManager
            manager = PhenomenonDialogueManager(db_path, mock_llm, mock_embedding)

            # 开始对话
            result = manager.start_conversation("查询很慢")
            session_id = result["session_id"]

            # 继续对话
            result2 = manager.continue_conversation(session_id, "IO 使用率确实很高")

            assert "message" in result2
            assert result2["session_id"] == session_id


class TestDialogueManagerDeprecated:
    """DialogueManager deprecated 测试"""

    def test_dialogue_manager_triggers_warning(self):
        """测试:DialogueManager 应触发 deprecation 警告"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            mock_llm = Mock()

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")

                from dbdiag.core.dialogue_manager import DialogueManager
                manager = DialogueManager(db_path, mock_llm)

                # 验证触发了 deprecation 警告（可能有多个，来自内部组件）
                deprecation_warnings = [
                    warning for warning in w
                    if issubclass(warning.category, DeprecationWarning)
                ]
                assert len(deprecation_warnings) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
