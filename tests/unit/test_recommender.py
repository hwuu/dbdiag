"""recommender 单元测试"""
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
from dbdiag.models.session import SessionState, Hypothesis, ConfirmedFact, ConfirmedPhenomenon
from dbdiag.utils.vector_utils import serialize_f32


class TestPhenomenonRecommendationEngine:
    """PhenomenonRecommendationEngine 测试"""

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

        conn.commit()
        conn.close()

        return db_path

    def test_recommend_next_action_no_hypotheses(self):
        """测试:没有假设时应询问初始信息"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()

            from dbdiag.core.recommender import PhenomenonRecommendationEngine
            engine = PhenomenonRecommendationEngine(db_path, mock_llm)

            session = SessionState(
                session_id="test-session",
                user_problem="查询很慢",
            )

            result = engine.recommend_next_action(session)

            assert result["action"] == "ask_initial_info"

    def test_recommend_next_action_high_confidence(self):
        """测试:高置信度时应确认根因"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()

            from dbdiag.core.recommender import PhenomenonRecommendationEngine
            engine = PhenomenonRecommendationEngine(db_path, mock_llm)

            session = SessionState(
                session_id="test-session",
                user_problem="查询很慢",
                active_hypotheses=[
                    Hypothesis(
                        root_cause="IO 瓶颈",
                        confidence=0.90,
                        supporting_step_ids=[],
                        missing_facts=[],
                        supporting_phenomenon_ids=["P-0001"],
                    )
                ],
            )

            result = engine.recommend_next_action(session)

            assert result["action"] == "confirm_root_cause"
            assert result["root_cause"] == "IO 瓶颈"

    def test_recommend_next_action_medium_confidence(self):
        """测试:中等置信度时应推荐验证现象"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()
            mock_llm.generate_simple.return_value = "no"

            from dbdiag.core.recommender import PhenomenonRecommendationEngine
            engine = PhenomenonRecommendationEngine(db_path, mock_llm)

            session = SessionState(
                session_id="test-session",
                user_problem="查询很慢",
                active_hypotheses=[
                    Hypothesis(
                        root_cause="IO 瓶颈",
                        confidence=0.60,
                        supporting_step_ids=[],
                        missing_facts=[],
                        supporting_phenomenon_ids=["P-0001"],
                        next_recommended_phenomenon_id="P-0001",
                    )
                ],
            )

            result = engine.recommend_next_action(session)

            # 应该推荐现象或询问症状
            assert result["action"] in ["recommend_phenomenon", "ask_symptom", "ask_general"]

    def test_get_phenomenon_by_id(self):
        """测试:应能根据 ID 获取现象"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)

            mock_llm = Mock()

            from dbdiag.core.recommender import PhenomenonRecommendationEngine
            engine = PhenomenonRecommendationEngine(db_path, mock_llm)

            phenomenon = engine._get_phenomenon_by_id("P-0001")

            assert phenomenon is not None
            assert phenomenon.phenomenon_id == "P-0001"
            assert "wait_io" in phenomenon.description


class TestRecommendationEngineDeprecated:
    """RecommendationEngine deprecated 测试"""

    def test_recommendation_engine_triggers_warning(self):
        """测试:RecommendationEngine 应触发 deprecation 警告"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            mock_llm = Mock()

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")

                from dbdiag.core.recommender import RecommendationEngine
                engine = RecommendationEngine(db_path, mock_llm)

                # 验证触发了 deprecation 警告
                deprecation_warnings = [
                    warning for warning in w
                    if issubclass(warning.category, DeprecationWarning)
                ]
                assert len(deprecation_warnings) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
