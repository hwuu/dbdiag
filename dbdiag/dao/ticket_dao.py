"""Ticket DAO

负责 tickets 和 ticket_phenomena 表的数据访问
"""
from typing import List, Optional, Dict, Any, Set

from dbdiag.dao.base import BaseDAO


class TicketDAO(BaseDAO):
    """工单数据访问对象"""

    def get_by_root_cause_id(
        self, root_cause_id: str, limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        获取某个根因的工单

        Args:
            root_cause_id: 根因 ID
            limit: 返回数量限制

        Returns:
            工单列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT ticket_id, description, root_cause, solution
                FROM tickets
                WHERE root_cause_id = ?
                LIMIT ?
                """,
                (root_cause_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_by_phenomenon_id(self, phenomenon_id: str) -> List[Dict[str, Any]]:
        """
        获取关联某个现象的工单

        Args:
            phenomenon_id: 现象 ID

        Returns:
            工单列表，包含 ticket_id 和 root_cause_id
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT DISTINCT tp.ticket_id, t.root_cause_id
                FROM ticket_phenomena tp
                JOIN tickets t ON tp.ticket_id = t.ticket_id
                WHERE tp.phenomenon_id = ?
                  AND t.root_cause_id IS NOT NULL
                """,
                (phenomenon_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_by_id(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """
        按 ID 获取单个工单

        Args:
            ticket_id: 工单 ID

        Returns:
            工单字典，不存在则返回 None
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT ticket_id, description, root_cause, root_cause_id, solution
                FROM tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all(self) -> List[Dict[str, Any]]:
        """
        获取所有工单

        Returns:
            工单列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT ticket_id, description, root_cause, root_cause_id, solution
                FROM tickets
                ORDER BY ticket_id
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """
        获取工单总数

        Returns:
            工单数量
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute("SELECT COUNT(*) FROM tickets")
            return cursor.fetchone()[0]


class TicketPhenomenonDAO(BaseDAO):
    """工单-现象关联数据访问对象"""

    def get_phenomena_by_root_cause_id(self, root_cause_id: str) -> Set[str]:
        """
        获取与某个根因关联的所有现象 ID

        Args:
            root_cause_id: 根因 ID

        Returns:
            现象 ID 集合
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                """
                SELECT DISTINCT tp.phenomenon_id
                FROM ticket_phenomena tp
                JOIN tickets t ON tp.ticket_id = t.ticket_id
                WHERE t.root_cause_id = ?
                """,
                (root_cause_id,),
            )
            return {row[0] for row in cursor.fetchall()}

    def get_ticket_phenomena_by_phenomenon(
        self, phenomenon_id: str
    ) -> List[Dict[str, Any]]:
        """
        获取某个现象关联的所有工单记录

        Args:
            phenomenon_id: 现象 ID

        Returns:
            工单记录列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT id, ticket_id, phenomenon_id, why_relevant, raw_anomaly_id
                FROM ticket_phenomena
                WHERE phenomenon_id = ?
                """,
                (phenomenon_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_all_associations(self) -> List[Dict[str, Any]]:
        """
        获取所有工单-现象关联

        Returns:
            关联记录列表，包含 ticket_id 和 phenomenon_id
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute("""
                SELECT ticket_id, phenomenon_id
                FROM ticket_phenomena
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_root_causes_by_phenomenon_id(self, phenomenon_id: str) -> Set[str]:
        """
        获取与某个现象关联的所有根因 ID

        Args:
            phenomenon_id: 现象 ID

        Returns:
            根因 ID 集合
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                """
                SELECT DISTINCT t.root_cause_id
                FROM ticket_phenomena tp
                JOIN tickets t ON tp.ticket_id = t.ticket_id
                WHERE tp.phenomenon_id = ?
                  AND t.root_cause_id IS NOT NULL
                """,
                (phenomenon_id,),
            )
            return {row[0] for row in cursor.fetchall()}

    def get_phenomena_count_by_ticket_id(self, ticket_id: str) -> int:
        """
        获取某个工单包含的现象数量

        Args:
            ticket_id: 工单 ID

        Returns:
            现象数量
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                """
                SELECT COUNT(DISTINCT phenomenon_id)
                FROM ticket_phenomena
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            )
            return cursor.fetchone()[0]

    def get_best_ticket_by_phenomena(
        self, phenomenon_ids: Set[str], root_cause_id: str
    ) -> Optional[str]:
        """
        根据已确认现象找到最匹配的工单

        找到包含最多已确认现象的工单，用于确定归一化因子。

        Args:
            phenomenon_ids: 已确认的现象 ID 集合
            root_cause_id: 目标根因 ID

        Returns:
            最匹配的工单 ID，如果没有匹配则返回 None
        """
        if not phenomenon_ids:
            return None

        with self.get_cursor(row_factory=False) as (conn, cursor):
            # 查找该根因下包含已确认现象最多的工单
            placeholders = ",".join("?" * len(phenomenon_ids))
            cursor.execute(
                f"""
                SELECT tp.ticket_id, COUNT(DISTINCT tp.phenomenon_id) as match_count
                FROM ticket_phenomena tp
                JOIN tickets t ON tp.ticket_id = t.ticket_id
                WHERE t.root_cause_id = ?
                  AND tp.phenomenon_id IN ({placeholders})
                GROUP BY tp.ticket_id
                ORDER BY match_count DESC
                LIMIT 1
                """,
                (root_cause_id, *phenomenon_ids),
            )
            row = cursor.fetchone()
            return row[0] if row else None


class PhenomenonRootCauseDAO(BaseDAO):
    """现象-根因关联数据访问对象"""

    def get_root_causes_by_phenomenon_id(self, phenomenon_id: str) -> Set[str]:
        """
        获取与某个现象直接关联的所有根因 ID

        Args:
            phenomenon_id: 现象 ID

        Returns:
            根因 ID 集合
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                """
                SELECT root_cause_id
                FROM phenomenon_root_causes
                WHERE phenomenon_id = ?
                """,
                (phenomenon_id,),
            )
            return {row[0] for row in cursor.fetchall()}

    def get_phenomena_by_root_cause_id(self, root_cause_id: str) -> Set[str]:
        """
        获取与某个根因直接关联的所有现象 ID

        Args:
            root_cause_id: 根因 ID

        Returns:
            现象 ID 集合
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                """
                SELECT phenomenon_id
                FROM phenomenon_root_causes
                WHERE root_cause_id = ?
                """,
                (root_cause_id,),
            )
            return {row[0] for row in cursor.fetchall()}

    def get_root_causes_with_ticket_count(self, phenomenon_id: str) -> Dict[str, int]:
        """
        获取与某个现象关联的所有根因及其 ticket_count

        Args:
            phenomenon_id: 现象 ID

        Returns:
            {root_cause_id: ticket_count} 字典
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                """
                SELECT root_cause_id, ticket_count
                FROM phenomenon_root_causes
                WHERE phenomenon_id = ?
                """,
                (phenomenon_id,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_all(self) -> List[Dict[str, Any]]:
        """
        获取所有现象-根因关联

        Returns:
            关联记录列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute("""
                SELECT phenomenon_id, root_cause_id, ticket_count
                FROM phenomenon_root_causes
                ORDER BY phenomenon_id, root_cause_id
            """)
            return [dict(row) for row in cursor.fetchall()]
