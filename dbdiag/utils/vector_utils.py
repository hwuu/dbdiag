"""向量计算工具函数"""
import struct
from typing import List
import math


def deserialize_f32(blob: bytes) -> List[float]:
    """
    反序列化 BLOB 为浮点向量

    Args:
        blob: 序列化的字节数据

    Returns:
        浮点向量
    """
    count = len(blob) // 4  # float32 每个 4 字节
    return list(struct.unpack(f"{count}f", blob))


def serialize_f32(vector: List[float]) -> bytes:
    """
    将浮点向量序列化为 BLOB

    Args:
        vector: 浮点向量

    Returns:
        序列化后的字节数据
    """
    return struct.pack(f"{len(vector)}f", *vector)


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    计算两个向量的余弦相似度

    Args:
        vec1: 向量 1
        vec2: 向量 2

    Returns:
        余弦相似度（0-1 之间）
    """
    if len(vec1) != len(vec2):
        raise ValueError(f"向量维度不匹配: {len(vec1)} vs {len(vec2)}")

    # 点积
    dot_product = sum(a * b for a, b in zip(vec1, vec2))

    # 模长
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)
