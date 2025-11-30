"""init_rar_index 单元测试"""
import pytest
import sqlite3
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.scripts.init_db import init_database


class TestInitRarIndex:
    """RAR 索引初始化测试"""

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库并插入测试数据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            # 插入测试数据到 raw_tickets
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO raw_tickets (ticket_id, metadata_json, description, root_cause, solution)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("T-0001", "{}", "查询变慢", "索引膨胀", "REINDEX"),
                    ("T-0002", "{}", "连接数过多", "连接泄露", "检查连接池"),
                ],
            )
            conn.commit()
            conn.close()

            yield db_path

    def test_init_rar_index_creates_records(self, temp_db):
        """测试:初始化 RAR 索引应创建记录"""
        from dbdiag.scripts.init_rar_index import init_rar_index

        # Mock embedding service
        mock_config = Mock()
        mock_embedding_service = Mock()
        mock_embedding_service.encode_batch.return_value = [
            [0.1] * 768,  # fake embedding
            [0.2] * 768,
        ]

        with patch("dbdiag.scripts.init_rar_index.load_config", return_value=mock_config):
            with patch("dbdiag.scripts.init_rar_index.EmbeddingService", return_value=mock_embedding_service):
                init_rar_index(temp_db)

        # 验证记录已创建
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM rar_raw_tickets")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 2

    def test_init_rar_index_combined_text(self, temp_db):
        """测试:combined_text 应包含 description + root_cause + solution"""
        from dbdiag.scripts.init_rar_index import init_rar_index

        mock_config = Mock()
        mock_embedding_service = Mock()
        mock_embedding_service.encode_batch.return_value = [
            [0.1] * 768,
            [0.2] * 768,
        ]

        with patch("dbdiag.scripts.init_rar_index.load_config", return_value=mock_config):
            with patch("dbdiag.scripts.init_rar_index.EmbeddingService", return_value=mock_embedding_service):
                init_rar_index(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT combined_text FROM rar_raw_tickets WHERE ticket_id='T-0001'")
        combined_text = cursor.fetchone()[0]
        conn.close()

        assert "查询变慢" in combined_text
        assert "索引膨胀" in combined_text
        assert "REINDEX" in combined_text

    def test_init_rar_index_has_embedding(self, temp_db):
        """测试:记录应有 embedding"""
        from dbdiag.scripts.init_rar_index import init_rar_index

        mock_config = Mock()
        mock_embedding_service = Mock()
        mock_embedding_service.encode_batch.return_value = [
            [0.1] * 768,
            [0.2] * 768,
        ]

        with patch("dbdiag.scripts.init_rar_index.load_config", return_value=mock_config):
            with patch("dbdiag.scripts.init_rar_index.EmbeddingService", return_value=mock_embedding_service):
                init_rar_index(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT embedding FROM rar_raw_tickets WHERE ticket_id='T-0001'")
        embedding = cursor.fetchone()[0]
        conn.close()

        assert embedding is not None
        assert len(embedding) > 0

    def test_init_rar_index_idempotent(self, temp_db):
        """测试:多次运行应该是幂等的（清除旧数据后重建）"""
        from dbdiag.scripts.init_rar_index import init_rar_index

        mock_config = Mock()
        mock_embedding_service = Mock()
        mock_embedding_service.encode_batch.return_value = [
            [0.1] * 768,
            [0.2] * 768,
        ]

        with patch("dbdiag.scripts.init_rar_index.load_config", return_value=mock_config):
            with patch("dbdiag.scripts.init_rar_index.EmbeddingService", return_value=mock_embedding_service):
                # 运行两次
                init_rar_index(temp_db)
                init_rar_index(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM rar_raw_tickets")
        count = cursor.fetchone()[0]
        conn.close()

        # 应该还是 2 条，不是 4 条
        assert count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
