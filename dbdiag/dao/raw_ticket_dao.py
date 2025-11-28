"""Raw Ticket DAO

负责 raw_tickets 表的数据访问
"""
import json
from typing import List, Dict, Any, Set, Tuple

from dbdiag.dao.base import BaseDAO


class RawTicketDAO(BaseDAO):
    """原始工单数据访问对象"""

    def get_all(self) -> List[Dict[str, Any]]:
        """
        获取所有原始工单

        Returns:
            工单列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute("""
                SELECT ticket_id, metadata_json, description, root_cause, solution
                FROM raw_tickets
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_all_root_causes(self) -> Set[str]:
        """
        获取所有唯一的根因

        Returns:
            根因集合
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute("SELECT DISTINCT root_cause FROM raw_tickets")
            return {row[0] for row in cursor.fetchall()}

    def count(self) -> int:
        """
        获取原始工单总数

        Returns:
            工单数量
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute("SELECT COUNT(*) FROM raw_tickets")
            return cursor.fetchone()[0]

    def insert_batch(
        self, tickets: List[Dict[str, Any]]
    ) -> Tuple[int, int, int]:
        """
        批量插入工单及其异常

        Args:
            tickets: 工单数据列表，每个工单包含 anomalies 字段

        Returns:
            (成功数, 跳过数, 异常数) 元组
        """
        imported_count = 0
        skipped_count = 0
        anomaly_count = 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                for ticket in tickets:
                    try:
                        anomalies_imported = self._insert_ticket(cursor, ticket)
                        imported_count += 1
                        anomaly_count += anomalies_imported
                    except Exception as e:
                        if "UNIQUE constraint failed" in str(e):
                            skipped_count += 1
                        else:
                            raise

                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return imported_count, skipped_count, anomaly_count

    def _insert_ticket(self, cursor, ticket: Dict[str, Any]) -> int:
        """
        插入单个工单及其异常

        Args:
            cursor: 数据库游标
            ticket: 工单数据字典

        Returns:
            导入的异常数量
        """
        ticket_id = ticket["ticket_id"]
        metadata = ticket.get("metadata", {})
        description = ticket["description"]
        root_cause = ticket["root_cause"]
        solution = ticket["solution"]
        anomalies = ticket.get("anomalies", [])

        # 插入到 raw_tickets
        cursor.execute(
            """
            INSERT INTO raw_tickets (ticket_id, metadata_json, description, root_cause, solution)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
                description,
                root_cause,
                solution,
            ),
        )

        # 插入异常到 raw_anomalies
        for index, anomaly in enumerate(anomalies):
            anomaly_id = f"{ticket_id}_anomaly_{index + 1}"

            cursor.execute(
                """
                INSERT INTO raw_anomalies (
                    id, ticket_id, anomaly_index,
                    description, observation_method, why_relevant
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    anomaly_id,
                    ticket_id,
                    index + 1,
                    anomaly["description"],
                    anomaly["observation_method"],
                    anomaly["why_relevant"],
                ),
            )

        return len(anomalies)
