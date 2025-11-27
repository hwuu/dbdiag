"""ResponseGenerator 单元测试"""
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
from dbdiag.core.response_generator import ResponseGenerator
from dbdiag.utils.vector_utils import serialize_f32


class TestResponseGenerator:
    """ResponseGenerator 测试"""

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
            VALUES ('T-001', '报表查询慢', 'IO 瓶颈', '优化磁盘配置，增加 IOPS')
        """)
        cursor.execute("""
            INSERT INTO raw_tickets (ticket_id, description, root_cause, solution)
            VALUES ('T-002', 'IO 等待高', 'IO 瓶颈', '检查磁盘性能')
        """)

        conn.commit()
        conn.close()

        return db_path

    def test_generate_diagnosis_summary_calls_llm(self):
        """测试: _generate_diagnosis_summary 调用 LLM"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()
            mock_llm.generate_simple.return_value = """**观察到的现象：**
用户反馈 wait_io 占比达到 70%，表明存在明显的 IO 等待问题。

**推理链路：**
高 IO 等待通常由磁盘性能瓶颈导致，结合历史案例确认为 IO 瓶颈。

**恢复措施：**
1. 优化磁盘配置
2. 增加 IOPS"""

            generator = ResponseGenerator(db_path, mock_llm)

            session = SessionState(
                session_id="test-session",
                user_problem="查询很慢",
                confirmed_phenomena=[
                    ConfirmedPhenomenon(
                        phenomenon_id="P-0001",
                        result_summary="wait_io 占比达到 70%"
                    )
                ],
            )

            recommendation = {
                "action": "confirm_root_cause",
                "root_cause": "IO 瓶颈",
                "confidence": 0.85,
            }

            result = generator.generate_response(session, recommendation)

            # 验证调用了 LLM
            assert mock_llm.generate_simple.called

            # 验证响应包含诊断总结
            assert "diagnosis_summary" in result
            assert "观察到的现象" in result["diagnosis_summary"]
            assert "推理链路" in result["diagnosis_summary"]
            assert "恢复措施" in result["diagnosis_summary"]

    def test_generate_diagnosis_summary_fallback(self):
        """测试: LLM 失败时降级处理"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()
            mock_llm.generate_simple.side_effect = Exception("LLM 调用失败")

            generator = ResponseGenerator(db_path, mock_llm)

            session = SessionState(
                session_id="test-session",
                user_problem="查询很慢",
                confirmed_phenomena=[
                    ConfirmedPhenomenon(
                        phenomenon_id="P-0001",
                        result_summary="wait_io 占比达到 70%"
                    )
                ],
            )

            recommendation = {
                "action": "confirm_root_cause",
                "root_cause": "IO 瓶颈",
                "confidence": 0.85,
            }

            result = generator.generate_response(session, recommendation)

            # 即使 LLM 失败，也应返回降级的总结
            assert "diagnosis_summary" in result
            assert "IO 瓶颈" in result["diagnosis_summary"]

    def test_get_phenomenon_details(self):
        """测试: 获取现象详情"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()
            generator = ResponseGenerator(db_path, mock_llm)

            details = generator._get_phenomenon_details(["P-0001", "P-0002"])

            assert len(details) == 2
            assert any(d["phenomenon_id"] == "P-0001" for d in details)
            assert any(d["phenomenon_id"] == "P-0002" for d in details)

    def test_get_phenomenon_details_empty(self):
        """测试: 空 ID 列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()
            generator = ResponseGenerator(db_path, mock_llm)

            details = generator._get_phenomenon_details([])

            assert details == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
