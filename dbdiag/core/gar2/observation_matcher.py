"""观察匹配器

将用户观察描述匹配到标准现象库、根因库和历史工单。
"""

import sqlite3
from typing import List, Tuple, Optional

from dbdiag.dao import PhenomenonDAO, RootCauseDAO
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.vector_utils import cosine_similarity, deserialize_f32
from dbdiag.core.gar2.models import (
    MatchResult, PhenomenonMatch, RootCauseMatch, TicketMatch
)


class ObservationMatcher:
    """观察匹配器

    使用向量相似度将用户观察匹配到三类目标：
    1. phenomena - 标准现象库
    2. root_causes - 根因库
    3. tickets - 历史工单（通过 rar_raw_tickets）

    Attributes:
        match_threshold: 匹配阈值，低于此值视为未匹配
    """

    def __init__(
        self,
        db_path: str,
        embedding_service: EmbeddingService,
        match_threshold: float = 0.75,
    ):
        """初始化观察匹配器

        Args:
            db_path: 数据库路径
            embedding_service: 向量服务
            match_threshold: 匹配阈值
        """
        self.db_path = db_path
        self.embedding_service = embedding_service
        self.match_threshold = match_threshold
        self._phenomenon_dao = PhenomenonDAO(db_path)
        self._root_cause_dao = RootCauseDAO(db_path)

    def match_all(
        self, observation_text: str, top_k: int = 5
    ) -> MatchResult:
        """匹配观察到三类目标

        同时匹配 phenomena、root_causes、tickets，返回综合结果。

        Args:
            observation_text: 用户观察描述
            top_k: 每类返回最多 k 个匹配结果

        Returns:
            MatchResult 包含三类匹配结果
        """
        # 生成观察向量
        obs_embedding = self.embedding_service.encode(observation_text)
        if not obs_embedding:
            return MatchResult()

        # 并行匹配三类目标
        phenomena = self._match_phenomena(obs_embedding, top_k)
        root_causes = self._match_root_causes(obs_embedding, top_k)
        tickets = self._match_tickets(obs_embedding, top_k)

        return MatchResult(
            phenomena=phenomena,
            root_causes=root_causes,
            tickets=tickets,
        )

    def _match_phenomena(
        self, obs_embedding: List[float], top_k: int
    ) -> List[PhenomenonMatch]:
        """匹配现象库"""
        all_phenomena = self._phenomenon_dao.get_all_with_embedding()
        if not all_phenomena:
            return []

        results = []
        for phenomenon in all_phenomena:
            if not phenomenon.get("embedding"):
                continue

            phen_embedding = deserialize_f32(phenomenon["embedding"])
            similarity = cosine_similarity(obs_embedding, phen_embedding)

            if similarity >= self.match_threshold:
                results.append(PhenomenonMatch(
                    phenomenon_id=phenomenon["phenomenon_id"],
                    score=similarity,
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def _match_root_causes(
        self, obs_embedding: List[float], top_k: int
    ) -> List[RootCauseMatch]:
        """匹配根因库"""
        all_root_causes = self._root_cause_dao.get_all_with_embedding()
        if not all_root_causes:
            return []

        results = []
        for rc in all_root_causes:
            if not rc.get("embedding"):
                continue

            rc_embedding = deserialize_f32(rc["embedding"])
            similarity = cosine_similarity(obs_embedding, rc_embedding)

            if similarity >= self.match_threshold:
                results.append(RootCauseMatch(
                    root_cause_id=rc["root_cause_id"],
                    score=similarity,
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def _match_tickets(
        self, obs_embedding: List[float], top_k: int
    ) -> List[TicketMatch]:
        """匹配历史工单（使用 rar_raw_tickets 表）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 检查表是否存在
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='rar_raw_tickets'"
            )
            if not cursor.fetchone():
                return []

            cursor.execute(
                """
                SELECT ticket_id, root_cause, embedding
                FROM rar_raw_tickets
                WHERE embedding IS NOT NULL
                """
            )
            rows = cursor.fetchall()

            if not rows:
                return []

            # 需要从 tickets 表获取 root_cause_id
            results = []
            for ticket_id, root_cause_text, embedding_blob in rows:
                ticket_embedding = deserialize_f32(embedding_blob)
                similarity = cosine_similarity(obs_embedding, ticket_embedding)

                if similarity >= self.match_threshold:
                    # 查找对应的 root_cause_id
                    root_cause_id = self._get_root_cause_id_for_ticket(cursor, ticket_id)
                    if root_cause_id:
                        results.append(TicketMatch(
                            ticket_id=ticket_id,
                            root_cause_id=root_cause_id,
                            score=similarity,
                        ))

            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]

        finally:
            conn.close()

    def _get_root_cause_id_for_ticket(
        self, cursor, ticket_id: str
    ) -> Optional[str]:
        """获取工单对应的 root_cause_id"""
        cursor.execute(
            "SELECT root_cause_id FROM tickets WHERE ticket_id = ?",
            (ticket_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    # ===== 兼容旧接口 =====

    def match(
        self, observation_text: str, top_k: int = 5
    ) -> List[Tuple[str, float]]:
        """匹配观察到现象（兼容旧接口）

        Args:
            observation_text: 用户观察描述
            top_k: 返回最多 k 个匹配结果

        Returns:
            匹配结果列表 [(phenomenon_id, match_score), ...]
            按 match_score 降序排列，只返回超过阈值的结果
        """
        result = self.match_all(observation_text, top_k)
        return [(m.phenomenon_id, m.score) for m in result.phenomena]

    def match_best(
        self, observation_text: str
    ) -> Optional[Tuple[str, float]]:
        """获取最佳匹配（兼容旧接口）

        Args:
            observation_text: 用户观察描述

        Returns:
            最佳匹配 (phenomenon_id, match_score)，如果无匹配则返回 None
        """
        results = self.match(observation_text, top_k=1)
        return results[0] if results else None

    def match_batch(
        self, observation_texts: List[str], top_k: int = 1
    ) -> List[Optional[Tuple[str, float]]]:
        """批量匹配（兼容旧接口）

        Args:
            observation_texts: 观察描述列表
            top_k: 每个观察返回最多 k 个匹配

        Returns:
            匹配结果列表，每项为 (phenomenon_id, match_score) 或 None
        """
        results = []
        for text in observation_texts:
            match = self.match_best(text) if top_k == 1 else self.match(text, top_k)
            results.append(match)
        return results
