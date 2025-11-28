"""DAO 层单元测试"""
import pytest
import sqlite3
import tempfile
import os
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.scripts.init_db import init_database
from dbdiag.dao import (
    BaseDAO, PhenomenonDAO, TicketDAO, TicketAnomalyDAO,
    RootCauseDAO, SessionDAO
)
from dbdiag.models import Phenomenon
from dbdiag.utils.vector_utils import serialize_f32


class TestBaseDAO:
    """BaseDAO 测试"""

    def test_default_db_path(self):
        """测试: 默认数据库路径"""
        dao = BaseDAO()
        assert dao.db_path.endswith("tickets.db")

    def test_custom_db_path(self):
        """测试: 自定义数据库路径"""
        dao = BaseDAO("/custom/path.db")
        assert dao.db_path == "/custom/path.db"

    def test_get_connection_context_manager(self):
        """测试: get_connection 上下文管理器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            dao = BaseDAO(db_path)
            with dao.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                assert "phenomena" in tables

    def test_get_cursor_context_manager(self):
        """测试: get_cursor 上下文管理器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_database(db_path)

            dao = BaseDAO(db_path)
            with dao.get_cursor() as (conn, cursor):
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                assert len(tables) > 0


class TestPhenomenonDAO:
    """PhenomenonDAO 测试"""

    def _setup_test_db(self, tmpdir: str) -> str:
        """创建测试数据库"""
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 插入测试数据
        phenomena = [
            ("P-0001", "wait_io 事件占比异常高", "SELECT wait_event FROM pg_stat_activity",
             json.dumps(["a1"]), 1, serialize_f32([0.1, 0.2, 0.3])),
            ("P-0002", "索引大小异常增长", "SELECT pg_relation_size(indexrelid)",
             json.dumps(["a2"]), 1, serialize_f32([0.4, 0.5, 0.6])),
        ]

        for p in phenomena:
            cursor.execute("""
                INSERT INTO phenomena (phenomenon_id, description, observation_method,
                                       source_anomaly_ids, cluster_size, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
            """, p)

        conn.commit()
        conn.close()
        return db_path

    def test_get_by_id_exists(self):
        """测试: 获取存在的现象"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = PhenomenonDAO(db_path)

            result = dao.get_by_id("P-0001")

            assert result is not None
            assert result["phenomenon_id"] == "P-0001"
            assert "wait_io" in result["description"]

    def test_get_by_id_not_exists(self):
        """测试: 获取不存在的现象"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = PhenomenonDAO(db_path)

            result = dao.get_by_id("P-9999")

            assert result is None

    def test_get_by_ids(self):
        """测试: 批量获取现象"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = PhenomenonDAO(db_path)

            result = dao.get_by_ids(["P-0001", "P-0002"])

            assert len(result) == 2

    def test_get_by_ids_empty(self):
        """测试: 空 ID 列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = PhenomenonDAO(db_path)

            result = dao.get_by_ids([])

            assert result == []

    def test_get_all_with_embedding(self):
        """测试: 获取所有有向量的现象"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = PhenomenonDAO(db_path)

            result = dao.get_all_with_embedding()

            assert len(result) == 2
            assert all("embedding" in r for r in result)

    def test_dict_to_model(self):
        """测试: 字典转模型"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = PhenomenonDAO(db_path)

            row_dict = dao.get_by_id("P-0001")
            model = dao.dict_to_model(row_dict)

            assert isinstance(model, Phenomenon)
            assert model.phenomenon_id == "P-0001"
            assert model.description == "wait_io 事件占比异常高"


class TestTicketDAO:
    """TicketDAO 测试"""

    def _setup_test_db(self, tmpdir: str) -> str:
        """创建测试数据库"""
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 插入 root_causes
        cursor.execute("""
            INSERT INTO root_causes (root_cause_id, description, solution, ticket_count)
            VALUES ('RC-0001', 'IO 瓶颈', '优化磁盘配置', 2)
        """)

        # 插入 tickets
        cursor.execute("""
            INSERT INTO tickets (ticket_id, metadata_json, description, root_cause_id, root_cause, solution)
            VALUES ('T-001', '{}', '报表查询慢', 'RC-0001', 'IO 瓶颈', '优化磁盘')
        """)
        cursor.execute("""
            INSERT INTO tickets (ticket_id, metadata_json, description, root_cause_id, root_cause, solution)
            VALUES ('T-002', '{}', 'IO 等待高', 'RC-0001', 'IO 瓶颈', '增加 IOPS')
        """)

        # 插入 phenomena
        cursor.execute("""
            INSERT INTO phenomena (phenomenon_id, description, observation_method,
                                   source_anomaly_ids, cluster_size)
            VALUES ('P-0001', 'wait_io 高', 'SELECT ...', '[]', 1)
        """)

        # 插入 ticket_anomalies
        cursor.execute("""
            INSERT INTO ticket_anomalies (id, ticket_id, phenomenon_id, why_relevant)
            VALUES ('T-001_a1', 'T-001', 'P-0001', '与 IO 相关')
        """)
        cursor.execute("""
            INSERT INTO ticket_anomalies (id, ticket_id, phenomenon_id, why_relevant)
            VALUES ('T-002_a1', 'T-002', 'P-0001', '与 IO 相关')
        """)

        conn.commit()
        conn.close()
        return db_path

    def test_get_by_root_cause_id(self):
        """测试: 根据根因 ID 获取工单"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = TicketDAO(db_path)

            result = dao.get_by_root_cause_id("RC-0001")

            assert len(result) == 2
            assert all("ticket_id" in r for r in result)

    def test_get_by_root_cause_id_with_limit(self):
        """测试: 限制返回数量"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = TicketDAO(db_path)

            result = dao.get_by_root_cause_id("RC-0001", limit=1)

            assert len(result) == 1

    def test_get_by_phenomenon_id(self):
        """测试: 根据现象 ID 获取工单"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = TicketDAO(db_path)

            result = dao.get_by_phenomenon_id("P-0001")

            assert len(result) == 2


class TestTicketAnomalyDAO:
    """TicketAnomalyDAO 测试"""

    def _setup_test_db(self, tmpdir: str) -> str:
        """创建测试数据库"""
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 插入 raw_tickets
        cursor.execute("""
            INSERT INTO raw_tickets (ticket_id, description, root_cause, solution)
            VALUES ('T-001', '报表查询慢', 'IO 瓶颈', '优化磁盘')
        """)
        cursor.execute("""
            INSERT INTO raw_tickets (ticket_id, description, root_cause, solution)
            VALUES ('T-002', 'IO 等待高', 'IO 瓶颈', '增加 IOPS')
        """)

        # 插入 root_causes
        cursor.execute("""
            INSERT INTO root_causes (root_cause_id, description, solution, ticket_count)
            VALUES ('RC-0001', 'IO 瓶颈', '优化磁盘配置', 2)
        """)

        # 插入 tickets
        cursor.execute("""
            INSERT INTO tickets (ticket_id, metadata_json, description, root_cause_id, root_cause, solution)
            VALUES ('T-001', '{}', '报表查询慢', 'RC-0001', 'IO 瓶颈', '优化磁盘')
        """)
        cursor.execute("""
            INSERT INTO tickets (ticket_id, metadata_json, description, root_cause_id, root_cause, solution)
            VALUES ('T-002', '{}', 'IO 等待高', 'RC-0001', 'IO 瓶颈', '增加 IOPS')
        """)

        # 插入 phenomena
        cursor.execute("""
            INSERT INTO phenomena (phenomenon_id, description, observation_method,
                                   source_anomaly_ids, cluster_size)
            VALUES ('P-0001', 'wait_io 高', 'SELECT ...', '[]', 1)
        """)
        cursor.execute("""
            INSERT INTO phenomena (phenomenon_id, description, observation_method,
                                   source_anomaly_ids, cluster_size)
            VALUES ('P-0002', '索引膨胀', 'SELECT ...', '[]', 1)
        """)

        # 插入 ticket_anomalies
        cursor.execute("""
            INSERT INTO ticket_anomalies (id, ticket_id, phenomenon_id, why_relevant)
            VALUES ('T-001_a1', 'T-001', 'P-0001', '与 IO 相关')
        """)
        cursor.execute("""
            INSERT INTO ticket_anomalies (id, ticket_id, phenomenon_id, why_relevant)
            VALUES ('T-002_a1', 'T-002', 'P-0002', '索引问题')
        """)

        conn.commit()
        conn.close()
        return db_path

    def test_get_phenomena_by_root_cause_id(self):
        """测试: 根据根因 ID 获取关联现象"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = TicketAnomalyDAO(db_path)

            result = dao.get_phenomena_by_root_cause_id("RC-0001")

            assert isinstance(result, set)
            assert "P-0001" in result or "P-0002" in result


class TestRootCauseDAO:
    """RootCauseDAO 测试"""

    def _setup_test_db(self, tmpdir: str) -> str:
        """创建测试数据库"""
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO root_causes (root_cause_id, description, solution, ticket_count)
            VALUES ('RC-0001', 'IO 瓶颈导致查询变慢', '优化磁盘配置，增加 IOPS', 3)
        """)

        conn.commit()
        conn.close()
        return db_path

    def test_get_description_exists(self):
        """测试: 获取存在的根因描述"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = RootCauseDAO(db_path)

            result = dao.get_description("RC-0001")

            assert result == "IO 瓶颈导致查询变慢"

    def test_get_description_not_exists(self):
        """测试: 获取不存在的根因描述"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = RootCauseDAO(db_path)

            result = dao.get_description("RC-9999")

            assert result == "RC-9999"  # 返回 ID 本身

    def test_get_solution_exists(self):
        """测试: 获取存在的解决方案"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = RootCauseDAO(db_path)

            result = dao.get_solution("RC-0001")

            assert "优化磁盘配置" in result

    def test_get_solution_not_exists(self):
        """测试: 获取不存在的解决方案"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = RootCauseDAO(db_path)

            result = dao.get_solution("RC-9999")

            assert result == "暂无具体解决方案，请参考相关工单。"


class TestSessionDAO:
    """SessionDAO 测试"""

    def _setup_test_db(self, tmpdir: str) -> str:
        """创建测试数据库"""
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)
        return db_path

    def test_create_session(self):
        """测试: 创建会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = SessionDAO(db_path)

            session = dao.create("查询变慢了")

            assert session.session_id is not None
            assert session.user_problem == "查询变慢了"

    def test_get_session(self):
        """测试: 获取会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = SessionDAO(db_path)

            created = dao.create("查询变慢了")
            retrieved = dao.get(created.session_id)

            assert retrieved is not None
            assert retrieved.session_id == created.session_id
            assert retrieved.user_problem == "查询变慢了"

    def test_get_session_not_exists(self):
        """测试: 获取不存在的会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = SessionDAO(db_path)

            result = dao.get("nonexistent-id")

            assert result is None

    def test_update_session(self):
        """测试: 更新会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = SessionDAO(db_path)

            session = dao.create("查询变慢了")
            session.user_problem = "查询变慢 - 已更新"
            dao.update(session)

            retrieved = dao.get(session.session_id)

            assert retrieved.user_problem == "查询变慢 - 已更新"

    def test_delete_session(self):
        """测试: 删除会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = SessionDAO(db_path)

            session = dao.create("查询变慢了")
            result = dao.delete(session.session_id)

            assert result is True
            assert dao.get(session.session_id) is None

    def test_delete_session_not_exists(self):
        """测试: 删除不存在的会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = SessionDAO(db_path)

            result = dao.delete("nonexistent-id")

            assert result is False

    def test_list_recent(self):
        """测试: 列出最近会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._setup_test_db(tmpdir)
            dao = SessionDAO(db_path)

            dao.create("问题 1")
            dao.create("问题 2")
            dao.create("问题 3")

            result = dao.list_recent(limit=2)

            assert len(result) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
