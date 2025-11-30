"""RAR 检索器

从 rar_raw_tickets 表检索相关工单。
"""
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from dbdiag.models.rar import RARSessionState
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.vector_utils import deserialize_f32, cosine_similarity


@dataclass
class RARTicket:
    """RAR 检索到的工单"""

    ticket_id: str
    description: str
    root_cause: str
    solution: str
    combined_text: str
    similarity: float = 0.0


class RARRetriever:
    """RAR 检索器

    使用向量相似度从 rar_raw_tickets 检索相关工单。
    """

    def __init__(
        self,
        db_path: str,
        embedding_service: EmbeddingService,
    ):
        """初始化

        Args:
            db_path: 数据库路径
            embedding_service: Embedding 服务
        """
        self.db_path = db_path
        self.embedding_service = embedding_service

    def retrieve(
        self,
        state: RARSessionState,
        user_message: str,
        top_k: int = 10,
    ) -> List[RARTicket]:
        """检索相关工单

        Args:
            state: 会话状态
            user_message: 用户当前输入
            top_k: 返回的最大工单数

        Returns:
            相关工单列表（按相似度降序）
        """
        # 1. 构建检索 query
        query = self._build_search_query(state, user_message)

        # 2. 生成 query embedding
        query_embedding = self.embedding_service.encode(query)

        # 3. 从数据库检索所有工单及其 embedding
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT ticket_id, description, root_cause, solution, combined_text, embedding
                FROM rar_raw_tickets
                WHERE embedding IS NOT NULL
                """
            )
            rows = cursor.fetchall()

            if not rows:
                return []

            # 4. 计算相似度并排序
            tickets_with_sim = []
            for row in rows:
                ticket_id, description, root_cause, solution, combined_text, embedding_blob = row
                ticket_embedding = deserialize_f32(embedding_blob)
                similarity = cosine_similarity(query_embedding, ticket_embedding)

                tickets_with_sim.append(
                    RARTicket(
                        ticket_id=ticket_id,
                        description=description,
                        root_cause=root_cause,
                        solution=solution,
                        combined_text=combined_text,
                        similarity=similarity,
                    )
                )

            # 按相似度降序排序
            tickets_with_sim.sort(key=lambda t: t.similarity, reverse=True)

            return tickets_with_sim[:top_k]

        finally:
            conn.close()

    def _build_search_query(
        self,
        state: RARSessionState,
        user_message: str,
    ) -> str:
        """构建检索 query

        Args:
            state: 会话状态
            user_message: 用户当前输入

        Returns:
            检索 query 文本
        """
        parts = [state.user_problem]

        # 加入已确认的观察
        if state.confirmed_observations:
            parts.append("确认现象: " + ", ".join(state.confirmed_observations))

        # 加入当前用户输入（如果不是简单的确认/否定）
        if not self._is_simple_feedback(user_message):
            parts.append(user_message)

        return " ".join(parts)

    def _is_simple_feedback(self, message: str) -> bool:
        """判断是否为简单反馈（确认/否定）

        Args:
            message: 用户消息

        Returns:
            是否为简单反馈
        """
        simple_patterns = [
            "确认",
            "是的",
            "对",
            "有",
            "否定",
            "不是",
            "没有",
            "不对",
            "1",
            "2",
            "3",
            "是",
            "否",
        ]
        message_stripped = message.strip()
        return message_stripped in simple_patterns or len(message_stripped) <= 2
