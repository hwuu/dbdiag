"""检索引擎

实现基于向量和关键词的混合检索
"""
import json
import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Set

from dbdiag.models import Phenomenon
from dbdiag.dao import PhenomenonDAO
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.vector_utils import deserialize_f32, cosine_similarity


@dataclass
class TicketMatch:
    """匹配到的工单信息"""

    ticket_id: str
    description: str
    root_cause: str
    similarity: float = 0.0


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
        self._phenomenon_dao = PhenomenonDAO(db_path)

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

        # 1. 向量检索（语义相似）
        if self.embedding_service:
            query_embedding = self.embedding_service.encode(query)

            # 获取所有有向量的现象
            rows = self._phenomenon_dao.get_all_with_embedding()

            candidates = []
            for row_dict in rows:
                emb_blob = row_dict["embedding"]

                # 反序列化向量
                embedding = deserialize_f32(emb_blob)

                # 计算相似度
                similarity = cosine_similarity(query_embedding, embedding)

                candidates.append((row_dict, similarity))

            # 按相似度排序，取 Top-N
            candidates.sort(key=lambda x: x[1], reverse=True)
            candidates = candidates[:vector_candidates]
        else:
            # 如果没有 embedding_service，获取所有现象
            rows = self._phenomenon_dao.get_all(limit=vector_candidates)
            candidates = [(row_dict, 0.5) for row_dict in rows]

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
            phenomenon = self._phenomenon_dao.dict_to_model(row_dict)

            scored_phenomena.append((phenomenon, final_score))

        # 4. 排序并返回 Top-K
        scored_phenomena.sort(key=lambda x: x[1], reverse=True)
        return scored_phenomena[:top_k]

    def search_by_ticket_description(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[TicketMatch]:
        """根据用户问题描述搜索相似的历史工单

        用于混合增强模式：从语义相似的历史工单中提取关联现象。

        Args:
            query: 用户问题描述
            top_k: 返回的最大工单数

        Returns:
            匹配的工单列表（按相似度降序）
        """
        if not self.embedding_service:
            return []

        # 生成查询向量
        query_embedding = self.embedding_service.encode(query)

        # 从 rar_raw_tickets 表检索（复用其向量）
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT ticket_id, description, root_cause, embedding
                FROM rar_raw_tickets
                WHERE embedding IS NOT NULL
                """
            )
            rows = cursor.fetchall()

            if not rows:
                return []

            # 计算相似度
            matches = []
            for row in rows:
                ticket_id, description, root_cause, embedding_blob = row
                ticket_embedding = deserialize_f32(embedding_blob)
                similarity = cosine_similarity(query_embedding, ticket_embedding)

                matches.append(
                    TicketMatch(
                        ticket_id=ticket_id,
                        description=description,
                        root_cause=root_cause,
                        similarity=similarity,
                    )
                )

            # 按相似度排序
            matches.sort(key=lambda m: m.similarity, reverse=True)
            return matches[:top_k]

        finally:
            conn.close()

    def get_phenomena_by_ticket_ids(
        self,
        ticket_ids: List[str],
    ) -> List[Phenomenon]:
        """根据工单 ID 获取关联的现象

        Args:
            ticket_ids: 工单 ID 列表

        Returns:
            去重后的现象列表
        """
        if not ticket_ids:
            return []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            placeholders = ",".join("?" * len(ticket_ids))
            cursor.execute(
                f"""
                SELECT DISTINCT p.phenomenon_id, p.description, p.observation_method,
                       p.source_anomaly_ids, p.cluster_size
                FROM phenomena p
                JOIN ticket_phenomena tp ON p.phenomenon_id = tp.phenomenon_id
                WHERE tp.ticket_id IN ({placeholders})
                """,
                ticket_ids,
            )
            rows = cursor.fetchall()

            phenomena = []
            for row in rows:
                # source_anomaly_ids 是 JSON 字符串
                source_ids = json.loads(row[3]) if row[3] else []
                phenomenon = Phenomenon(
                    phenomenon_id=row[0],
                    description=row[1],
                    observation_method=row[2] or "",
                    source_anomaly_ids=source_ids,
                    cluster_size=row[4] or 1,
                )
                phenomena.append(phenomenon)

            return phenomena

        finally:
            conn.close()
