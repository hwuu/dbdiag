"""Ticket DAO

负责 tickets 和 ticket_anomalies 表的数据访问
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
                SELECT DISTINCT ta.ticket_id, t.root_cause_id
                FROM ticket_anomalies ta
                JOIN tickets t ON ta.ticket_id = t.ticket_id
                WHERE ta.phenomenon_id = ?
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

    def count(self) -> int:
        """
        获取工单总数

        Returns:
            工单数量
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute("SELECT COUNT(*) FROM tickets")
            return cursor.fetchone()[0]


class TicketAnomalyDAO(BaseDAO):
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
                SELECT DISTINCT ta.phenomenon_id
                FROM ticket_anomalies ta
                JOIN tickets t ON ta.ticket_id = t.ticket_id
                WHERE t.root_cause_id = ?
                """,
                (root_cause_id,),
            )
            return {row[0] for row in cursor.fetchall()}

    def get_ticket_anomalies_by_phenomenon(
        self, phenomenon_id: str
    ) -> List[Dict[str, Any]]:
        """
        获取某个现象关联的所有工单异常记录

        Args:
            phenomenon_id: 现象 ID

        Returns:
            工单异常记录列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT id, ticket_id, phenomenon_id, why_relevant, raw_anomaly_id
                FROM ticket_anomalies
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
                FROM ticket_anomalies
            """)
            return [dict(row) for row in cursor.fetchall()]
