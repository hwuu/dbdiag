"""CLI 主程序

提供命令行交互界面进行数据库问题诊断。
"""
import sys
from pathlib import Path
from typing import Optional

from cli.formatter import TextFormatter
from dbdiag.core.dialogue_manager import DialogueManager
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.config import load_config


class CLI:
    """命令行界面"""

    def __init__(self):
        """初始化 CLI"""
        # 加载配置
        self.config = load_config()

        # 数据库路径
        db_path = str(Path("data") / "tickets.db")

        # 初始化单例服务
        self.llm_service = LLMService(self.config)
        self.embedding_service = EmbeddingService(self.config)

        # 初始化对话管理器
        self.dialogue_manager = DialogueManager(
            db_path, self.llm_service, self.embedding_service
        )

        # 格式化器
        self.formatter = TextFormatter()

        # 当前会话 ID
        self.session_id: Optional[str] = None

    def run(self):
        """运行 CLI 主循环"""
        # 显示欢迎信息
        print(self.formatter.format_welcome())

        try:
            while True:
                # 读取用户输入
                try:
                    user_input = input("> ").strip()
                except EOFError:
                    # Ctrl+D
                    print("\n\n再见！")
                    break

                if not user_input:
                    continue

                # 处理命令
                if user_input.startswith("/"):
                    if self._handle_command(user_input):
                        break  # /exit 命令返回 True
                    continue

                # 处理诊断消息
                self._handle_diagnosis_message(user_input)

        except KeyboardInterrupt:
            # Ctrl+C
            print("\n\n再见！")

    def _handle_command(self, command: str) -> bool:
        """
        处理命令

        Args:
            command: 命令字符串

        Returns:
            是否退出程序
        """
        command = command.lower().strip()

        if command == "/help":
            print(self.formatter.format_help())
            return False

        elif command == "/status":
            if not self.session_id:
                print(self.formatter.format_error("还没有开始诊断会话"))
            else:
                session_info = self.dialogue_manager.get_session(self.session_id)
                if session_info:
                    print(self.formatter.format_status(session_info))
                else:
                    print(self.formatter.format_error("会话不存在"))
            return False

        elif command == "/history":
            if not self.session_id:
                print(self.formatter.format_error("还没有开始诊断会话"))
            else:
                self._show_history()
            return False

        elif command == "/reset":
            self.session_id = None
            print(self.formatter.format_system_message("已重置会话，请重新描述问题"))
            return False

        elif command == "/exit":
            print("\n再见！\n")
            return True

        else:
            print(self.formatter.format_error(f"未知命令: {command}，输入 /help 查看可用命令"))
            return False

    def _handle_diagnosis_message(self, user_message: str):
        """
        处理诊断消息

        Args:
            user_message: 用户消息
        """
        try:
            if not self.session_id:
                # 开始新会话
                response = self.dialogue_manager.start_conversation(user_message)
                self.session_id = response.get("session_id")
            else:
                # 继续对话
                response = self.dialogue_manager.continue_conversation(
                    self.session_id, user_message
                )

            # 格式化并输出响应
            self._format_and_print_response(response)

        except Exception as e:
            print(self.formatter.format_error(f"处理失败: {str(e)}"))

    def _format_and_print_response(self, response: dict):
        """
        格式化并打印响应

        Args:
            response: 系统响应
        """
        action = response.get("action", "")

        if action == "recommend_step":
            print(self.formatter.format_step_recommendation(response))
        elif action == "confirm_root_cause":
            print(self.formatter.format_root_cause_confirmation(response))
        else:
            # 默认：直接显示 message
            message = response.get("message", "")
            if message:
                print(f"\n{message}\n")

    def _show_history(self):
        """显示对话历史（最近5轮）"""
        session = self.dialogue_manager.session_service.get_session(self.session_id)
        if not session or not session.dialogue_history:
            print(self.formatter.format_system_message("暂无对话历史"))
            return

        print("\n--- 对话历史（最近5轮）---\n")

        # 只显示最近5轮对话
        recent_history = session.dialogue_history[-10:]  # 5轮 = 10条消息（用户+助手）

        for msg in recent_history:
            role_label = "用户" if msg.role == "user" else "系统"
            print(f"[{role_label}] {msg.content}\n")


def main():
    """主入口"""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
