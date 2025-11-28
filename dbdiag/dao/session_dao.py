"""Session DAO

负责 sessions 表的数据访问（原 session_service.py）
"""
import json
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime

from dbdiag.dao.base import BaseDAO
from dbdiag.models import SessionState


class SessionDAO(BaseDAO):
    """会话数据访问对象"""

    def create(self, user_problem: str) -> SessionState:
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

        self._save(session)
        return session

    def get(self, session_id: str) -> Optional[SessionState]:
        """
        获取会话状态

        Args:
            session_id: 会话 ID

        Returns:
            会话状态，如果不存在返回 None
        """
        with self.get_cursor() as (conn, cursor):
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

            state_data = json.loads(row["state_json"])
            return SessionState.from_dict(state_data)

    def update(self, session: SessionState) -> None:
        """
        更新会话状态

        Args:
            session: 会话状态
        """
        self._save(session, is_update=True)

    def delete(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否删除成功
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
            cursor.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        列出最近的会话

        Args:
            limit: 返回数量

        Returns:
            会话列表（摘要信息）
        """
        with self.get_cursor() as (conn, cursor):
            cursor.execute(
                """
                SELECT session_id, user_problem, created_at, updated_at
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def _save(self, session: SessionState, is_update: bool = False) -> None:
        """
        保存会话到数据库

        Args:
            session: 会话状态
            is_update: 是否为更新操作
        """
        with self.get_cursor(row_factory=False) as (conn, cursor):
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
