"""WebSocket 聊天端点

提供基于 WebSocket 的实时诊断交互。
每个 WebSocket 连接拥有独立的会话状态。
"""
import io
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from rich.console import Console
from rich.theme import Theme
import rich.markdown

from dbdiag.core.gar.dialogue_manager import GARDialogueManager
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.config import load_config
from dbdiag.cli.rendering import DiagnosisRenderer
from dbdiag.dao import RootCauseDAO
from dbdiag.dao.base import get_default_db_path

# 配置日志
logger = logging.getLogger(__name__)


# Monkey patch: 修复 Rich Markdown 标题默认居中的问题
def _left_aligned_heading_console(self, console, options):
    """左对齐的标题渲染"""
    self.text.justify = "left"
    yield self.text


rich.markdown.Heading.__rich_console__ = _left_aligned_heading_console

# 创建路由
router = APIRouter()


class WebChatSession:
    """WebSocket 聊天会话

    每个 WebSocket 连接对应一个独立的会话实例。
    """

    # 移除背景色的正则表达式
    _BG_PATTERN = re.compile(r'background-color:\s*#[0-9a-fA-F]+;?', re.IGNORECASE)
    # 移除 ANSI 控制序列
    _ANSI_PATTERN = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\[H')

    # 暗色主题
    _DARK_THEME = Theme({
        "dim": "#a0a0a0",
        "default": "#e8e8e8",
    })

    def __init__(self, websocket: WebSocket, config: dict):
        """初始化会话

        Args:
            websocket: WebSocket 连接
            config: 应用配置
        """
        self.websocket = websocket
        self.config = config

        # 使用 record=True 捕获输出为 HTML，file=io.StringIO() 禁止输出到 stdout
        self.console = Console(
            record=True,
            force_terminal=True,
            width=10000,  # 不限制宽度，由前端 CSS 控制换行
            theme=self._DARK_THEME,
            file=io.StringIO(),  # 静默输出
        )
        self.renderer = DiagnosisRenderer(self.console)

        # 数据库路径
        self.db_path = get_default_db_path()

        # 服务（延迟初始化）
        self._llm_service: Optional[LLMService] = None
        self._embedding_service: Optional[EmbeddingService] = None
        self._dialogue_manager: Optional[GARDialogueManager] = None
        self._root_cause_dao: Optional[RootCauseDAO] = None

        # 会话状态
        self.session_id: Optional[str] = None
        self.round_count: int = 0

        # 统计
        self.stats = {
            "recommended": 0,
            "confirmed": 0,
            "denied": 0,
            "top_hypotheses": [],
        }
        self._recommended_phenomenon_ids: set = set()

        # 诊断模式（从配置读取，默认 hyb）
        self.diagnosis_mode = config.get("web", {}).get("diagnosis_mode", "hyb")

    def _init_services(self):
        """延迟初始化服务（首次使用时）"""
        if self._llm_service is None:
            app_config = load_config()
            self._llm_service = LLMService(app_config)
            self._embedding_service = EmbeddingService(app_config)
            self._root_cause_dao = RootCauseDAO(self.db_path)

            # 根据模式创建对话管理器
            hybrid_mode = self.diagnosis_mode == "hyb"
            self._dialogue_manager = GARDialogueManager(
                self.db_path,
                self._llm_service,
                self._embedding_service,
                progress_callback=self._on_progress,
                recommender_config=app_config.recommender,
                hybrid_mode=hybrid_mode,
            )

    def _on_progress(self, message: str):
        """进度回调（可选：发送进度消息给客户端）"""
        # 目前不发送进度消息，保持简单
        pass

    async def handle_message(self, msg: dict) -> dict:
        """处理传入消息

        Args:
            msg: 消息字典 {"type": "message"|"command", "content": "..."}

        Returns:
            响应字典 {"type": "output"|"close", "html": "..."}
        """
        msg_type = msg.get("type", "message")
        content = msg.get("content", "").strip()

        if not content:
            return {"type": "output", "html": ""}

        if msg_type == "command" or content.startswith("/"):
            return await self._process_command(content)
        else:
            return await self._process_diagnosis(content)

    async def _process_diagnosis(self, content: str) -> dict:
        """处理诊断消息"""
        self._init_services()

        self.round_count += 1

        # 渲染轮次标题
        self.console.print()
        self.console.print(f"[bold]• 第 {self.round_count} 轮[/bold]")

        try:
            if not self.session_id:
                self.console.print("  [dim]正在分析问题...[/dim]")
                response = self._dialogue_manager.start_conversation(content)
                self.session_id = response.get("session_id")
            else:
                self.console.print("  [dim]正在处理反馈...[/dim]")
                response = self._dialogue_manager.continue_conversation(
                    self.session_id, content
                )

            self.console.print()

            # 更新统计并渲染状态栏
            self._update_stats_from_session()
            status_bar = self.renderer.render_status_bar(
                round_count=self.round_count,
                recommended=self.stats["recommended"],
                confirmed=self.stats["confirmed"],
                denied=self.stats["denied"],
                hypotheses=self.stats["top_hypotheses"],
            )
            self.console.print("  ", status_bar)
            self.console.print()

            # 渲染响应
            action = response.get("action", "")
            if action == "recommend_phenomenon":
                self._render_phenomenon_recommendation(response)
            elif action == "confirm_root_cause":
                self._render_root_cause_confirmation(response)
            else:
                message = response.get("message", "")
                if message:
                    self.console.print(f"  {message}")

        except Exception as e:
            self.console.print(f"  [red]处理失败: {str(e)}[/red]")

        # 导出为 HTML
        html = self._export_html()
        return {"type": "output", "html": html}

    async def _process_command(self, command: str) -> dict:
        """处理 CLI 命令"""
        command = command.lower().strip()

        if command == "/help":
            help_panel = self.renderer.render_help("gar")
            self.console.print(help_panel)

        elif command == "/status":
            if not self.session_id:
                self.console.print("[yellow]还没有开始诊断会话[/yellow]")
            else:
                self._init_services()
                self._update_stats_from_session()
                status_bar = self.renderer.render_status_bar(
                    round_count=self.round_count,
                    recommended=self.stats["recommended"],
                    confirmed=self.stats["confirmed"],
                    denied=self.stats["denied"],
                    hypotheses=self.stats["top_hypotheses"],
                )
                self.console.print(status_bar)

        elif command == "/reset":
            self.session_id = None
            self.round_count = 0
            self.stats = {"recommended": 0, "confirmed": 0, "denied": 0, "top_hypotheses": []}
            self._recommended_phenomenon_ids = set()
            self.console.print("[green]会话已重置，请重新描述问题[/green]")

        elif command == "/exit":
            self.console.print("[blue]再见！[/blue]")
            html = self._export_html()
            return {"type": "close", "html": html}

        else:
            self.console.print(f"[red]未知命令: {command}[/red]，输入 /help 查看可用命令")

        html = self._export_html()
        return {"type": "output", "html": html}

    def _render_phenomenon_recommendation(self, response: dict):
        """渲染现象推荐"""
        phenomena_with_reasons = response.get("phenomena_with_reasons", [])

        if not phenomena_with_reasons:
            phenomena = response.get("phenomena", [])
            if not phenomena and response.get("phenomenon"):
                phenomena = [response["phenomenon"]]
            if phenomena:
                phenomena_with_reasons = [{"phenomenon": p, "reason": ""} for p in phenomena]

        if not phenomena_with_reasons:
            self.console.print(f"  {response.get('message', '')}")
            return

        # 更新统计（去重）
        for item in phenomena_with_reasons:
            phenomenon = item["phenomenon"]
            if phenomenon.phenomenon_id not in self._recommended_phenomenon_ids:
                self._recommended_phenomenon_ids.add(phenomenon.phenomenon_id)
                self.stats["recommended"] += 1

        # 渲染
        recommendation = self.renderer.render_phenomenon_recommendation(phenomena_with_reasons)
        self.console.print("  ", recommendation)

    def _render_root_cause_confirmation(self, response: dict):
        """渲染根因确认"""
        root_cause = response.get("root_cause", "未知")
        diagnosis_summary = response.get("diagnosis_summary", "")
        citations = response.get("citations", [])

        result = self.renderer.render_diagnosis_result(
            root_cause=root_cause,
            diagnosis_summary=diagnosis_summary,
            citations=citations,
            show_border=False,  # Web 不显示边框
        )
        self.console.print()
        self.console.print("  ", result)

    def _update_stats_from_session(self):
        """从 session 更新统计信息"""
        if not self.session_id or not self._dialogue_manager:
            return

        session = self._dialogue_manager.session_service.get_session(self.session_id)
        if not session:
            return

        self.stats["confirmed"] = len(session.confirmed_phenomena)
        self.stats["denied"] = len(session.denied_phenomena)

        self.stats["top_hypotheses"] = []
        if session.active_hypotheses:
            for hyp in session.active_hypotheses[:3]:
                desc = self._root_cause_dao.get_description(hyp.root_cause_id)
                self.stats["top_hypotheses"].append((hyp.confidence, desc))

    def render_welcome(self) -> str:
        """渲染欢迎消息"""
        # LOGO
        logo = self.renderer.get_logo(self.diagnosis_mode)
        if self.diagnosis_mode == "hyb":
            self.console.print(f"[bold green]{logo}[/bold green]")
            self.console.print("[bold green]混合增强推理方法[/bold green]")
        elif self.diagnosis_mode == "rar":
            self.console.print(f"[bold magenta]{logo}[/bold magenta]")
            self.console.print("[bold magenta]检索增强推理方法[/bold magenta]")
        else:
            self.console.print(f"[bold blue]{logo}[/bold blue]")
            self.console.print("[bold blue]图谱增强推理方法[/bold blue]")

        self.console.print()
        self.console.print("[dim]可用命令: /help /status /reset /exit[/dim]")
        self.console.print()
        self.console.print("[bold yellow]请描述您遇到的数据库问题开始诊断。[/bold yellow]")
        self.console.print()

        return self._export_html()

    def cleanup(self):
        """清理会话资源"""
        # 目前无需特殊清理
        pass

    def _export_html(self) -> str:
        """导出 HTML 并清理样式"""
        html = self.console.export_html(inline_styles=True, clear=True)
        # 移除 Rich 导出的背景色
        html = self._BG_PATTERN.sub('', html)
        # 移除 ANSI 控制序列
        html = self._ANSI_PATTERN.sub('', html)
        # 移除残留的控制字符
        html = html.replace('[H', '').replace('\x1b', '')
        return html


# 全局配置（延迟加载）
_config: Optional[dict] = None


def _get_config() -> dict:
    """获取配置"""
    global _config
    if _config is None:
        _config = {}
        try:
            app_config = load_config()
            _config["web"] = {
                "diagnosis_mode": app_config.web.diagnosis_mode,
            }
        except Exception:
            pass
    return _config


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket 聊天端点

    每个连接拥有独立的会话状态。
    """
    await websocket.accept()

    # 获取客户端 IP
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"[{client_host}] WebSocket 连接建立")

    config = _get_config()
    session = WebChatSession(websocket, config)

    # 发送欢迎消息
    welcome_html = session.render_welcome()
    await websocket.send_json({
        "type": "output",
        "html": welcome_html,
    })

    try:
        while True:
            # 接收消息
            msg = await websocket.receive_json()
            content = msg.get("content", "")

            # 记录输入
            logger.info(f"[{client_host}] <- input: {len(content)} chars")

            response = await session.handle_message(msg)

            # 记录输出
            html_len = len(response.get("html", ""))
            logger.info(f"[{client_host}] -> output: {html_len} chars")

            # 发送响应
            await websocket.send_json(response)

            # 检查是否需要关闭
            if response.get("type") == "close":
                break

    except WebSocketDisconnect:
        logger.info(f"[{client_host}] WebSocket 连接断开")
    finally:
        session.cleanup()
