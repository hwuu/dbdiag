"""Index Builder DAO

负责 rebuild-index 脚本的数据库写入操作
"""
import json
from typing import List, Dict, Any

from dbdiag.dao.base import BaseDAO
from dbdiag.utils.vector_utils import serialize_f32


class IndexBuilderDAO(BaseDAO):
    """索引重建数据访问对象

    封装 rebuild-index 脚本需要的所有写入操作，支持事务控制。
    """

    def rebuild_all(
        self,
        phenomena: List[Dict[str, Any]],
        raw_anomalies: List[Dict[str, Any]],
        anomaly_to_phenomenon: Dict[str, str],
        raw_root_causes: List[Dict[str, Any]],
        root_causes: List[Dict[str, Any]],
        raw_rc_to_standard: Dict[str, str],
    ) -> Dict[str, int]:
        """
        重建所有索引表

        Args:
            phenomena: 标准现象列表
            raw_anomalies: 原始异常列表
            anomaly_to_phenomenon: 异常ID到现象ID的映射
            raw_root_causes: 原始根因列表（聚类前）
            root_causes: 标准根因列表（聚类后）
            raw_rc_to_standard: 原始根因ID到标准根因ID的映射

        Returns:
            统计信息字典
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # 1. 清除旧数据
                cursor.execute("DELETE FROM phenomenon_root_causes")
                cursor.execute("DELETE FROM ticket_phenomena")
                cursor.execute("DELETE FROM phenomena")
                cursor.execute("DELETE FROM raw_root_causes")
                cursor.execute("DELETE FROM root_causes")

                # 2. 保存 phenomena
                for p in phenomena:
                    cursor.execute("""
                        INSERT INTO phenomena (
                            phenomenon_id, description, observation_method,
                            source_anomaly_ids, cluster_size, embedding
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        p["phenomenon_id"],
                        p["description"],
                        p["observation_method"],
                        json.dumps(p["source_anomaly_ids"]),
                        p["cluster_size"],
                        serialize_f32(p["embedding"]),
                    ))

                # 3. 保存 ticket_phenomena
                for anomaly in raw_anomalies:
                    phenomenon_id = anomaly_to_phenomenon[anomaly["id"]]
                    cursor.execute("""
                        INSERT INTO ticket_phenomena (
                            id, ticket_id, phenomenon_id, why_relevant, raw_anomaly_id
                        )
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        anomaly["id"],
                        anomaly["ticket_id"],
                        phenomenon_id,
                        anomaly["why_relevant"],
                        anomaly["id"],
                    ))

                # 4. 保存 raw_root_causes
                for rrc in raw_root_causes:
                    cursor.execute("""
                        INSERT INTO raw_root_causes (
                            id, description, solution, source_ticket_ids,
                            ticket_count, embedding
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        rrc["id"],
                        rrc["description"],
                        rrc["solution"],
                        json.dumps(rrc["source_ticket_ids"]),
                        rrc["ticket_count"],
                        serialize_f32(rrc["embedding"]) if rrc.get("embedding") else None,
                    ))

                # 5. 保存 root_causes（聚类后的标准根因）
                for rc in root_causes:
                    cursor.execute("""
                        INSERT INTO root_causes (
                            root_cause_id, description, solution,
                            source_raw_root_cause_ids, cluster_size,
                            related_ticket_ids, ticket_count, embedding
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        rc["root_cause_id"],
                        rc["description"],
                        rc["solution"],
                        json.dumps(rc["source_raw_root_cause_ids"]),
                        rc["cluster_size"],
                        json.dumps(rc["related_ticket_ids"]),
                        rc["ticket_count"],
                        serialize_f32(rc["embedding"]) if rc.get("embedding") else None,
                    ))

                # 6. 同步到 tickets 表
                self._sync_to_tickets_v2(cursor, raw_root_causes, raw_rc_to_standard)

                # 7. 构建 phenomenon_root_causes 表
                self._build_phenomenon_root_causes(cursor)

                conn.commit()

                # 8. 统计
                stats = self._get_stats(cursor)
                return stats

            except Exception:
                conn.rollback()
                raise

    def _build_root_causes(self, cursor) -> Dict[str, str]:
        """
        从 raw_tickets 提取唯一根因，生成 root_causes 表

        Returns:
            根因文本到 root_cause_id 的映射
        """
        # 1. 提取唯一根因及其统计信息
        cursor.execute("""
            SELECT
                root_cause,
                GROUP_CONCAT(ticket_id) as ticket_ids,
                COUNT(*) as ticket_count,
                MAX(solution) as solution
            FROM raw_tickets
            GROUP BY root_cause
            ORDER BY ticket_count DESC
        """)

        root_cause_rows = cursor.fetchall()
        root_cause_map = {}  # root_cause_text -> root_cause_id

        # 2. 清除旧数据
        cursor.execute("DELETE FROM root_causes")

        # 3. 生成 root_causes 记录
        for idx, row in enumerate(root_cause_rows):
            root_cause_text = row[0]
            ticket_ids = row[1].split(",") if row[1] else []
            ticket_count = row[2]
            solution = row[3] or ""

            root_cause_id = f"RC-{idx + 1:04d}"
            root_cause_map[root_cause_text] = root_cause_id

            # 查找该根因关联的现象 ID
            cursor.execute("""
                SELECT DISTINCT tp.phenomenon_id
                FROM ticket_phenomena tp
                WHERE tp.ticket_id IN (
                    SELECT ticket_id FROM raw_tickets WHERE root_cause = ?
                )
            """, (root_cause_text,))
            phenomenon_ids = [r[0] for r in cursor.fetchall()]

            cursor.execute("""
                INSERT INTO root_causes (
                    root_cause_id, description, solution,
                    key_phenomenon_ids, related_ticket_ids, ticket_count
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                root_cause_id,
                root_cause_text,
                solution,
                json.dumps(phenomenon_ids),
                json.dumps(ticket_ids),
                ticket_count,
            ))

        return root_cause_map

    def _sync_to_tickets(self, cursor, root_cause_map: Dict[str, str]) -> None:
        """
        同步数据到 tickets 表，包含 root_cause_id 外键

        Args:
            cursor: 数据库游标
            root_cause_map: 根因文本到 root_cause_id 的映射
        """
        # 先清空 tickets 表
        cursor.execute("DELETE FROM tickets")

        # 从 raw_tickets 读取数据并写入 tickets
        cursor.execute("""
            SELECT ticket_id, metadata_json, description, root_cause, solution
            FROM raw_tickets
        """)

        for row in cursor.fetchall():
            ticket_id, metadata_json, description, root_cause_text, solution = row
            root_cause_id = root_cause_map.get(root_cause_text)

            cursor.execute("""
                INSERT INTO tickets (
                    ticket_id, metadata_json, description,
                    root_cause_id, root_cause, solution
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ticket_id,
                metadata_json or "{}",
                description,
                root_cause_id,
                root_cause_text,
                solution,
            ))

    def _sync_to_tickets_v2(
        self,
        cursor,
        raw_root_causes: List[Dict[str, Any]],
        raw_rc_to_standard: Dict[str, str],
    ) -> None:
        """
        同步数据到 tickets 表，使用新的根因映射

        Args:
            cursor: 数据库游标
            raw_root_causes: 原始根因列表
            raw_rc_to_standard: 原始根因ID到标准根因ID的映射
        """
        # 构建 root_cause_text -> root_cause_id 映射
        # 通过 raw_root_causes 和 raw_rc_to_standard 推导
        root_cause_text_to_id: Dict[str, str] = {}
        for rrc in raw_root_causes:
            root_cause_text = rrc["description"]
            raw_rc_id = rrc["id"]
            standard_rc_id = raw_rc_to_standard.get(raw_rc_id)
            if standard_rc_id:
                root_cause_text_to_id[root_cause_text] = standard_rc_id

        # 先清空 tickets 表
        cursor.execute("DELETE FROM tickets")

        # 从 raw_tickets 读取数据并写入 tickets
        cursor.execute("""
            SELECT ticket_id, metadata_json, description, root_cause, solution
            FROM raw_tickets
        """)

        for row in cursor.fetchall():
            ticket_id, metadata_json, description, root_cause_text, solution = row
            root_cause_id = root_cause_text_to_id.get(root_cause_text)

            cursor.execute("""
                INSERT INTO tickets (
                    ticket_id, metadata_json, description,
                    root_cause_id, root_cause, solution
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ticket_id,
                metadata_json or "{}",
                description,
                root_cause_id,
                root_cause_text,
                solution,
            ))

    def _build_phenomenon_root_causes(self, cursor) -> None:
        """
        从 ticket_phenomena + tickets 推导 phenomenon_root_causes 关联表

        逻辑：phenomenon 出现在哪些 ticket 中，这些 ticket 的 root_cause 是什么
        """
        cursor.execute("""
            INSERT INTO phenomenon_root_causes (phenomenon_id, root_cause_id, ticket_count)
            SELECT
                tp.phenomenon_id,
                t.root_cause_id,
                COUNT(*) as ticket_count
            FROM ticket_phenomena tp
            JOIN tickets t ON tp.ticket_id = t.ticket_id
            WHERE t.root_cause_id IS NOT NULL
            GROUP BY tp.phenomenon_id, t.root_cause_id
        """)

    def _get_stats(self, cursor) -> Dict[str, int]:
        """获取统计信息"""
        cursor.execute("SELECT COUNT(*) FROM phenomena")
        phenomena_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ticket_phenomena")
        ticket_phenomena_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM phenomenon_root_causes")
        phenomenon_root_causes_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM raw_root_causes")
        raw_root_causes_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM root_causes")
        root_causes_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tickets")
        tickets_count = cursor.fetchone()[0]

        return {
            "phenomena": phenomena_count,
            "ticket_phenomena": ticket_phenomena_count,
            "phenomenon_root_causes": phenomenon_root_causes_count,
            "raw_root_causes": raw_root_causes_count,
            "root_causes": root_causes_count,
            "tickets": tickets_count,
        }
