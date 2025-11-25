"""向量工具单元测试"""
import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from dbdiag.utils.vector_utils import serialize_f32, deserialize_f32, cosine_similarity


class TestVectorUtils:
    """向量工具测试"""

    def test_serialize_deserialize_single_vector(self):
        """测试:序列化和反序列化单个向量"""
        original = [0.1, 0.2, 0.3, 0.4, 0.5]

        # 序列化
        serialized = serialize_f32(original)
        assert isinstance(serialized, bytes)
        assert len(serialized) == len(original) * 4  # float32 占 4 字节

        # 反序列化
        deserialized = deserialize_f32(serialized)
        assert isinstance(deserialized, list)
        assert len(deserialized) == len(original)
        # 检查值是否接近（考虑浮点精度）
        for i, (orig, deser) in enumerate(zip(original, deserialized)):
            assert abs(orig - deser) < 1e-6, f"索引 {i}: {orig} vs {deser}"

    def test_cosine_similarity_identical_vectors(self):
        """测试:相同向量的余弦相似度应为 1.0"""
        vec = [1.0, 2.0, 3.0]
        similarity = cosine_similarity(vec, vec)
        assert abs(similarity - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal_vectors(self):
        """测试:正交向量的余弦相似度应为 0.0"""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        similarity = cosine_similarity(vec1, vec2)
        assert abs(similarity) < 1e-6

    def test_cosine_similarity_opposite_vectors(self):
        """测试:相反向量的余弦相似度应为 -1.0"""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [-1.0, -2.0, -3.0]
        similarity = cosine_similarity(vec1, vec2)
        assert abs(similarity - (-1.0)) < 1e-6

    def test_cosine_similarity_zero_vector(self):
        """测试:零向量的余弦相似度应为 0.0"""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [0.0, 0.0, 0.0]
        similarity = cosine_similarity(vec1, vec2)
        assert similarity == 0.0

    def test_serialize_deserialize_large_vector(self):
        """测试:大向量的序列化和反序列化"""
        # 模拟 1024 维向量
        original = list(np.random.rand(1024).astype(np.float32))

        serialized = serialize_f32(original)
        assert len(serialized) == 1024 * 4

        deserialized = deserialize_f32(serialized)
        assert len(deserialized) == 1024
        # 检查前 10 个值
        for i in range(10):
            assert abs(original[i] - deserialized[i]) < 1e-6

    def test_cosine_similarity_normalized_vectors(self):
        """测试:归一化向量的余弦相似度"""
        vec1 = [0.6, 0.8]  # 已归一化
        vec2 = [0.8, 0.6]  # 已归一化

        similarity = cosine_similarity(vec1, vec2)
        expected = 0.6 * 0.8 + 0.8 * 0.6  # 0.96
        assert abs(similarity - expected) < 1e-6

    def test_cosine_similarity_dimension_mismatch(self):
        """测试:维度不匹配应抛出异常"""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.0, 2.0]

        with pytest.raises(ValueError, match="向量维度不匹配"):
            cosine_similarity(vec1, vec2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
