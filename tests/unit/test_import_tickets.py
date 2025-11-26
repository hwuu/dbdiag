"""import_tickets 单元测试"""
import pytest
import sqlite3
import tempfile
import os
import json
from pathlib import Path
import sys
import warnings

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.init_db import init_database
from scripts.import_tickets import import_tickets, import_tickets_v2


class TestImportTicketsV2:
    """V2 导入功能测试"""

    def _create_test_data_v2(self, tmpdir: str) -> str:
        """创建 V2 格式的测试数据"""
        data = [
            {
                "ticket_id": "TICKET-001",
                "metadata": {"version": "PostgreSQL-14.5", "module": "query_optimizer"},
                "description": "在线报表查询突然变慢",
                "root_cause": "索引膨胀导致 IO 瓶颈",
                "solution": "执行 REINDEX",
                "anomalies": [
                    {
                        "description": "wait_io 事件占比 65%",
                        "observation_method": "SELECT event FROM pg_stat_activity",
                        "why_relevant": "IO 等待高说明磁盘瓶颈"
                    },
                    {
                        "description": "索引大小增长 6 倍",
                        "observation_method": "SELECT pg_relation_size(indexrelid)",
                        "why_relevant": "索引膨胀导致逻辑读放大"
                    }
                ]
            },
            {
                "ticket_id": "TICKET-002",
                "metadata": {"version": "PostgreSQL-15.0"},
                "description": "连接数过多",
                "root_cause": "连接泄漏",
                "solution": "修复连接池",
                "anomalies": [
                    {
                        "description": "活跃连接数 500",
                        "observation_method": "SELECT count(*) FROM pg_stat_activity",
                        "why_relevant": "连接数异常说明存在泄漏"
                    }
                ]
            }
        ]
        data_path = os.path.join(tmpdir, "tickets_v2.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return data_path

    def test_import_tickets_v2_to_raw_tables(self):
        """测试:V2 导入应写入 raw_tickets 和 raw_anomalies 表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)
            data_path = self._create_test_data_v2(tmpdir)

            import_tickets_v2(data_path, db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 验证 raw_tickets
            cursor.execute("SELECT COUNT(*) FROM raw_tickets")
            assert cursor.fetchone()[0] == 2

            # 验证 raw_anomalies
            cursor.execute("SELECT COUNT(*) FROM raw_anomalies")
            assert cursor.fetchone()[0] == 3  # 2 + 1

            conn.close()

    def test_import_tickets_v2_raw_ticket_content(self):
        """测试:V2 导入的 raw_tickets 内容正确"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)
            data_path = self._create_test_data_v2(tmpdir)

            import_tickets_v2(data_path, db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT ticket_id, description, root_cause FROM raw_tickets WHERE ticket_id='TICKET-001'")
            row = cursor.fetchone()

            assert row[0] == "TICKET-001"
            assert "报表查询" in row[1]
            assert "索引膨胀" in row[2]

            conn.close()

    def test_import_tickets_v2_raw_anomaly_content(self):
        """测试:V2 导入的 raw_anomalies 内容正确"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)
            data_path = self._create_test_data_v2(tmpdir)

            import_tickets_v2(data_path, db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, ticket_id, anomaly_index, description, why_relevant
                FROM raw_anomalies
                WHERE ticket_id='TICKET-001'
                ORDER BY anomaly_index
            """)
            rows = cursor.fetchall()

            assert len(rows) == 2

            # 第一个异常
            assert rows[0][0] == "TICKET-001_anomaly_1"
            assert rows[0][2] == 1  # anomaly_index
            assert "wait_io" in rows[0][3]
            assert "IO 等待" in rows[0][4]

            # 第二个异常
            assert rows[1][0] == "TICKET-001_anomaly_2"
            assert rows[1][2] == 2

            conn.close()

    def test_import_tickets_v2_skip_duplicate(self):
        """测试:V2 导入应跳过重复数据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)
            data_path = self._create_test_data_v2(tmpdir)

            # 第一次导入
            import_tickets_v2(data_path, db_path)

            # 第二次导入（应跳过重复）
            import_tickets_v2(data_path, db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM raw_tickets")
            assert cursor.fetchone()[0] == 2  # 仍然是 2

            conn.close()

    def test_import_tickets_v2_file_not_found(self):
        """测试:V2 导入不存在的文件应抛出异常"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            with pytest.raises(FileNotFoundError):
                import_tickets_v2("/nonexistent/path.json", db_path)


class TestImportTicketsV1Deprecated:
    """V1 导入功能测试（deprecated）"""

    def _create_test_data_v1(self, tmpdir: str) -> str:
        """创建 V1 格式的测试数据"""
        data = [
            {
                "ticket_id": "T001",
                "metadata": {"version": "14.5"},
                "description": "查询慢",
                "root_cause": "索引问题",
                "solution": "重建索引",
                "diagnostic_steps": [
                    {
                        "observed_fact": "wait_io 高",
                        "observation_method": "SELECT",
                        "analysis_result": "IO 瓶颈"
                    }
                ]
            }
        ]
        data_path = os.path.join(tmpdir, "tickets_v1.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return data_path

    def test_import_tickets_v1_still_works(self):
        """测试:V1 导入仍然可用（向后兼容）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)
            data_path = self._create_test_data_v1(tmpdir)

            # V1 导入应该仍然可用
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                import_tickets(data_path, db_path)

                # 验证触发了 deprecation 警告
                deprecation_warnings = [
                    warning for warning in w
                    if issubclass(warning.category, DeprecationWarning)
                ]
                assert len(deprecation_warnings) >= 1

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # V1 表应该有数据
            cursor.execute("SELECT COUNT(*) FROM tickets")
            assert cursor.fetchone()[0] == 1

            cursor.execute("SELECT COUNT(*) FROM diagnostic_steps")
            assert cursor.fetchone()[0] == 1

            conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
