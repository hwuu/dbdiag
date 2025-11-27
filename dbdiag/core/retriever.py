"""检索引擎

实现基于向量和关键词的混合检索
"""
import sqlite3
import json
from typing import List, Optional, Set

from dbdiag.models import Phenomenon
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.vector_utils import deserialize_f32, cosine_similarity


class PhenomenonRetriever:
    """现象检索器

    从 phenomena 表中检索相关的标准现象。
    """

    def __init__(self, db_path: str, embedding_service: EmbeddingService = None):
        """
        初始化检索器

        Args:
            db_path: 数据库路径
            embedding_service: Embedding 服务实例
        """
        self.db_path = db_path
        self.embedding_service = embedding_service

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        vector_candidates: int = 50,
        keywords: Optional[List[str]] = None,
        excluded_phenomenon_ids: Optional[Set[str]] = None,
    ) -> List[tuple[Phenomenon, float]]:
        """
        检索相关的标准现象

        Args:
            query: 查询文本
            top_k: 返回前 K 个结果
            vector_candidates: 向量召回候选数量
            keywords: 关键词列表（用于过滤）
            excluded_phenomenon_ids: 已确认的现象 ID（降低权重）

        Returns:
            (现象, 得分) 列表，按得分降序排列
        """
        if excluded_phenomenon_ids is None:
            excluded_phenomenon_ids = set()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # 1. 向量检索（语义相似）
            if self.embedding_service:
                query_embedding = self.embedding_service.encode(query)

                # 获取所有有向量的现象
                cursor.execute(
                    """
                    SELECT
                        phenomenon_id, description, observation_method,
                        source_anomaly_ids, cluster_size, embedding
                    FROM phenomena
                    WHERE embedding IS NOT NULL
                    """
                )

                candidates = []
                for row in cursor.fetchall():
                    emb_blob = row["embedding"]

                    # 反序列化向量
                    embedding = deserialize_f32(emb_blob)

                    # 计算相似度
                    similarity = cosine_similarity(query_embedding, embedding)

                    candidates.append((dict(row), similarity))

                # 按相似度排序，取 Top-N
                candidates.sort(key=lambda x: x[1], reverse=True)
                candidates = candidates[:vector_candidates]
            else:
                # 如果没有 embedding_service，获取所有现象
                cursor.execute(
                    """
                    SELECT
                        phenomenon_id, description, observation_method,
                        source_anomaly_ids, cluster_size
                    FROM phenomena
                    """
                )
                candidates = [(dict(row), 0.5) for row in cursor.fetchall()[:vector_candidates]]

            # 2. 关键词过滤（如果提供）
            if keywords:
                filtered_candidates = []
                for row_dict, similarity in candidates:
                    # 检查是否包含关键词
                    text = f"{row_dict['description']} {row_dict['observation_method']}"
                    if any(keyword.lower() in text.lower() for keyword in keywords):
                        filtered_candidates.append((row_dict, similarity))
                candidates = filtered_candidates

            # 3. 重排序（综合评分）
            scored_phenomena = []
            for row_dict, vector_score in candidates:
                phenomenon_id = row_dict["phenomenon_id"]

                # 3.1 向量相似度（权重 50%）
                vector_score_weight = 0.5 * vector_score

                # 3.2 现象新颖度（权重 30%）
                novelty = 0.3 if phenomenon_id not in excluded_phenomenon_ids else 0.1

                # 3.3 关键词匹配度（权重 20%）
                keyword_score = 0.0
                if keywords:
                    text = f"{row_dict['description']} {row_dict['observation_method']}"
                    matched = sum(1 for kw in keywords if kw.lower() in text.lower())
                    keyword_score = 0.2 * (matched / len(keywords))
                else:
                    keyword_score = 0.2  # 无关键词时给默认分

                # 综合评分
                final_score = vector_score_weight + novelty + keyword_score

                # 构建 Phenomenon 对象
                source_ids = row_dict.get("source_anomaly_ids", "[]")
                if isinstance(source_ids, str):
                    source_ids = json.loads(source_ids)

                phenomenon = Phenomenon(
                    phenomenon_id=row_dict["phenomenon_id"],
                    description=row_dict["description"],
                    observation_method=row_dict["observation_method"],
                    source_anomaly_ids=source_ids,
                    cluster_size=row_dict.get("cluster_size", 1),
                )

                scored_phenomena.append((phenomenon, final_score))

            # 4. 排序并返回 Top-K
            scored_phenomena.sort(key=lambda x: x[1], reverse=True)
            return scored_phenomena[:top_k]

        finally:
            conn.close()
