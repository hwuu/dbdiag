"""Raw Anomaly DAO

负责 raw_anomalies 表的数据访问
"""
from typing import List, Dict, Any

from dbdiag.dao.base import BaseDAO


class RawAnomalyDAO(BaseDAO):
    """原始异常数据访问对象"""

    def get_all(self) -> List[Dict[str, Any]]:
        """
        获取所有原始异常

        Returns:
            原始异常列表（按 ticket_id, anomaly_index 排序）
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute("""
                SELECT id, ticket_id, anomaly_index, description,
                       observation_method, why_relevant
                FROM raw_anomalies
                ORDER BY ticket_id, anomaly_index
            """)
            return [dict(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """
        获取原始异常总数

        Returns:
            异常数量
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute("SELECT COUNT(*) FROM raw_anomalies")
            return cursor.fetchone()[0]
