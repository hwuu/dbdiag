"""RAR Retriever 单元测试"""
import pytest
import sqlite3
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.scripts.init_db import init_database
from dbdiag.models.rar import RARSessionState


class TestRARRetriever:
    """RAR 检索器测试"""

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
            mock_embedding_3 = struct.pack("768f", *([0.3] * 768))

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
                    (
                        "T-0003",
                        "CPU 使用率 100%",
                        "全表扫描",
                        "添加索引",
                        "问题描述: CPU 高\n根因: 全表扫描\n解决方案: 添加索引",
                        mock_embedding_3,
                    ),
                ],
            )
            conn.commit()
            conn.close()

            yield db_path

    def test_build_search_query_basic(self):
        """测试:构建基础检索 query"""
        from dbdiag.core.rar.retriever import RARRetriever

        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )

        retriever = RARRetriever.__new__(RARRetriever)
        query = retriever._build_search_query(state, "有什么异常吗？")

        assert "查询变慢" in query

    def test_build_search_query_with_observations(self):
        """测试:构建带观察的检索 query"""
        from dbdiag.core.rar.retriever import RARRetriever

        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )
        state.confirm_observation("wait_io 高")
        state.deny_observation("CPU 高")

        retriever = RARRetriever.__new__(RARRetriever)
        query = retriever._build_search_query(state, "还有什么？")

        assert "查询变慢" in query
        assert "wait_io 高" in query

    def test_retrieve_tickets(self, temp_db_with_data):
        """测试:检索工单"""
        from dbdiag.core.rar.retriever import RARRetriever

        # Mock embedding service
        mock_embedding_service = Mock()
        mock_embedding_service.encode.return_value = [0.1] * 768

        retriever = RARRetriever(temp_db_with_data, mock_embedding_service)

        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )

        tickets = retriever.retrieve(state, "有什么异常？", top_k=2)

        assert len(tickets) <= 2
        assert all(hasattr(t, "ticket_id") for t in tickets)

    def test_retrieve_returns_sorted_by_similarity(self, temp_db_with_data):
        """测试:检索结果按相似度排序"""
        from dbdiag.core.rar.retriever import RARRetriever

        # Mock embedding service - 返回与第一条工单相似的向量
        mock_embedding_service = Mock()
        mock_embedding_service.encode.return_value = [0.1] * 768

        retriever = RARRetriever(temp_db_with_data, mock_embedding_service)

        state = RARSessionState(
            session_id="test-001",
            user_problem="查询变慢",
        )

        tickets = retriever.retrieve(state, "wait_io 高", top_k=3)

        # 第一条应该是最相似的
        assert len(tickets) >= 1
        # 第一条的 ticket_id 应该是 T-0001（embedding 最接近）
        assert tickets[0].ticket_id == "T-0001"

    def test_retrieve_empty_db(self):
        """测试:空数据库检索返回空列表"""
        from dbdiag.core.rar.retriever import RARRetriever

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            mock_embedding_service = Mock()
            mock_embedding_service.encode.return_value = [0.1] * 768

            retriever = RARRetriever(db_path, mock_embedding_service)

            state = RARSessionState(
                session_id="test-001",
                user_problem="查询变慢",
            )

            tickets = retriever.retrieve(state, "test", top_k=5)

            assert tickets == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
