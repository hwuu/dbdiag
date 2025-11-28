"""init_db 单元测试"""
import pytest
import sqlite3
import tempfile
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.scripts.init_db import init_database


class TestInitDatabase:
    """数据库初始化测试"""

    def test_init_database_creates_file(self):
        """测试:初始化数据库应创建文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)
            assert os.path.exists(db_path)

    def test_init_database_creates_all_tables(self):
        """测试:初始化数据库应创建所有表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()

            # V1 表（保留兼容）
            assert "tickets" in tables
            assert "diagnostic_steps" in tables
            assert "sessions" in tables
            assert "root_causes" in tables  # V2 重命名：root_cause_patterns → root_causes

            # V2 新增表
            assert "raw_tickets" in tables
            assert "raw_anomalies" in tables
            assert "phenomena" in tables
            assert "ticket_anomalies" in tables

    def test_tickets_table_structure(self):
        """测试:tickets 表结构（包含 root_cause_id）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(tickets)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            conn.close()

            assert "ticket_id" in columns
            assert "root_cause_id" in columns  # V2 新增
            assert "root_cause" in columns     # 保留兼容
            assert "solution" in columns

    def test_root_causes_table_structure(self):
        """测试:root_causes 表结构"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(root_causes)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            conn.close()

            assert "root_cause_id" in columns
            assert "description" in columns
            assert "solution" in columns
            assert "key_phenomenon_ids" in columns
            assert "related_ticket_ids" in columns
            assert "ticket_count" in columns
            assert "embedding" in columns

    def test_raw_tickets_table_structure(self):
        """测试:raw_tickets 表结构"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(raw_tickets)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            conn.close()

            assert "ticket_id" in columns
            assert "metadata_json" in columns
            assert "description" in columns
            assert "root_cause" in columns
            assert "solution" in columns
            assert "created_at" in columns

    def test_raw_anomalies_table_structure(self):
        """测试:raw_anomalies 表结构"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(raw_anomalies)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            conn.close()

            assert "id" in columns
            assert "ticket_id" in columns
            assert "anomaly_index" in columns
            assert "description" in columns
            assert "observation_method" in columns
            assert "why_relevant" in columns
            assert "created_at" in columns

    def test_phenomena_table_structure(self):
        """测试:phenomena 表结构"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(phenomena)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            conn.close()

            assert "phenomenon_id" in columns
            assert "description" in columns
            assert "observation_method" in columns
            assert "source_anomaly_ids" in columns
            assert "cluster_size" in columns
            assert "embedding" in columns
            assert "created_at" in columns

    def test_ticket_anomalies_table_structure(self):
        """测试:ticket_anomalies 表结构"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(ticket_anomalies)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            conn.close()

            assert "id" in columns
            assert "ticket_id" in columns
            assert "phenomenon_id" in columns
            assert "why_relevant" in columns
            assert "raw_anomaly_id" in columns

    def test_phenomena_fts_table_exists(self):
        """测试:phenomena 全文检索表应存在"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='phenomena_fts'")
            result = cursor.fetchone()
            conn.close()

            assert result is not None

    def test_idempotent_initialization(self):
        """测试:多次初始化应该是幂等的"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            # 第一次初始化
            init_database(db_path)

            # 插入测试数据
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO raw_tickets (ticket_id, metadata_json, description, root_cause, solution)
                VALUES ('T001', '{}', 'test', 'test', 'test')
            """)
            conn.commit()
            conn.close()

            # 第二次初始化（不应删除数据）
            init_database(db_path)

            # 验证数据仍然存在
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT ticket_id FROM raw_tickets WHERE ticket_id='T001'")
            result = cursor.fetchone()
            conn.close()

            assert result is not None
            assert result[0] == "T001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
