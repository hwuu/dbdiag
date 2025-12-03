"""DAO 基类

提供数据库连接管理的基础功能
"""
import os
import sqlite3
from typing import Optional
from pathlib import Path
from contextlib import contextmanager


def get_default_db_path() -> str:
    """获取默认数据库路径

    优先从环境变量 DATA_DIR 读取，否则使用项目根目录的 data/tickets.db
    """
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        return str(Path(data_dir) / "tickets.db")
    project_root = Path(__file__).parent.parent.parent
    return str(project_root / "data" / "tickets.db")


class BaseDAO:
    """DAO 基类

    提供数据库连接管理和通用操作
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 DAO

        Args:
            db_path: 数据库路径，如果为 None 则使用默认路径（优先环境变量 DATA_DIR）
        """
        if db_path is None:
            db_path = get_default_db_path()

        self.db_path = db_path

    @contextmanager
    def get_connection(self, row_factory: bool = True):
        """
        获取数据库连接的上下文管理器

        Args:
            row_factory: 是否启用 Row 工厂（允许通过列名访问）

        Yields:
            sqlite3.Connection: 数据库连接
        """
        conn = sqlite3.connect(self.db_path)
        if row_factory:
            conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def get_cursor(self, row_factory: bool = True):
        """
        获取数据库游标的上下文管理器

        Args:
            row_factory: 是否启用 Row 工厂

        Yields:
            tuple: (connection, cursor)
        """
        with self.get_connection(row_factory) as conn:
            cursor = conn.cursor()
            yield conn, cursor
