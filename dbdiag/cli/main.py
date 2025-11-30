"""CLI 主程序

使用 Rich 库美化 CLI 输出。

运行方式：
    python -m dbdiag cli       # 图谱增强推理方法（默认）
    python -m dbdiag cli --rar # 检索增强推理方法（实验性）
"""
from pathlib import Path
from typing import Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
import rich.markdown

from dbdiag.core.gar.dialogue_manager import GARDialogueManager
from dbdiag.dao import RootCauseDAO
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.config import load_config


# Monkey patch: 修复 Rich Markdown 标题默认居中的问题
def _left_aligned_heading_console(self, console, options):
    """左对齐的标题渲染"""
    self.text.justify = "left"
    yield self.text


rich.markdown.Heading.__rich_console__ = _left_aligned_heading_console


class RichCLI:
    """Rich CLI"""

    LOGO = """
██████╗ ██████╗ ██████╗ ██╗ █████╗  ██████╗        ██████╗
██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗██╔════╝       ██╔════╝
██║  ██║██████╔╝██║  ██║██║███████║██║  ███╗█████╗██║  ███╗
██║  ██║██╔══██╗██║  ██║██║██╔══██║██║   ██║╚════╝██║   ██║
██████╔╝██████╔╝██████╔╝██║██║  ██║╚██████╔╝      ╚██████╔╝
╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝        ╚═════╝
"""

    def __init__(self):
        """初始化"""
        self.console = Console()
        self.config = load_config()
        self.db_path = str(Path("data") / "tickets.db")

        # 服务
        self.llm_service = LLMService(self.config)
        self.embedding_service = EmbeddingService(self.config)

        # 对话管理器
        self.dialogue_manager = GARDialogueManager(
            self.db_path, self.llm_service, self.embedding_service,
            progress_callback=self._print_progress,
            recommender_config=self.config.recommender,
        )

        # DAO
        self._root_cause_dao = RootCauseDAO(self.db_path)

        # 状态
        self.session_id: Optional[str] = None
        self.round_count: int = 0

        # 进度追踪
        self._hypothesis_count = 0
        self._hypothesis_total = 0

        # 统计
        self.stats = {
            "recommended": 0,  # 推荐的现象数（去重）
            "confirmed": 0,    # 确认的现象数
            "denied": 0,       # 否认的现象数
            "top_hypotheses": [],  # Top 3 假设 [(confidence, description), ...]
        }
        self._recommended_phenomenon_ids: set = set()  # 已推荐的现象ID（用于去重）

    def _print_progress(self, message: str):
        """打印进度信息（合并评估假设，带缩进）"""
        import re
        # 检测评估假设消息
        match = re.match(r"评估假设 \((\d+)/(\d+)\)", message)
        if match:
            current, total = int(match.group(1)), int(match.group(2))
            self._hypothesis_total = total
            # 只在最后一个时显示
            if current == total:
                self._print_indented(Text(f"→ 评估假设 ({total}/{total}) 完成", style="dim"))
            return

        # 其他消息正常显示（带缩进）
        self._print_indented(Text(f"→ {message}", style="dim"))

    def _get_root_cause_description(self, root_cause_id: str) -> str:
        """获取根因描述"""
        return self._root_cause_dao.get_description(root_cause_id)

    def _render_footer(self) -> Group:
        """渲染底部状态栏（无边框）"""
        # 第一行：轮次、推荐、确认、否认（横向）
        stats_text = Text()
        stats_text.append("轮次 ", style="dim")
        stats_text.append(str(self.round_count), style="bold")
        stats_text.append("  │  ", style="dim")
        stats_text.append("推荐 ", style="dim")
        stats_text.append(str(self.stats["recommended"]), style="bold")
        stats_text.append("  │  ", style="dim")
        stats_text.append("确认 ", style="dim")
        stats_text.append(str(self.stats["confirmed"]), style="bold green")
        stats_text.append("  │  ", style="dim")
        stats_text.append("否认 ", style="dim")
        stats_text.append(str(self.stats["denied"]), style="bold red")

        content_parts = [stats_text]

        # Top 3 假设
        hypotheses = self.stats["top_hypotheses"]
        if hypotheses:
            content_parts.append(Text(""))  # 空行
            for i, (conf, desc) in enumerate(hypotheses, 1):
                bar_filled = int(conf * 10)
                bar_empty = 10 - bar_filled

                hyp_line = Text()
                hyp_line.append(f"{i}. ", style="dim")
                hyp_line.append("█" * bar_filled, style="green")
                hyp_line.append("░" * bar_empty, style="dim")
                hyp_line.append(f" {conf:.0%} ", style="bold")

                # 截断描述
                if len(desc) > 35:
                    desc = desc[:35] + "..."
                hyp_line.append(desc)
                content_parts.append(hyp_line)
        else:
            content_parts.append(Text("暂无假设", style="dim"))

        return Group(*content_parts)

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
            self._print_indented(Text(response.get('message', '')))
            return

        # 更新统计（去重）
        for item in phenomena_with_reasons:
            phenomenon = item["phenomenon"]
            if phenomenon.phenomenon_id not in self._recommended_phenomenon_ids:
                self._recommended_phenomenon_ids.add(phenomenon.phenomenon_id)
                self.stats["recommended"] += 1

        # 标题
        self._print_indented(Text(f"建议确认以下 {len(phenomena_with_reasons)} 个现象：", style="bold yellow"))
        self._print_indented(Text(""))

        # 渲染每个现象
        for i, item in enumerate(phenomena_with_reasons, 1):
            phenomenon = item["phenomenon"]
            reason = item.get("reason", "")

            # 标题行
            title = Text()
            title.append(f"[{i}] ", style="bold yellow")
            title.append(phenomenon.phenomenon_id, style="bold cyan")
            self._print_indented(title)

            # 描述
            self._print_indented(Text(phenomenon.description), num_spaces=6)

            # 观察方法
            if phenomenon.observation_method:
                self._print_indented(Text("观察方法:", style="dim"), num_spaces=6)
                self._print_indented(Text(phenomenon.observation_method.strip()), num_spaces=6)

            # 推荐原因
            if reason:
                self._print_indented(Text(f"推荐原因: {reason}", style="italic dim"), num_spaces=6)

            self._print_indented(Text(""))  # 空行

        self._print_indented(Text("请输入检查结果（如：1确认 2否定 3确认）。", style="bold yellow"))
        self._print_indented(Text(""))

    def _render_root_cause_confirmation(self, response: dict):
        """渲染根因确认"""
        root_cause = response.get("root_cause", "未知")
        confidence = response.get("confidence", 0.0)
        diagnosis_summary = response.get("diagnosis_summary", "")
        citations = response.get("citations", [])

        # 构建 Panel 内容
        content_parts = []

        # 根因和置信度
        info = Text()
        info.append("根因: ", style="bold")
        info.append(f"{root_cause}\n", style="green bold")
        content_parts.append(info)

        # 诊断报告（Markdown 渲染）
        if diagnosis_summary:
            md = Markdown(diagnosis_summary, justify="left")
            content_parts.append(md)
            content_parts.append(Text(""))

        # 引用工单
        if citations:
            content_parts.append(Text("引用工单", style="bold"))
            for i, citation in enumerate(citations, 1):
                content_parts.append(Text(""))
                cite_text = Text()
                cite_text.append(f"[{i}] ", style="dim")
                cite_text.append(f"{citation['ticket_id']}", style="bold cyan")
                cite_text.append(f": {citation['description']}")
                content_parts.append(cite_text)

        # 使用 Panel 包装，最大宽度 100
        panel = Panel(
            Group(*content_parts),
            title="✓ 根因已定位",
            title_align="left",
            border_style="green",
            width=min(100, self.console.width),
            padding=(1, 2),
        )
        self._print_indented(Text(""))
        self._print_indented(panel)

    def _update_stats_from_session(self):
        """从 session 更新统计信息"""
        if not self.session_id:
            return

        session = self.dialogue_manager.session_service.get_session(self.session_id)
        if not session:
            return

        # 更新确认/否认数
        self.stats["confirmed"] = len(session.confirmed_phenomena)
        self.stats["denied"] = len(session.denied_phenomena)

        # 更新 top 3 假设
        self.stats["top_hypotheses"] = []
        if session.active_hypotheses:
            for hyp in session.active_hypotheses[:3]:
                desc = self._get_root_cause_description(hyp.root_cause_id)
                self.stats["top_hypotheses"].append((hyp.confidence, desc))

    def _handle_command(self, command: str) -> bool:
        """处理命令，返回 True 表示退出"""
        command = command.lower().strip()

        if command == "/help":
            help_text = """
**可用命令：**
- `/help` - 显示此帮助
- `/status` - 查看当前诊断状态
- `/history` - 查看对话历史
- `/reset` - 重新开始诊断
- `/exit` - 退出程序

直接输入诊断结果或观察到的现象即可继续诊断。
            """
            self.console.print(Panel(Markdown(help_text.strip()), title="帮助", title_align="left", border_style="blue"))
            return False

        elif command == "/status":
            if not self.session_id:
                self.console.print(Text("还没有开始诊断会话", style="yellow"))
            else:
                self._update_stats_from_session()
                self.console.print(self._render_footer())
            return False

        elif command == "/reset":
            self.session_id = None
            self.round_count = 0
            self.stats = {"recommended": 0, "confirmed": 0, "denied": 0, "top_hypotheses": []}
            self._recommended_phenomenon_ids = set()
            self.console.print(Text("已重置会话，请重新描述问题", style="green"))
            return False

        elif command == "/exit":
            self.console.print(Text("再见！", style="blue"))
            return True

        else:
            text = Text()
            text.append(f"未知命令: {command}", style="red")
            text.append("，输入 /help 查看可用命令")
            self.console.print(text)
            return False

    def _print_indented(self, content, num_spaces: int = 2) -> None:
        """打印带缩进的 Rich 对象"""
        from rich.padding import Padding
        self.console.print(Padding(content, (0, 0, 0, num_spaces)))

    def _handle_diagnosis(self, user_message: str) -> bool:
        """处理诊断消息，返回 True 表示根因已定位"""
        try:
            self.console.print()
            self.console.print(Text.from_markup(f"[bold]• 第 {self.round_count + 1} 轮[/bold]"))
            self.round_count += 1

            if not self.session_id:
                self._print_indented(Text("正在分析问题...", style="dim"))
                response = self.dialogue_manager.start_conversation(user_message)
                self.session_id = response.get("session_id")
            else:
                self._print_indented(Text("正在处理反馈...", style="dim"))
                response = self.dialogue_manager.continue_conversation(
                    self.session_id, user_message
                )

            self.console.print()

            # 先更新统计并显示状态
            self._update_stats_from_session()
            self._print_indented(self._render_footer())
            self.console.print()

            # 再渲染响应（现象推荐等）
            action = response.get("action", "")
            if action == "recommend_phenomenon":
                self._render_phenomenon_recommendation(response)
            elif action == "confirm_root_cause":
                self._render_root_cause_confirmation(response)
                return True
            else:
                message = response.get("message", "")
                if message:
                    self._print_indented(Text(message))

            return False

        except Exception as e:
            self._print_indented(Text(f"处理失败: {str(e)}", style="red"))
            return False

    def run(self):
        """运行 CLI 主循环"""
        # 欢迎信息（无边框）
        self.console.print()
        self.console.print(Text(self.LOGO.strip(), style="bold blue"))
        self.console.print(Text("可用命令: /help /status /reset /exit", style="dim"))
        self.console.print()
        self.console.print(Text("请描述您遇到的数据库问题开始诊断。", style="bold yellow"))
        self.console.print()

        try:
            while True:
                try:
                    user_input = self.console.input("[bold]> [/bold]").strip()
                except EOFError:
                    self.console.print(Text("\n再见！\n", style="blue"))
                    break

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    if self._handle_command(user_input):
                        break
                    continue

                if self._handle_diagnosis(user_input):
                    self.console.print(Text("\n再见！\n", style="blue"))
                    break

        except KeyboardInterrupt:
            self.console.print(Text("\n再见！\n", style="blue"))


class RARCLI:
    """RAR CLI (实验性)

    使用检索增强推理方法的简化 CLI。
    """

    LOGO = """
██████╗ ██████╗ ██████╗ ██╗ █████╗  ██████╗       ██████╗
██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗██╔════╝       ██╔══██╗
██║  ██║██████╔╝██║  ██║██║███████║██║  ███╗█████╗██████╔╝
██║  ██║██╔══██╗██║  ██║██║██╔══██║██║   ██║╚════╝██╔══██╗
██████╔╝██████╔╝██████╔╝██║██║  ██║╚██████╔╝      ██║  ██║
╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝       ╚═╝  ╚═╝
"""

    def __init__(self):
        """初始化"""
        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        self.console = Console()
        self.config = load_config()
        self.db_path = str(Path("data") / "tickets.db")

        # 服务
        self.llm_service = LLMService(self.config)
        self.embedding_service = EmbeddingService(self.config)

        # RAR 对话管理器
        self.dialogue_manager = RARDialogueManager(
            self.db_path, self.llm_service, self.embedding_service
        )

        # 状态
        self.session_id: Optional[str] = None
        self.round_count: int = 0

    def _print_indented(self, content, num_spaces: int = 2) -> None:
        """打印带缩进的 Rich 对象"""
        from rich.padding import Padding
        self.console.print(Padding(content, (0, 0, 0, num_spaces)))

    def _render_recommendation(self, response: dict):
        """渲染推荐响应"""
        recommendations = response.get("recommendations", [])
        reasoning = response.get("reasoning", "")
        confidence = response.get("confidence", 0.0)

        # 置信度
        self._print_indented(Text(f"置信度: {confidence:.0%}", style="dim"))
        self.console.print()

        if reasoning:
            self._print_indented(Text(f"分析: {reasoning}", style="italic"))
            self.console.print()

        if recommendations:
            self._print_indented(Text(f"建议检查以下 {len(recommendations)} 个现象：", style="bold yellow"))
            self.console.print()

            for i, rec in enumerate(recommendations, 1):
                obs = rec.get("observation", "")
                method = rec.get("method", "")
                why = rec.get("why", "")
                related = rec.get("related_root_causes", [])

                # 标题
                title = Text()
                title.append(f"[{i}] ", style="bold yellow")
                title.append(obs, style="bold")
                self._print_indented(title)

                # 观察方法
                if method:
                    self._print_indented(Text(f"方法: {method}", style="dim"), num_spaces=6)

                # 原因
                if why:
                    self._print_indented(Text(f"原因: {why}", style="italic"), num_spaces=6)

                # 相关根因
                if related:
                    self._print_indented(Text(f"可能根因: {', '.join(related)}", style="cyan"), num_spaces=6)

                self.console.print()

            self._print_indented(Text("请检查上述现象并反馈结果（如：1确认 2否定）", style="bold yellow"))
        else:
            self._print_indented(Text("暂无推荐，请提供更多信息", style="yellow"))
        self._print_indented(Text(""))

    def _render_diagnosis(self, response: dict):
        """渲染诊断响应"""
        root_cause = response.get("root_cause", "未知")
        confidence = response.get("confidence", 0.0)
        reasoning = response.get("reasoning", "")
        solution = response.get("solution", "")
        cited_tickets = response.get("cited_tickets", [])
        forced = response.get("forced", False)

        content_parts = []

        # 根因
        info = Text()
        info.append("根因: ", style="bold")
        info.append(f"{root_cause}\n", style="green bold")
        content_parts.append(info)

        # 置信度
        conf_text = Text()
        conf_text.append("置信度: ", style="bold")
        conf_text.append(f"{confidence:.0%}", style="yellow" if confidence < 0.7 else "green")
        if forced:
            conf_text.append(" (强制诊断)", style="red")
        content_parts.append(conf_text)
        content_parts.append(Text(""))

        # 分析
        if reasoning:
            content_parts.append(Text("分析:", style="bold"))
            content_parts.append(Text(reasoning))
            content_parts.append(Text(""))

        # 解决方案
        if solution:
            content_parts.append(Text("解决方案:", style="bold"))
            content_parts.append(Markdown(solution))
            content_parts.append(Text(""))

        # 引用工单
        if cited_tickets:
            content_parts.append(Text(f"参考工单: {', '.join(cited_tickets)}", style="cyan"))

        panel = Panel(
            Group(*content_parts),
            title="✓ 诊断结论" if not forced else "⚠ 诊断结论（信息不足）",
            title_align="left",
            border_style="green" if not forced else "yellow",
            width=min(100, self.console.width),
            padding=(1, 2),
        )
        self._print_indented(panel)

    def _handle_message(self, user_message: str) -> bool:
        """处理用户消息，返回 True 表示诊断完成"""
        try:
            self.console.print()
            self.console.print(Text.from_markup(f"[bold]• 第 {self.round_count + 1} 轮[/bold]"))
            self.round_count += 1

            if not self.session_id:
                self._print_indented(Text("正在分析问题...", style="dim"))
                self.session_id = self.dialogue_manager.start_session(user_message)
                response = self.dialogue_manager.process_message(user_message)
            else:
                # 解析用户反馈
                self._parse_feedback(user_message)
                self._print_indented(Text("正在处理反馈...", style="dim"))
                response = self.dialogue_manager.process_message(user_message)

            self.console.print()

            action = response.get("action", "")
            if action == "recommend":
                self._render_recommendation(response)
                return False
            elif action == "diagnose":
                self._render_diagnosis(response)
                return True
            else:
                self._print_indented(Text(str(response)))
                return False

        except Exception as e:
            self._print_indented(Text(f"处理失败: {str(e)}", style="red"))
            import traceback
            traceback.print_exc()
            return False

    def _parse_feedback(self, message: str):
        """解析用户反馈并更新状态"""
        import re
        # 解析 "1确认 2否定" 格式
        confirm_pattern = re.findall(r"(\d+)\s*确认", message)
        deny_pattern = re.findall(r"(\d+)\s*否定", message)

        # 这里简化处理，假设用户直接描述观察结果
        # 实际应该根据推荐的索引来确认/否定
        if "确认" in message and "否定" not in message:
            # 全部确认
            self.dialogue_manager.confirm_observation(message)
        elif "否定" in message:
            self.dialogue_manager.deny_observation(message)

    def _handle_command(self, command: str) -> bool:
        """处理命令，返回 True 表示退出"""
        command = command.lower().strip()

        if command == "/help":
            help_text = """
**RAR 模式可用命令：**
- `/help` - 显示此帮助
- `/reset` - 重新开始诊断
- `/exit` - 退出程序

直接输入问题描述或检查结果即可继续诊断。
            """
            self.console.print(Panel(Markdown(help_text.strip()), title="帮助", title_align="left", border_style="blue"))
            return False

        elif command == "/reset":
            self.session_id = None
            self.round_count = 0
            self.dialogue_manager.state = None
            self.console.print(Text("已重置会话，请重新描述问题", style="green"))
            return False

        elif command == "/exit":
            self.console.print(Text("再见！", style="blue"))
            return True

        else:
            text = Text()
            text.append(f"未知命令: {command}", style="red")
            text.append("，输入 /help 查看可用命令")
            self.console.print(text)
            return False

    def run(self):
        """运行 CLI 主循环"""
        # 欢迎信息
        self.console.print()
        self.console.print(Text(self.LOGO.strip(), style="bold magenta"))
        self.console.print(Text("检索增强推理方法（实验性）", style="bold magenta"))
        self.console.print(Text("可用命令: /help /reset /exit", style="dim"))
        self.console.print()
        self.console.print(Text("请描述您遇到的数据库问题开始诊断。", style="bold yellow"))
        self.console.print()

        try:
            while True:
                try:
                    user_input = self.console.input("[bold magenta]> [/bold magenta]").strip()
                except EOFError:
                    self.console.print(Text("\n再见！\n", style="blue"))
                    break

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    if self._handle_command(user_input):
                        break
                    continue

                if self._handle_message(user_input):
                    self.console.print(Text("\n再见！\n", style="blue"))
                    break

        except KeyboardInterrupt:
            self.console.print(Text("\n再见！\n", style="blue"))


def main(use_rar: bool = False):
    """入口

    Args:
        use_rar: 是否使用 RAR 方法
    """
    if use_rar:
        cli = RARCLI()
    else:
        cli = RichCLI()
    cli.run()


if __name__ == "__main__":
    main()
