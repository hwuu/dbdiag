"""会话状态持久化服务

向后兼容包装器，实际实现已迁移到 dbdiag.dao.session_dao
"""
import warnings
from typing import Optional, List, Dict, Any

from dbdiag.dao.session_dao import SessionDAO
from dbdiag.models import SessionState


class SessionService:
    """会话服务（向后兼容包装器）

    实际实现已迁移到 SessionDAO，此类为向后兼容保留。
    建议直接使用 dbdiag.dao.SessionDAO。
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化会话服务

        Args:
            db_path: 数据库路径
        """
        self._dao = SessionDAO(db_path)
        self.db_path = self._dao.db_path

    def create_session(self, user_problem: str) -> SessionState:
        """创建新会话"""
        return self._dao.create(user_problem)

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """获取会话状态"""
        return self._dao.get(session_id)

    def update_session(self, session: SessionState) -> None:
        """更新会话状态"""
        self._dao.update(session)

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        return self._dao.delete(session_id)

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """列出最近的会话"""
        return self._dao.list_recent(limit)
