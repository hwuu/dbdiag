"""Phenomenon DAO

负责 phenomena 表的数据访问
"""
import json
from typing import List, Optional, Set, Dict, Any

from dbdiag.dao.base import BaseDAO
from dbdiag.models import Phenomenon
from dbdiag.utils.vector_utils import deserialize_f32


class PhenomenonDAO(BaseDAO):
    """现象数据访问对象"""

    def get_all_with_embedding(self) -> List[Dict[str, Any]]:
        """
        获取所有有向量的现象

        Returns:
            包含 embedding 的现象字典列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT
                    phenomenon_id, description, observation_method,
                    source_anomaly_ids, cluster_size, embedding
                FROM phenomena
                WHERE embedding IS NOT NULL
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_all(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取所有现象（不含 embedding）

        Args:
            limit: 返回数量限制

        Returns:
            现象字典列表
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT
                    phenomenon_id, description, observation_method,
                    source_anomaly_ids, cluster_size
                FROM phenomena
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_by_ids(self, phenomenon_ids: List[str]) -> List[Dict[str, Any]]:
        """
        按 ID 获取现象详情

        Args:
            phenomenon_ids: 现象 ID 列表

        Returns:
            现象详情列表
        """
        if not phenomenon_ids:
            return []

        with self.get_cursor() as (conn, cursor):
            placeholders = ",".join("?" * len(phenomenon_ids))
            cursor.execute(
                f"""
                SELECT phenomenon_id, description, observation_method
                FROM phenomena
                WHERE phenomenon_id IN ({placeholders})
                """,
                phenomenon_ids,
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_by_id(self, phenomenon_id: str) -> Optional[Dict[str, Any]]:
        """
        按 ID 获取单个现象

        Args:
            phenomenon_id: 现象 ID

        Returns:
            现象字典，不存在则返回 None
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT phenomenon_id, description, observation_method,
                       source_anomaly_ids, cluster_size
                FROM phenomena
                WHERE phenomenon_id = ?
                """,
                (phenomenon_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def dict_to_model(self, row_dict: Dict[str, Any]) -> Phenomenon:
        """
        将字典转换为 Phenomenon 模型

        Args:
            row_dict: 数据库行字典

        Returns:
            Phenomenon 对象
        """
        source_ids = row_dict.get("source_anomaly_ids", "[]")
        if isinstance(source_ids, str):
            source_ids = json.loads(source_ids)

        return Phenomenon(
            phenomenon_id=row_dict["phenomenon_id"],
            description=row_dict["description"],
            observation_method=row_dict["observation_method"],
            source_anomaly_ids=source_ids,
            cluster_size=row_dict.get("cluster_size", 1),
        )

    def count(self) -> int:
        """
        获取现象总数

        Returns:
            现象数量
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute("SELECT COUNT(*) FROM phenomena")
            return cursor.fetchone()[0]
