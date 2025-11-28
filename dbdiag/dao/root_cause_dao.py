"""Root Cause DAO

负责 root_causes 表的数据访问
"""
from typing import List, Optional, Dict, Any

from dbdiag.dao.base import BaseDAO


class RootCauseDAO(BaseDAO):
    """根因数据访问对象"""

    def get_description(self, root_cause_id: str) -> str:
        """
        获取根因描述文本

        Args:
            root_cause_id: 根因 ID

        Returns:
            根因描述文本，找不到时返回 root_cause_id
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                """
                SELECT description
                FROM root_causes
                WHERE root_cause_id = ?
                """,
                (root_cause_id,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
            return root_cause_id

    def get_solution(self, root_cause_id: str) -> str:
        """
        获取根因的解决方案

        Args:
            root_cause_id: 根因 ID

        Returns:
            解决方案文本
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                """
                SELECT solution
                FROM root_causes
                WHERE root_cause_id = ?
                """,
                (root_cause_id,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
            return "暂无具体解决方案，请参考相关工单。"

    def get_by_id(self, root_cause_id: str) -> Optional[Dict[str, Any]]:
        """
        按 ID 获取根因详情

        Args:
            root_cause_id: 根因 ID

        Returns:
            根因字典，不存在则返回 None
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT root_cause_id, description, solution,
                       key_phenomenon_ids, related_ticket_ids, ticket_count
                FROM root_causes
                WHERE root_cause_id = ?
                """,
                (root_cause_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all(self) -> List[Dict[str, Any]]:
        """
        获取所有根因

        Returns:
            根因列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT root_cause_id, description, solution, ticket_count
                FROM root_causes
                ORDER BY ticket_count DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """
        获取根因总数

        Returns:
            根因数量
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute("SELECT COUNT(*) FROM root_causes")
            return cursor.fetchone()[0]
