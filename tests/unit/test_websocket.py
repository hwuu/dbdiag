"""WebSocket 模块单元测试"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from dbdiag.api.websocket import WebChatSession


def run_async(coro):
    """运行异步函数，兼容没有事件循环的情况"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class TestWebChatSession:
    """WebChatSession 测试"""

    @pytest.fixture
    def mock_websocket(self):
        """创建模拟 WebSocket"""
        ws = MagicMock()
        ws.send_json = AsyncMock()
        ws.receive_json = AsyncMock()
        return ws

    @pytest.fixture
    def session(self, mock_websocket):
        """创建会话实例"""
        config = {"web": {"diagnosis_mode": "hyb"}}
        return WebChatSession(mock_websocket, config)

    # ===== 初始化测试 =====

    def test_init_default_config(self, mock_websocket):
        """测试默认配置初始化"""
        session = WebChatSession(mock_websocket, {})
        assert session.diagnosis_mode == "gar2"  # 默认 gar2
        assert session.session_id is None
        assert session.round_count == 0

    def test_init_custom_config(self, mock_websocket):
        """测试自定义配置初始化"""
        config = {"web": {"diagnosis_mode": "gar"}}
        session = WebChatSession(mock_websocket, config)
        assert session.diagnosis_mode == "gar"

    def test_init_rar_mode(self, mock_websocket):
        """测试 RAR 模式配置"""
        config = {"web": {"diagnosis_mode": "rar"}}
        session = WebChatSession(mock_websocket, config)
        assert session.diagnosis_mode == "rar"

    # ===== render_welcome 测试 =====

    def test_render_welcome_hyb(self, mock_websocket):
        """测试 HYB 模式欢迎消息"""
        config = {"web": {"diagnosis_mode": "hyb"}}
        session = WebChatSession(mock_websocket, config)
        html = session.render_welcome()
        assert html  # 非空
        assert "<" in html  # 包含 HTML 标签

    def test_render_welcome_gar(self, mock_websocket):
        """测试 GAR 模式欢迎消息"""
        config = {"web": {"diagnosis_mode": "gar"}}
        session = WebChatSession(mock_websocket, config)
        html = session.render_welcome()
        assert html

    def test_render_welcome_rar(self, mock_websocket):
        """测试 RAR 模式欢迎消息"""
        config = {"web": {"diagnosis_mode": "rar"}}
        session = WebChatSession(mock_websocket, config)
        html = session.render_welcome()
        assert html

    # ===== _process_command 测试 =====

    def test_process_command_help(self, session):
        """测试 /help 命令"""
        result = run_async(
            session._process_command("/help")
        )
        assert result["type"] == "output"
        assert result["html"]

    def test_process_command_status_no_session(self, session):
        """测试 /status 命令（无会话）"""
        result = run_async(
            session._process_command("/status")
        )
        assert result["type"] == "output"
        assert result["html"]

    def test_process_command_reset(self, session):
        """测试 /reset 命令"""
        session.session_id = "test-session"
        session.round_count = 5
        session.stats["confirmed"] = 3

        result = run_async(
            session._process_command("/reset")
        )

        assert result["type"] == "output"
        assert session.session_id is None
        assert session.round_count == 0
        assert session.stats["confirmed"] == 0

    def test_process_command_exit(self, session):
        """测试 /exit 命令"""
        result = run_async(
            session._process_command("/exit")
        )
        assert result["type"] == "close"
        assert result["html"]

    def test_process_command_unknown(self, session):
        """测试未知命令"""
        result = run_async(
            session._process_command("/unknown")
        )
        assert result["type"] == "output"
        assert result["html"]

    # ===== handle_message 测试 =====

    def test_handle_message_empty(self, session):
        """测试空消息"""
        result = run_async(
            session.handle_message({"type": "message", "content": ""})
        )
        assert result["type"] == "output"
        assert result["html"] == ""

    def test_handle_message_command(self, session):
        """测试命令消息"""
        result = run_async(
            session.handle_message({"type": "command", "content": "/help"})
        )
        assert result["type"] == "output"

    def test_handle_message_command_prefix(self, session):
        """测试以 / 开头的消息自动识别为命令"""
        result = run_async(
            session.handle_message({"type": "message", "content": "/reset"})
        )
        assert result["type"] == "output"
        assert session.session_id is None

    # ===== 统计测试 =====

    def test_stats_initial(self, session):
        """测试初始统计"""
        assert session.stats["recommended"] == 0
        assert session.stats["confirmed"] == 0
        assert session.stats["denied"] == 0
        assert session.stats["top_hypotheses"] == []

    def test_recommended_phenomenon_tracking(self, session):
        """测试推荐现象去重"""
        session._recommended_phenomenon_ids.add("P-0001")
        session.stats["recommended"] = 1

        # 模拟再次推荐同一个现象
        assert "P-0001" in session._recommended_phenomenon_ids

    # ===== cleanup 测试 =====

    def test_cleanup(self, session):
        """测试清理方法"""
        session.cleanup()  # 应该不抛出异常

    # ===== 边界情况测试 =====

    def test_handle_message_whitespace_only(self, session):
        """测试仅空白消息"""
        result = run_async(
            session.handle_message({"type": "message", "content": "   "})
        )
        assert result["type"] == "output"
        assert result["html"] == ""

    def test_handle_message_missing_content(self, session):
        """测试缺少 content 字段"""
        result = run_async(
            session.handle_message({"type": "message"})
        )
        assert result["type"] == "output"
        assert result["html"] == ""

    def test_handle_message_missing_type(self, session):
        """测试缺少 type 字段（默认 message）"""
        # 由于 _process_diagnosis 需要数据库，这里只测试命令路径
        result = run_async(
            session.handle_message({"content": "/help"})
        )
        assert result["type"] == "output"
