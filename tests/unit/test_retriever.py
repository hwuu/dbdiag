"""retriever 单元测试"""
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


class TestPhenomenonRetriever:
    """PhenomenonRetriever 测试"""

    def _setup_test_db(self, tmpdir: str) -> str:
        """创建测试数据库并插入测试数据"""
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 插入测试 phenomena
        from dbdiag.utils.vector_utils import serialize_f32

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

        conn.commit()
        conn.close()

        return db_path

    def test_retrieve_phenomena_returns_results(self):
        """测试:检索应返回结果"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            # Mock embedding service
            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]  # 与 P-0001 相似

            from dbdiag.core.retriever import PhenomenonRetriever
            retriever = PhenomenonRetriever(db_path, mock_embedding)

            results = retriever.retrieve("IO 等待高", top_k=3)

            assert len(results) > 0
            assert all(hasattr(r[0], 'phenomenon_id') for r in results)

    def test_retrieve_phenomena_sorted_by_score(self):
        """测试:结果应按分数排序"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            from dbdiag.core.retriever import PhenomenonRetriever
            retriever = PhenomenonRetriever(db_path, mock_embedding)

            results = retriever.retrieve("wait_io", top_k=3)

            # 验证分数降序排列
            scores = [r[1] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_retrieve_phenomena_excludes_confirmed(self):
        """测试:应排除已确认的现象（降低权重）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.1, 0.2, 0.3]

            from dbdiag.core.retriever import PhenomenonRetriever
            retriever = PhenomenonRetriever(db_path, mock_embedding)

            # 排除 P-0001
            results = retriever.retrieve(
                "wait_io",
                top_k=3,
                excluded_phenomenon_ids={"P-0001"}
            )

            # P-0001 的分数应该较低
            p0001_results = [r for r in results if r[0].phenomenon_id == "P-0001"]
            if p0001_results:
                p0001_score = p0001_results[0][1]
                other_scores = [r[1] for r in results if r[0].phenomenon_id != "P-0001"]
                if other_scores:
                    # P-0001 分数应该不是最高的
                    assert p0001_score <= max(other_scores) or len(other_scores) == 0

    def test_retrieve_phenomena_with_keywords(self):
        """测试:关键词过滤应生效"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_embedding = Mock()
            mock_embedding.encode.return_value = [0.5, 0.5, 0.5]

            from dbdiag.core.retriever import PhenomenonRetriever
            retriever = PhenomenonRetriever(db_path, mock_embedding)

            # 使用关键词 "索引"
            results = retriever.retrieve(
                "性能问题",
                top_k=3,
                keywords=["索引"]
            )

            # 应该只返回包含"索引"的结果
            for phenomenon, score in results:
                assert "索引" in phenomenon.description or "索引" in phenomenon.observation_method


class TestStepRetrieverDeprecated:
    """StepRetriever deprecated 测试"""

    def test_step_retriever_triggers_warning(self):
        """测试:StepRetriever 应触发 deprecation 警告"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")

                from dbdiag.core.retriever import StepRetriever
                retriever = StepRetriever(db_path)

                # 验证触发了 deprecation 警告
                deprecation_warnings = [
                    warning for warning in w
                    if issubclass(warning.category, DeprecationWarning)
                ]
                assert len(deprecation_warnings) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
