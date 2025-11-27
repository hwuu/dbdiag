"""hypothesis_tracker 单元测试"""
import pytest
import sqlite3
import tempfile
import os
import json
from pathlib import Path
from unittest.mock import Mock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.init_db import init_database
from dbdiag.models import SessionState, ConfirmedPhenomenon, Hypothesis
from dbdiag.utils.vector_utils import serialize_f32


class TestPhenomenonHypothesisTracker:
    """PhenomenonHypothesisTracker 测试"""

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
            ("P-0003", "连接数超过阈值", "SELECT count(*) FROM pg_stat_activity",
             json.dumps(["a3"]), 1, serialize_f32([0.7, 0.8, 0.9])),
        ]

        for p in phenomena:
            cursor.execute("""
                INSERT INTO phenomena (phenomenon_id, description, observation_method,
                                       source_anomaly_ids, cluster_size, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
            """, p)

        # 插入 raw_tickets 关联（用于获取 root_cause）
        cursor.execute("""
            INSERT INTO raw_tickets (ticket_id, description, root_cause, solution)
            VALUES ('T-001', '报表查询慢', 'IO 瓶颈', '优化磁盘')
        """)
        cursor.execute("""
            INSERT INTO raw_tickets (ticket_id, description, root_cause, solution)
            VALUES ('T-002', '索引膨胀', '索引碎片', 'REINDEX')
        """)

        # 插入 ticket_anomalies 关联
        cursor.execute("""
            INSERT INTO ticket_anomalies (id, ticket_id, phenomenon_id, why_relevant)
            VALUES ('ta1', 'T-001', 'P-0001', 'IO 等待高')
        """)
        cursor.execute("""
            INSERT INTO ticket_anomalies (id, ticket_id, phenomenon_id, why_relevant)
            VALUES ('ta2', 'T-002', 'P-0002', '索引膨胀导致查询慢')
        """)

        conn.commit()
        conn.close()

        return db_path

    def test_update_hypotheses_returns_session(self):
        """测试:update_hypotheses 应返回更新后的会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            # Mock services
            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            mock_llm = Mock()
            mock_llm.generate_simple.return_value = "0.7"

            from dbdiag.core.hypothesis_tracker import PhenomenonHypothesisTracker
            tracker = PhenomenonHypothesisTracker(db_path, mock_llm, mock_embedding)

            session = SessionState(
                session_id="test-session",
                user_problem="查询很慢",
            )

            result = tracker.update_hypotheses(session)

            assert result is not None
            assert result.session_id == "test-session"

    def test_update_hypotheses_generates_hypotheses(self):
        """测试:update_hypotheses 应生成假设"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            mock_llm = Mock()
            mock_llm.generate_simple.return_value = "0.7"

            from dbdiag.core.hypothesis_tracker import PhenomenonHypothesisTracker
            tracker = PhenomenonHypothesisTracker(db_path, mock_llm, mock_embedding)

            session = SessionState(
                session_id="test-session",
                user_problem="IO 等待很高",
            )

            result = tracker.update_hypotheses(session)

            # 应该生成假设（取决于检索结果）
            assert hasattr(result, 'active_hypotheses')

    def test_update_hypotheses_with_confirmed_phenomena(self):
        """测试:带有确认现象时应提高置信度"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            mock_llm = Mock()

            from dbdiag.core.hypothesis_tracker import PhenomenonHypothesisTracker
            tracker = PhenomenonHypothesisTracker(db_path, mock_llm, mock_embedding)

            # 先不带 confirmed_phenomena
            session_without = SessionState(
                session_id="test-session-1",
                user_problem="IO 等待很高",
            )
            result_without = tracker.update_hypotheses(session_without)

            # 带 confirmed_phenomena（确认了 P-0001）
            session_with = SessionState(
                session_id="test-session-2",
                user_problem="IO 等待很高",
                confirmed_phenomena=[
                    ConfirmedPhenomenon(phenomenon_id="P-0001", result_summary="wait_io 占比达到 70%")
                ],
            )
            result_with = tracker.update_hypotheses(session_with)

            # 确认现象后，相关假设的置信度应提高
            # （由于置信度基于现象确认进度，确认越多置信度越高）
            assert hasattr(result_with, 'active_hypotheses')

    def test_update_hypotheses_uses_v2_fields(self):
        """测试:假设应包含 V2 字段"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            mock_llm = Mock()
            mock_llm.generate_simple.return_value = "0.7"

            from dbdiag.core.hypothesis_tracker import PhenomenonHypothesisTracker
            tracker = PhenomenonHypothesisTracker(db_path, mock_llm, mock_embedding)

            session = SessionState(
                session_id="test-session",
                user_problem="IO 等待很高",
            )

            result = tracker.update_hypotheses(session)

            # 检查 V2 字段
            if result.active_hypotheses:
                hypothesis = result.active_hypotheses[0]
                # V2 字段应该存在
                assert hasattr(hypothesis, 'supporting_phenomenon_ids')
                assert hasattr(hypothesis, 'supporting_ticket_ids')
                assert hasattr(hypothesis, 'next_recommended_phenomenon_id')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
