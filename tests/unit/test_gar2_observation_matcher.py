"""观察匹配器单元测试"""

import pytest
from unittest.mock import MagicMock, patch
import numpy as np

from dbdiag.core.gar2.observation_matcher import ObservationMatcher
from dbdiag.utils.vector_utils import serialize_f32


class TestObservationMatcher:
    """ObservationMatcher 测试"""

    def _create_mock_matcher(self, phenomena_data=None, threshold=0.75):
        """创建带 mock 的匹配器"""
        mock_embedding_service = MagicMock()
        mock_embedding_service.encode.return_value = [1.0, 0.0, 0.0]

        with patch.object(ObservationMatcher, "__init__", lambda self, *args, **kwargs: None):
            matcher = ObservationMatcher.__new__(ObservationMatcher)
            matcher.embedding_service = mock_embedding_service
            matcher.match_threshold = threshold
            matcher.db_path = ":memory:"
            matcher._phenomenon_dao = MagicMock()
            matcher._root_cause_dao = MagicMock()

            # 默认返回空列表
            matcher._root_cause_dao.get_all_with_embedding.return_value = []

            if phenomena_data:
                matcher._phenomenon_dao.get_all_with_embedding.return_value = phenomena_data
            else:
                matcher._phenomenon_dao.get_all_with_embedding.return_value = []

        return matcher

    def test_match_no_phenomena(self):
        """没有现象数据时返回空"""
        matcher = self._create_mock_matcher([])
        results = matcher.match("wait_io 很高")
        assert results == []

    def test_match_with_similar_phenomenon(self):
        """匹配相似的现象"""
        # 创建一个与查询向量相似的现象
        similar_vector = serialize_f32([0.9, 0.1, 0.0])  # 高相似度
        dissimilar_vector = serialize_f32([0.0, 1.0, 0.0])  # 低相似度

        phenomena = [
            {"phenomenon_id": "P-001", "embedding": similar_vector},
            {"phenomenon_id": "P-002", "embedding": dissimilar_vector},
        ]

        matcher = self._create_mock_matcher(phenomena)
        results = matcher.match("test observation")

        # 只有 P-001 应该超过阈值
        assert len(results) >= 1
        assert results[0][0] == "P-001"
        assert results[0][1] > 0.75

    def test_match_below_threshold(self):
        """低于阈值的不返回"""
        # 创建一个与查询向量不太相似的现象
        low_similarity_vector = serialize_f32([0.5, 0.5, 0.5])

        phenomena = [
            {"phenomenon_id": "P-001", "embedding": low_similarity_vector},
        ]

        matcher = self._create_mock_matcher(phenomena, threshold=0.9)
        results = matcher.match("test")

        # 相似度约 0.58，低于 0.9 阈值
        assert results == []

    def test_match_sorted_by_score(self):
        """结果按相似度排序"""
        vec1 = serialize_f32([0.95, 0.05, 0.0])  # 最高
        vec2 = serialize_f32([0.85, 0.15, 0.0])  # 中等
        vec3 = serialize_f32([0.80, 0.20, 0.0])  # 较低

        phenomena = [
            {"phenomenon_id": "P-002", "embedding": vec2},
            {"phenomenon_id": "P-001", "embedding": vec1},
            {"phenomenon_id": "P-003", "embedding": vec3},
        ]

        matcher = self._create_mock_matcher(phenomena)
        results = matcher.match("test", top_k=3)

        # 应该按相似度降序
        assert results[0][0] == "P-001"
        assert results[1][0] == "P-002"
        assert results[2][0] == "P-003"

    def test_match_respects_top_k(self):
        """遵守 top_k 限制"""
        vectors = [serialize_f32([0.9, 0.1, 0.0]) for _ in range(10)]
        phenomena = [
            {"phenomenon_id": f"P-{i:03d}", "embedding": vectors[i]}
            for i in range(10)
        ]

        matcher = self._create_mock_matcher(phenomena)
        results = matcher.match("test", top_k=3)

        assert len(results) == 3

    def test_match_best(self):
        """match_best 返回最佳匹配"""
        vec1 = serialize_f32([0.95, 0.05, 0.0])
        vec2 = serialize_f32([0.85, 0.15, 0.0])

        phenomena = [
            {"phenomenon_id": "P-001", "embedding": vec1},
            {"phenomenon_id": "P-002", "embedding": vec2},
        ]

        matcher = self._create_mock_matcher(phenomena)
        result = matcher.match_best("test")

        assert result is not None
        assert result[0] == "P-001"

    def test_match_best_no_match(self):
        """没有匹配时 match_best 返回 None"""
        matcher = self._create_mock_matcher([])
        result = matcher.match_best("test")
        assert result is None

    def test_match_skips_phenomena_without_embedding(self):
        """跳过没有向量的现象"""
        vec = serialize_f32([0.9, 0.1, 0.0])
        phenomena = [
            {"phenomenon_id": "P-001", "embedding": None},
            {"phenomenon_id": "P-002", "embedding": vec},
        ]

        matcher = self._create_mock_matcher(phenomena)
        results = matcher.match("test")

        assert len(results) == 1
        assert results[0][0] == "P-002"

    def test_match_empty_embedding_response(self):
        """向量服务返回空时返回空列表"""
        matcher = self._create_mock_matcher([])
        matcher.embedding_service.encode.return_value = None

        results = matcher.match("test")
        assert results == []
