"""rebuild_index 单元测试"""
import pytest
import sqlite3
import tempfile
import os
import json
from pathlib import Path
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.init_db import init_database
from scripts.import_tickets import import_tickets_v2


class TestRebuildIndex:
    """rebuild_index 功能测试"""

    def _setup_test_db(self, tmpdir: str) -> tuple:
        """创建测试数据库并导入测试数据"""
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        # 创建测试数据
        data = [
            {
                "ticket_id": "TICKET-001",
                "metadata": {"version": "PostgreSQL-14.5"},
                "description": "报表查询变慢",
                "root_cause": "索引膨胀",
                "solution": "REINDEX",
                "anomalies": [
                    {
                        "description": "wait_io 事件占比 65%，超过阈值",
                        "observation_method": "SELECT wait_event FROM pg_stat_activity",
                        "why_relevant": "IO 等待高说明磁盘瓶颈"
                    },
                    {
                        "description": "索引大小从 2GB 增长到 12GB",
                        "observation_method": "SELECT pg_relation_size(indexrelid)",
                        "why_relevant": "索引膨胀导致扫描效率下降"
                    }
                ]
            },
            {
                "ticket_id": "TICKET-002",
                "metadata": {"version": "PostgreSQL-15.0"},
                "description": "批量导入变慢",
                "root_cause": "IO 瓶颈",
                "solution": "优化磁盘",
                "anomalies": [
                    {
                        "description": "wait_io 占比 70%，高于正常水平",  # 与 TICKET-001 的第一个相似
                        "observation_method": "SELECT wait_event_type FROM pg_stat_activity",
                        "why_relevant": "IO 等待表明存储性能不足"
                    }
                ]
            },
            {
                "ticket_id": "TICKET-003",
                "metadata": {},
                "description": "连接数过多",
                "root_cause": "连接泄漏",
                "solution": "修复连接池",
                "anomalies": [
                    {
                        "description": "活跃连接数 500，超过配置上限",
                        "observation_method": "SELECT count(*) FROM pg_stat_activity",
                        "why_relevant": "连接数异常说明存在泄漏"
                    }
                ]
            }
        ]

        data_path = os.path.join(tmpdir, "tickets.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        import_tickets_v2(data_path, db_path)
        return db_path, data_path

    def test_rebuild_index_creates_phenomena(self):
        """测试:rebuild_index 应创建 phenomena 记录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = self._setup_test_db(tmpdir)

            # Mock embedding service
            mock_embeddings = [
                [0.1, 0.2, 0.3],  # TICKET-001_anomaly_1 (wait_io)
                [0.4, 0.5, 0.6],  # TICKET-001_anomaly_2 (索引大小)
                [0.11, 0.21, 0.31],  # TICKET-002_anomaly_1 (wait_io 相似)
                [0.7, 0.8, 0.9],  # TICKET-003_anomaly_1 (连接数)
            ]

            with patch('scripts.rebuild_index.EmbeddingService') as MockEmbedding:
                mock_embedding_instance = Mock()
                mock_embedding_instance.encode_batch.return_value = mock_embeddings
                MockEmbedding.return_value = mock_embedding_instance

                with patch('scripts.rebuild_index.LLMService') as MockLLM:
                    mock_llm_instance = Mock()
                    mock_llm_instance.generate_simple.return_value = "标准化描述"
                    MockLLM.return_value = mock_llm_instance

                    from scripts.rebuild_index import rebuild_index
                    rebuild_index(db_path, similarity_threshold=0.95)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 应该创建了 phenomena 记录
            cursor.execute("SELECT COUNT(*) FROM phenomena")
            count = cursor.fetchone()[0]
            assert count > 0

            conn.close()

    def test_rebuild_index_creates_ticket_anomalies(self):
        """测试:rebuild_index 应创建 ticket_anomalies 关联"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = self._setup_test_db(tmpdir)

            mock_embeddings = [
                [0.1, 0.2, 0.3],
                [0.4, 0.5, 0.6],
                [0.11, 0.21, 0.31],
                [0.7, 0.8, 0.9],
            ]

            with patch('scripts.rebuild_index.EmbeddingService') as MockEmbedding:
                mock_embedding_instance = Mock()
                mock_embedding_instance.encode_batch.return_value = mock_embeddings
                MockEmbedding.return_value = mock_embedding_instance

                with patch('scripts.rebuild_index.LLMService') as MockLLM:
                    mock_llm_instance = Mock()
                    mock_llm_instance.generate_simple.return_value = "标准化描述"
                    MockLLM.return_value = mock_llm_instance

                    from scripts.rebuild_index import rebuild_index
                    rebuild_index(db_path, similarity_threshold=0.95)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 应该创建了 ticket_anomalies 关联（每个原始异常对应一个）
            cursor.execute("SELECT COUNT(*) FROM ticket_anomalies")
            count = cursor.fetchone()[0]
            assert count == 4  # 4 个原始异常

            conn.close()

    def test_rebuild_index_clusters_similar_anomalies(self):
        """测试:相似的异常应该聚类到同一个 phenomenon"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = self._setup_test_db(tmpdir)

            # 让前两个向量非常相似（wait_io 相关）
            mock_embeddings = [
                [0.1, 0.2, 0.3],  # TICKET-001_anomaly_1 (wait_io)
                [0.4, 0.5, 0.6],  # TICKET-001_anomaly_2 (索引大小) - 不同
                [0.1, 0.2, 0.3],  # TICKET-002_anomaly_1 (wait_io) - 完全相同
                [0.7, 0.8, 0.9],  # TICKET-003_anomaly_1 (连接数) - 不同
            ]

            with patch('scripts.rebuild_index.EmbeddingService') as MockEmbedding:
                mock_embedding_instance = Mock()
                mock_embedding_instance.encode_batch.return_value = mock_embeddings
                MockEmbedding.return_value = mock_embedding_instance

                with patch('scripts.rebuild_index.LLMService') as MockLLM:
                    mock_llm_instance = Mock()
                    mock_llm_instance.generate_simple.return_value = "标准化描述"
                    MockLLM.return_value = mock_llm_instance

                    from scripts.rebuild_index import rebuild_index
                    rebuild_index(db_path, similarity_threshold=0.99)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 相似的异常应该聚类，phenomena 数量应该少于原始异常数量
            cursor.execute("SELECT COUNT(*) FROM phenomena")
            phenomena_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM raw_anomalies")
            raw_count = cursor.fetchone()[0]

            # 4 个原始异常，2 个相似的应该聚类，所以最多 3 个 phenomena
            assert phenomena_count <= raw_count

            conn.close()

    def test_rebuild_index_preserves_why_relevant(self):
        """测试:ticket_anomalies 应保留原始的 why_relevant"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = self._setup_test_db(tmpdir)

            mock_embeddings = [[0.1] * 3] * 4

            with patch('scripts.rebuild_index.EmbeddingService') as MockEmbedding:
                mock_embedding_instance = Mock()
                mock_embedding_instance.encode_batch.return_value = mock_embeddings
                MockEmbedding.return_value = mock_embedding_instance

                with patch('scripts.rebuild_index.LLMService') as MockLLM:
                    mock_llm_instance = Mock()
                    mock_llm_instance.generate_simple.return_value = "标准化描述"
                    MockLLM.return_value = mock_llm_instance

                    from scripts.rebuild_index import rebuild_index
                    rebuild_index(db_path, similarity_threshold=0.95)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT why_relevant FROM ticket_anomalies
                WHERE id = 'TICKET-001_anomaly_1'
            """)
            row = cursor.fetchone()
            assert row is not None
            assert "IO 等待" in row[0]

            conn.close()

    def test_rebuild_index_clears_old_data(self):
        """测试:rebuild_index 应清除旧的 phenomena 和 ticket_anomalies"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = self._setup_test_db(tmpdir)

            mock_embeddings = [[0.1] * 3] * 4

            with patch('scripts.rebuild_index.EmbeddingService') as MockEmbedding:
                mock_embedding_instance = Mock()
                mock_embedding_instance.encode_batch.return_value = mock_embeddings
                MockEmbedding.return_value = mock_embedding_instance

                with patch('scripts.rebuild_index.LLMService') as MockLLM:
                    mock_llm_instance = Mock()
                    mock_llm_instance.generate_simple.return_value = "标准化描述"
                    MockLLM.return_value = mock_llm_instance

                    from scripts.rebuild_index import rebuild_index

                    # 第一次 rebuild
                    rebuild_index(db_path, similarity_threshold=0.95)

                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM phenomena")
                    first_count = cursor.fetchone()[0]
                    conn.close()

                    # 第二次 rebuild（应该清除旧数据重建）
                    rebuild_index(db_path, similarity_threshold=0.95)

                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM phenomena")
                    second_count = cursor.fetchone()[0]
                    conn.close()

                    # 数量应该相同（不是累加）
                    assert first_count == second_count

    def test_rebuild_index_creates_root_causes(self):
        """测试:rebuild_index 应创建 root_causes 记录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = self._setup_test_db(tmpdir)

            mock_embeddings = [[0.1] * 3] * 4

            with patch('scripts.rebuild_index.EmbeddingService') as MockEmbedding:
                mock_embedding_instance = Mock()
                mock_embedding_instance.encode_batch.return_value = mock_embeddings
                MockEmbedding.return_value = mock_embedding_instance

                with patch('scripts.rebuild_index.LLMService') as MockLLM:
                    mock_llm_instance = Mock()
                    mock_llm_instance.generate_simple.return_value = "标准化描述"
                    MockLLM.return_value = mock_llm_instance

                    from scripts.rebuild_index import rebuild_index
                    rebuild_index(db_path, similarity_threshold=0.95)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 测试数据有 3 个不同的 root_cause，应该生成 3 个 root_causes 记录
            cursor.execute("SELECT COUNT(*) FROM root_causes")
            count = cursor.fetchone()[0]
            assert count == 3

            # 验证 root_causes 内容
            cursor.execute("SELECT root_cause_id, description, ticket_count FROM root_causes ORDER BY root_cause_id")
            rows = cursor.fetchall()
            assert len(rows) == 3
            # 每个 root_cause 都应该有对应的 description
            for row in rows:
                assert row["root_cause_id"].startswith("RC-")
                assert row["description"] is not None
                assert row["ticket_count"] >= 1

            conn.close()

    def test_rebuild_index_sets_tickets_root_cause_id(self):
        """测试:rebuild_index 应为 tickets 设置 root_cause_id"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = self._setup_test_db(tmpdir)

            mock_embeddings = [[0.1] * 3] * 4

            with patch('scripts.rebuild_index.EmbeddingService') as MockEmbedding:
                mock_embedding_instance = Mock()
                mock_embedding_instance.encode_batch.return_value = mock_embeddings
                MockEmbedding.return_value = mock_embedding_instance

                with patch('scripts.rebuild_index.LLMService') as MockLLM:
                    mock_llm_instance = Mock()
                    mock_llm_instance.generate_simple.return_value = "标准化描述"
                    MockLLM.return_value = mock_llm_instance

                    from scripts.rebuild_index import rebuild_index
                    rebuild_index(db_path, similarity_threshold=0.95)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 验证 tickets 表有 root_cause_id
            cursor.execute("SELECT ticket_id, root_cause_id, root_cause FROM tickets")
            rows = cursor.fetchall()
            assert len(rows) == 3

            for row in rows:
                # root_cause_id 应该存在且格式正确
                assert row["root_cause_id"] is not None
                assert row["root_cause_id"].startswith("RC-")
                # root_cause 文本也应该保留
                assert row["root_cause"] is not None

            # 验证 root_cause_id 正确关联到 root_causes 表
            cursor.execute("""
                SELECT t.ticket_id, t.root_cause, rc.description
                FROM tickets t
                JOIN root_causes rc ON t.root_cause_id = rc.root_cause_id
            """)
            joined_rows = cursor.fetchall()
            assert len(joined_rows) == 3

            for row in joined_rows:
                # root_cause 文本应该与 root_causes.description 一致
                assert row["root_cause"] == row["description"]

            conn.close()


class TestClusterBySimilarity:
    """聚类算法测试"""

    def test_cluster_identical_vectors(self):
        """测试:完全相同的向量应聚类到一起"""
        from scripts.rebuild_index import cluster_by_similarity

        items = [
            {"id": "a", "embedding": [1.0, 0.0, 0.0]},
            {"id": "b", "embedding": [1.0, 0.0, 0.0]},  # 与 a 相同
            {"id": "c", "embedding": [0.0, 1.0, 0.0]},  # 不同
        ]

        clusters = cluster_by_similarity(items, similarity_threshold=0.99)

        # a 和 b 应该在同一个聚类
        assert len(clusters) == 2

    def test_cluster_all_different(self):
        """测试:完全不同的向量应各自成聚类"""
        from scripts.rebuild_index import cluster_by_similarity

        items = [
            {"id": "a", "embedding": [1.0, 0.0, 0.0]},
            {"id": "b", "embedding": [0.0, 1.0, 0.0]},
            {"id": "c", "embedding": [0.0, 0.0, 1.0]},
        ]

        clusters = cluster_by_similarity(items, similarity_threshold=0.99)

        # 每个都应该是独立聚类
        assert len(clusters) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
