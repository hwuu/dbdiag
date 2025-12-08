"""CLI 主程序

使用 Rich 库美化 CLI 输出。

运行方式：
    python -m dbdiag cli       # 图谱增强推理方法（默认）
    python -m dbdiag cli --rar # 检索增强推理方法（实验性）
    python -m dbdiag cli --hyb # 混合增强推理方法（实验性）
"""
from abc import ABC, abstractmethod
from typing import Optional

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
import rich.markdown

from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.config import load_config
from dbdiag.cli.rendering import DiagnosisRenderer
from dbdiag.dao.base import get_default_db_path


# Monkey patch: 修复 Rich Markdown 标题默认居中的问题
def _left_aligned_heading_console(self, console, options):
    """左对齐的标题渲染"""
    self.text.justify = "left"
    yield self.text


rich.markdown.Heading.__rich_console__ = _left_aligned_heading_console


class CLI(ABC):
    """CLI 抽象基类

    所有 CLI 实现（GARCLI、RARCLI、HybCLI）的基类。
    不能直接实例化，子类必须实现抽象方法。
    """

    def __init__(self):
        """初始化基础组件"""
        self.console = Console()
        self.config = load_config()
        self.db_path = get_default_db_path()

        # 服务（子类可能会用到）
        self.llm_service = LLMService(self.config)
        self.embedding_service = EmbeddingService(self.config)

        # 状态
        self.session_id: Optional[str] = None
        self.round_count: int = 0

    def _print_indented(self, content, num_spaces: int = 2) -> None:
        """打印带缩进的 Rich 对象"""
        from rich.padding import Padding
        self.console.print(Padding(content, (0, 0, 0, num_spaces)))

    def run(self):
        """运行 CLI 主循环"""
        # 欢迎信息
        self.console.print()
        self._show_welcome()
        self.console.print(Text(f"可用命令: {self._get_available_commands()}", style="dim"))
        self.console.print()
        self.console.print(Text("请描述您遇到的数据库问题开始诊断。", style="bold yellow"))
        self.console.print()

        try:
            while True:
                try:
                    user_input = self.console.input(self._get_prompt()).strip()
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

    def _handle_command(self, command: str) -> bool:
        """处理通用命令，返回 True 表示退出

        子类可以覆盖此方法添加额外命令。
        """
        command = command.lower().strip()

        if command == "/help":
            self._show_help()
            return False

        elif command == "/status":
            self._show_status()
            return False

        elif command == "/reset":
            self._reset_session()
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

    # ===== 子类必须实现的抽象方法 =====

    @abstractmethod
    def _show_welcome(self) -> None:
        """显示欢迎信息（LOGO 等）"""
        pass

    @abstractmethod
    def _get_prompt(self) -> str:
        """获取输入提示符"""
        pass

    @abstractmethod
    def _get_available_commands(self) -> str:
        """获取可用命令列表字符串"""
        pass

    @abstractmethod
    def _show_help(self) -> None:
        """显示帮助信息"""
        pass

    @abstractmethod
    def _show_status(self) -> None:
        """显示当前状态"""
        pass

    @abstractmethod
    def _reset_session(self) -> None:
        """重置会话状态"""
        pass

    @abstractmethod
    def _handle_diagnosis(self, user_message: str) -> bool:
        """处理诊断消息，返回 True 表示诊断完成"""
        pass


class GARCLI(CLI):
    """GAR CLI（图谱增强推理）

    使用知识图谱进行诊断推理。
    """

    def __init__(self):
        """初始化"""
        super().__init__()

        from dbdiag.core.gar.dialogue_manager import GARDialogueManager
        from dbdiag.dao import RootCauseDAO

        # 渲染器
        self.renderer = DiagnosisRenderer(self.console)

        # 对话管理器
        self.dialogue_manager = GARDialogueManager(
            self.db_path, self.llm_service, self.embedding_service,
            progress_callback=self._print_progress,
            recommender_config=self.config.recommender,
        )

        # DAO
        self._root_cause_dao = RootCauseDAO(self.db_path)

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

    # ===== 实现抽象方法 =====

    def _show_welcome(self) -> None:
        """显示欢迎信息"""
        self.console.print(Text(self.renderer.get_logo("gar"), style="bold blue"))
        self.console.print(Text("图谱增强推理方法", style="bold blue"))

    def _get_prompt(self) -> str:
        """获取输入提示符"""
        return "[bold blue]> [/bold blue]"

    def _get_available_commands(self) -> str:
        """获取可用命令列表"""
        return "/help /status /reset /exit"

    def _show_help(self) -> None:
        """显示帮助信息"""
        self.console.print(self.renderer.render_help("gar"))

    def _show_status(self) -> None:
        """显示当前状态"""
        if not self.session_id:
            self.console.print(Text("还没有开始诊断会话", style="yellow"))
        else:
            self._update_stats_from_session()
            self.console.print(self._render_footer())

    def _reset_session(self) -> None:
        """重置会话状态"""
        self.session_id = None
        self.round_count = 0
        self.stats = {"recommended": 0, "confirmed": 0, "denied": 0, "top_hypotheses": []}
        self._recommended_phenomenon_ids = set()

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

    # ===== GAR 特有方法 =====

    def _render_footer(self) -> Group:
        """渲染底部状态栏（无边框）"""
        return self.renderer.render_status_bar(
            round_count=self.round_count,
            recommended=self.stats["recommended"],
            confirmed=self.stats["confirmed"],
            denied=self.stats["denied"],
            hypotheses=self.stats["top_hypotheses"],
        )

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

        # 复用 DiagnosisRenderer 渲染
        rendered = self.renderer.render_phenomenon_recommendation(phenomena_with_reasons)
        self._print_indented(rendered)
        self._print_indented(Text(""))

    def _render_root_cause_confirmation(self, response: dict):
        """渲染根因确认"""
        root_cause = response.get("root_cause", "未知")
        diagnosis_summary = response.get("diagnosis_summary", "")
        citations = response.get("citations", [])

        panel = self.renderer.render_diagnosis_result(
            root_cause=root_cause,
            diagnosis_summary=diagnosis_summary,
            citations=citations,
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

        # 更新 top 假设
        self.stats["top_hypotheses"] = []
        if session.active_hypotheses:
            top_k = self.config.recommender.hypothesis_top_k
            for hyp in session.active_hypotheses[:top_k]:
                desc = self._get_root_cause_description(hyp.root_cause_id)
                self.stats["top_hypotheses"].append((hyp.confidence, desc))


class HybCLI(GARCLI):
    """Hyb CLI（混合增强推理，实验性）

    继承 GARCLI，启用混合增强模式：
    - 初始检索增强：搜索 ticket description
    - LLM 增强推荐解释
    """

    def __init__(self):
        """初始化"""
        # 调用基类初始化（会创建服务和 dialogue_manager）
        super().__init__()

        # 重新创建 dialogue_manager，启用 hybrid_mode
        from dbdiag.core.gar.dialogue_manager import GARDialogueManager
        self.dialogue_manager = GARDialogueManager(
            self.db_path, self.llm_service, self.embedding_service,
            progress_callback=self._print_progress,
            recommender_config=self.config.recommender,
            hybrid_mode=True,  # 启用混合模式
        )

    def _show_welcome(self) -> None:
        """显示欢迎信息"""
        self.console.print(Text(self.renderer.get_logo("hyb"), style="bold green"))
        self.console.print(Text("混合增强推理方法（实验性）", style="bold green"))

    def _get_prompt(self) -> str:
        """获取输入提示符"""
        return "[bold green]> [/bold green]"


class RARCLI(CLI):
    """RAR CLI（检索增强推理，实验性）

    使用 RAG + LLM 端到端推理。
    """

    def __init__(self):
        """初始化"""
        super().__init__()

        from dbdiag.core.rar.dialogue_manager import RARDialogueManager

        # 渲染器
        self.renderer = DiagnosisRenderer(self.console)

        # RAR 对话管理器
        self.dialogue_manager = RARDialogueManager(
            self.db_path, self.llm_service, self.embedding_service
        )

        # 统计（与 GAR 保持一致）
        self.stats = {
            "recommended": 0,  # 推荐的现象数
            "confirmed": 0,    # 确认的现象数
            "denied": 0,       # 否认的现象数
            "confidence": 0.0, # 当前置信度
        }

    # ===== 实现抽象方法 =====

    def _show_welcome(self) -> None:
        """显示欢迎信息"""
        self.console.print(Text(self.renderer.get_logo("rar"), style="bold magenta"))
        self.console.print(Text("检索增强推理方法（实验性）", style="bold magenta"))

    def _get_prompt(self) -> str:
        """获取输入提示符"""
        return "[bold magenta]> [/bold magenta]"

    def _get_available_commands(self) -> str:
        """获取可用命令列表"""
        return "/help /reset /exit"

    def _show_help(self) -> None:
        """显示帮助信息"""
        self.console.print(self.renderer.render_help("rar"))

    def _show_status(self) -> None:
        """显示当前状态"""
        self.console.print(self._render_footer())

    def _reset_session(self) -> None:
        """重置会话状态"""
        self.session_id = None
        self.round_count = 0
        self.stats = {"recommended": 0, "confirmed": 0, "denied": 0, "confidence": 0.0}
        self.dialogue_manager.state = None

    def _handle_diagnosis(self, user_message: str) -> bool:
        """处理诊断消息，返回 True 表示诊断完成"""
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

    # ===== RAR 特有方法 =====

    def _render_footer(self) -> Group:
        """渲染底部状态栏（复用 DiagnosisRenderer）"""
        # RAR 只有一个置信度，包装成假设格式
        hypotheses = [(self.stats["confidence"], "当前置信度")]
        return self.renderer.render_status_bar(
            round_count=self.round_count,
            recommended=self.stats["recommended"],
            confirmed=self.stats["confirmed"],
            denied=self.stats["denied"],
            hypotheses=hypotheses,
        )

    def _render_recommendation(self, response: dict):
        """渲染推荐响应（复用 DiagnosisRenderer）"""
        recommendations = response.get("recommendations", [])
        confidence = response.get("confidence", 0.0)

        # 更新统计
        self.stats["confidence"] = confidence
        self.stats["recommended"] += len(recommendations)

        # 先显示状态栏
        self._print_indented(self._render_footer())
        self.console.print()

        # 复用 DiagnosisRenderer 渲染
        rendered = self.renderer.render_rar_recommendation(recommendations)
        self._print_indented(rendered)
        self._print_indented(Text(""))

    def _render_diagnosis(self, response: dict):
        """渲染诊断响应（复用 DiagnosisRenderer）"""
        root_cause = response.get("root_cause", "未知")
        confidence = response.get("confidence", 0.0)
        reasoning = response.get("reasoning", "")
        solution = response.get("solution", "")
        cited_tickets = response.get("cited_tickets", [])
        observed_phenomena = response.get("observed_phenomena", [])
        forced = response.get("forced", False)

        # 更新统计
        self.stats["confidence"] = confidence

        # 先显示状态栏
        self._print_indented(self._render_footer())

        # 复用 DiagnosisRenderer 渲染
        panel = self.renderer.render_diagnosis_result(
            root_cause=root_cause,
            citations=cited_tickets,
            observed_phenomena=observed_phenomena,
            reasoning=reasoning,
            solution=solution,
            forced=forced,
        )
        self._print_indented(Text(""))
        self._print_indented(panel)

    def _parse_feedback(self, message: str):
        """解析用户反馈并更新状态"""
        import re
        # 解析 "1确认 2否定" 格式
        confirm_matches = re.findall(r"(\d+)\s*确认", message)
        deny_matches = re.findall(r"(\d+)\s*否定", message)

        # 更新统计
        self.stats["confirmed"] += len(confirm_matches)
        self.stats["denied"] += len(deny_matches)

        # 更新 dialogue_manager 状态
        for _ in confirm_matches:
            self.dialogue_manager.confirm_observation(message)
        for _ in deny_matches:
            self.dialogue_manager.deny_observation(message)


class GAR2CLI(CLI):
    """GAR2 CLI（图谱增强推理 v2，实验性）

    基于观察的诊断推理引擎。
    """

    def __init__(self):
        """初始化"""
        super().__init__()

        from dbdiag.core.gar2.dialogue_manager import GAR2DialogueManager
        from dbdiag.dao import RootCauseDAO

        # 渲染器
        self.renderer = DiagnosisRenderer(self.console)

        # GAR2 对话管理器
        self.dialogue_manager = GAR2DialogueManager(
            self.db_path, self.llm_service, self.embedding_service,
            progress_callback=self._print_progress,
        )

        # DAO
        self._root_cause_dao = RootCauseDAO(self.db_path)

        # 统计
        self.stats = {
            "observations": 0,  # 观察数
            "matched": 0,       # 匹配的观察数
            "blocked": 0,       # 阻塞的现象数
        }

    def _print_progress(self, message: str):
        """打印进度信息"""
        self._print_indented(Text(f"→ {message}", style="dim"))

    # ===== 实现抽象方法 =====

    def _show_welcome(self) -> None:
        """显示欢迎信息"""
        self.console.print(Text(self.renderer.get_logo("gar2"), style="bold cyan"))
        self.console.print(Text("图谱增强推理 v2（实验性）", style="bold cyan"))

    def _get_prompt(self) -> str:
        """获取输入提示符"""
        return "[bold cyan]> [/bold cyan]"

    def _get_available_commands(self) -> str:
        """获取可用命令列表"""
        return "/help /status /reset /exit"

    def _show_help(self) -> None:
        """显示帮助信息"""
        self.console.print(self.renderer.render_help("gar2"))

    def _show_status(self) -> None:
        """显示当前状态"""
        if not self.session_id:
            self.console.print(Text("还没有开始诊断会话", style="yellow"))
        else:
            self._update_stats_from_session()
            self.console.print(self._render_footer())

    def _reset_session(self) -> None:
        """重置会话状态"""
        self.session_id = None
        self.round_count = 0
        self.stats = {"observations": 0, "matched": 0, "blocked": 0}
        self.dialogue_manager.reset()

    def _handle_diagnosis(self, user_message: str) -> bool:
        """处理诊断消息，返回 True 表示诊断完成"""
        try:
            self.console.print()
            self.console.print(Text.from_markup(f"[bold]• 第 {self.round_count + 1} 轮[/bold]"))
            self.round_count += 1

            if not self.session_id:
                self._print_indented(Text("正在分析问题...", style="dim"))
                response = self.dialogue_manager.start_conversation(user_message)
                session = response.get("session")
                if session:
                    self.session_id = session.session_id
            else:
                self._print_indented(Text("正在处理反馈...", style="dim"))
                response = self.dialogue_manager.continue_conversation(user_message)

            self.console.print()

            # 更新统计并显示状态
            self._update_stats_from_session()
            self._print_indented(self._render_footer())
            self.console.print()

            # 渲染响应
            action = response.get("action", "")
            if action == "recommend":
                self._render_recommendation(response)
                return False
            elif action == "diagnose":
                self._render_diagnosis(response)
                return True
            elif action == "ask_more_info":
                self._print_indented(Text(response.get("message", "请提供更多信息"), style="yellow"))
                return False
            else:
                message = response.get("message", "")
                if message:
                    self._print_indented(Text(message))
                return False

        except Exception as e:
            self._print_indented(Text(f"处理失败: {str(e)}", style="red"))
            import traceback
            traceback.print_exc()
            return False

    # ===== GAR2 特有方法 =====

    def _get_root_cause_description(self, root_cause_id: str) -> str:
        """获取根因描述"""
        return self._root_cause_dao.get_description(root_cause_id)

    def _render_footer(self) -> Group:
        """渲染底部状态栏"""
        session = self.dialogue_manager.get_session()
        hypotheses = []
        if session and session.hypotheses:
            for hyp in session.hypotheses[:3]:
                desc = self._get_root_cause_description(hyp.root_cause_id)
                hypotheses.append((hyp.confidence, desc))

        return self.renderer.render_status_bar(
            round_count=self.round_count,
            recommended=self.stats["observations"],
            confirmed=self.stats["matched"],
            denied=self.stats["blocked"],
            hypotheses=hypotheses,
        )

    def _render_recommendation(self, response: dict):
        """渲染推荐响应（复用 DiagnosisRenderer）"""
        recommendations = response.get("recommendations", [])

        if not recommendations:
            self._print_indented(Text("没有更多现象可推荐", style="yellow"))
            return

        # 转换为 render_phenomenon_recommendation 所需格式
        from dbdiag.models.common import Phenomenon
        phenomena_with_reasons = []
        for rec in recommendations:
            phenomenon = Phenomenon(
                phenomenon_id=rec.get("phenomenon_id", ""),
                description=rec.get("description", ""),
                observation_method=rec.get("observation_method", ""),
                source_anomaly_ids=[],  # 渲染时不需要
                cluster_size=0,  # 渲染时不需要
            )
            phenomena_with_reasons.append({
                "phenomenon": phenomenon,
                "reason": rec.get("reason", ""),
            })

        # 复用 DiagnosisRenderer 渲染
        rendered = self.renderer.render_phenomenon_recommendation(phenomena_with_reasons)
        self._print_indented(rendered)
        self._print_indented(Text(""))

    def _render_diagnosis(self, response: dict):
        """渲染诊断结果"""
        root_cause = response.get("root_cause", "未知")
        confidence = response.get("confidence", 0.0)
        solution = response.get("solution", "")
        observed_phenomena = response.get("observed_phenomena", [])

        panel = self.renderer.render_diagnosis_result(
            root_cause=root_cause,
            observed_phenomena=observed_phenomena,
            solution=solution,
        )
        self._print_indented(Text(""))
        self._print_indented(panel)

    def _update_stats_from_session(self):
        """从 session 更新统计信息"""
        session = self.dialogue_manager.get_session()
        if not session:
            return

        self.stats["observations"] = len(session.symptom.observations)
        self.stats["matched"] = len(session.symptom.get_matched_phenomenon_ids())
        self.stats["blocked"] = len(session.symptom.blocked_phenomenon_ids)


def main(use_rar: bool = False, use_hyb: bool = False, use_gar2: bool = False, db_path: str = None):
    """入口

    Args:
        use_rar: 是否使用 RAR 方法
        use_hyb: 是否使用混合增强方法
        use_gar2: 是否使用 GAR2 方法
        db_path: 数据库路径，如果指定则覆盖默认路径
    """
    import os

    # 如果指定了 db_path，设置环境变量
    if db_path:
        os.environ["DB_PATH"] = db_path

    if use_gar2:
        cli = GAR2CLI()
    elif use_hyb:
        cli = HybCLI()
    elif use_rar:
        cli = RARCLI()
    else:
        cli = GARCLI()
    cli.run()


if __name__ == "__main__":
    main()
