"""会话状态持久化服务

负责会话的创建、读取、更新和删除
"""
import sqlite3
import json
import uuid
from typing import Optional
from datetime import datetime
from pathlib import Path

from dbdiag.models import SessionState


class SessionService:
    """会话服务"""

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化会话服务

        Args:
            db_path: 数据库路径
        """
        if db_path is None:
            project_root = Path(__file__).parent.parent.parent
            db_path = str(project_root / "data" / "tickets.db")

        self.db_path = db_path

    def create_session(self, user_problem: str) -> SessionState:
        """
        创建新会话

        Args:
            user_problem: 用户问题描述

        Returns:
            新创建的会话状态
        """
        session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        session = SessionState(
            session_id=session_id,
            user_problem=user_problem,
        )

        self._save_session(session)
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """
        获取会话状态

        Args:
            session_id: 会话 ID

        Returns:
            会话状态，如果不存在返回 None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT session_id, user_problem, state_json, created_at, updated_at
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            # 解析 state_json
            state_data = json.loads(row["state_json"])

            return SessionState.from_dict(state_data)

        finally:
            conn.close()

    def update_session(self, session: SessionState) -> None:
        """
        更新会话状态

        Args:
            session: 会话状态
        """
        self._save_session(session, is_update=True)

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否删除成功
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

        finally:
            conn.close()

    def list_sessions(self, limit: int = 10) -> list[dict]:
        """
        列出最近的会话

        Args:
            limit: 返回数量

        Returns:
            会话列表（摘要信息）
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT session_id, user_problem, created_at, updated_at
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()

    def _save_session(self, session: SessionState, is_update: bool = False) -> None:
        """
        保存会话到数据库

        Args:
            session: 会话状态
            is_update: 是否为更新操作
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            state_json = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)

            if is_update:
                cursor.execute(
                    """
                    UPDATE sessions
                    SET user_problem = ?,
                        state_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = ?
                    """,
                    (session.user_problem, state_json, session.session_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO sessions (session_id, user_problem, state_json)
                    VALUES (?, ?, ?)
                    """,
                    (session.session_id, session.user_problem, state_json),
                )

            conn.commit()

        finally:
            conn.close()
