"""共享渲染逻辑

CLI 和 Web 服务共用的渲染逻辑。
"""
from typing import List, Tuple, Union

from rich.box import SIMPLE
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


class DiagnosisRenderer:
    """诊断结果渲染器

    提供 CLI 和 Web 服务共用的渲染方法。
    所有方法返回 Rich 可渲染对象，由调用方决定如何输出。
    """

    # LOGO 定义
    LOGO_GAR = """
██████╗ ██████╗ ██████╗ ██╗ █████╗  ██████╗        ██████╗
██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗██╔════╝       ██╔════╝
██║  ██║██████╔╝██║  ██║██║███████║██║  ███╗█████╗██║  ███╗
██║  ██║██╔══██╗██║  ██║██║██╔══██║██║   ██║╚════╝██║   ██║
██████╔╝██████╔╝██████╔╝██║██║  ██║╚██████╔╝      ╚██████╔╝
╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝        ╚═════╝
"""

    LOGO_HYB = """
██████╗ ██████╗ ██████╗ ██╗ █████╗  ██████╗       ██╗  ██╗
██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗██╔════╝       ██║  ██║
██║  ██║██████╔╝██║  ██║██║███████║██║  ███╗█████╗███████║
██║  ██║██╔══██╗██║  ██║██║██╔══██║██║   ██║╚════╝██╔══██║
██████╔╝██████╔╝██████╔╝██║██║  ██║╚██████╔╝      ██║  ██║
╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝       ╚═╝  ╚═╝
"""

    LOGO_RAR = """
██████╗ ██████╗ ██████╗ ██╗ █████╗  ██████╗       ██████╗
██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗██╔════╝       ██╔══██╗
██║  ██║██████╔╝██║  ██║██║███████║██║  ███╗█████╗██████╔╝
██║  ██║██╔══██╗██║  ██║██║██╔══██║██║   ██║╚════╝██╔══██╗
██████╔╝██████╔╝██████╔╝██║██║  ██║╚██████╔╝      ██║  ██║
╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝       ╚═╝  ╚═╝
"""

    def __init__(self, console: Console = None):
        """初始化渲染器

        Args:
            console: Rich Console 实例，用于获取终端宽度等信息
        """
        self.console = console or Console()

    def get_logo(self, mode: str = "gar") -> str:
        """获取 LOGO

        Args:
            mode: 诊断模式 (gar/hyb/rar)

        Returns:
            LOGO 字符串
        """
        logos = {
            "gar": self.LOGO_GAR,
            "hyb": self.LOGO_HYB,
            "rar": self.LOGO_RAR,
        }
        return logos.get(mode, self.LOGO_GAR).strip()

    def render_status_bar(
        self,
        round_count: int,
        recommended: int,
        confirmed: int,
        denied: int,
        hypotheses: List[Tuple[float, str]] = None,
    ) -> Group:
        """渲染状态栏

        Args:
            round_count: 轮次
            recommended: 推荐的现象数
            confirmed: 确认的现象数
            denied: 否认的现象数
            hypotheses: 假设列表 [(confidence, description), ...]

        Returns:
            Rich Group 对象
        """
        # 第一行：轮次、推荐、确认、否认（横向）
        stats_text = Text()
        stats_text.append("轮次 ", style="dim")
        stats_text.append(str(round_count), style="bold")
        stats_text.append("  │  ", style="dim")
        stats_text.append("推荐 ", style="dim")
        stats_text.append(str(recommended), style="bold")
        stats_text.append("  │  ", style="dim")
        stats_text.append("确认 ", style="dim")
        stats_text.append(str(confirmed), style="bold green")
        stats_text.append("  │  ", style="dim")
        stats_text.append("否认 ", style="dim")
        stats_text.append(str(denied), style="bold red")

        content_parts = [stats_text]

        # Top 3 假设
        if hypotheses:
            content_parts.append(Text(""))  # 空行
            for i, (conf, desc) in enumerate(hypotheses[:3], 1):
                bar = self._render_confidence_bar(i, conf, desc)
                content_parts.append(bar)
        else:
            content_parts.append(Text("暂无假设", style="dim"))

        return Group(*content_parts)

    def render_phenomenon_recommendation(
        self,
        phenomena_with_reasons: list,
    ) -> Group:
        """渲染现象推荐

        Args:
            phenomena_with_reasons: [{"phenomenon": Phenomenon, "reason": str}, ...]

        Returns:
            Rich Group 对象
        """
        if not phenomena_with_reasons:
            return Group(Text("暂无推荐", style="dim"))

        parts = []

        # 标题
        parts.append(Text(f"建议确认以下 {len(phenomena_with_reasons)} 个现象：", style="bold yellow"))
        parts.append(Text(""))

        # 渲染每个现象
        for i, item in enumerate(phenomena_with_reasons, 1):
            phenomenon = item["phenomenon"]
            reason = item.get("reason", "")

            # 标题行
            title = Text()
            title.append(f"[{i}] ", style="bold yellow")
            title.append(phenomenon.phenomenon_id, style="bold cyan")
            parts.append(title)

            # 描述
            parts.append(Text(f"    {phenomenon.description}"))

            # 观察方法
            if phenomenon.observation_method:
                parts.append(Text("    观察方法:", style="dim"))
                parts.append(Text(f"    {phenomenon.observation_method.strip()}"))

            # 推荐原因
            if reason:
                parts.append(Text(f"    推荐原因: {reason}", style="italic dim"))

            parts.append(Text(""))  # 空行

        parts.append(Text("请输入检查结果（如：1确认 2否定 3确认）。", style="bold yellow"))

        return Group(*parts)

    def render_diagnosis_result(
        self,
        root_cause: str,
        diagnosis_summary: str = "",
        citations: list = None,
        show_border: bool = True,
    ) -> Union[Panel, Group]:
        """渲染诊断结果

        Args:
            root_cause: 根因描述
            diagnosis_summary: 诊断总结（Markdown）
            citations: 引用工单 [{"ticket_id": str, "description": str}, ...]
            show_border: 是否显示边框（默认 True）

        Returns:
            Rich Panel 或 Group 对象
        """
        content_parts = []

        # 根因
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
            content_parts.append(Text(""))
            for i, citation in enumerate(citations, 1):
                cite_text = Text()
                cite_text.append(f"[{i}] ", style="dim")
                cite_text.append(f"{citation['ticket_id']}", style="bold cyan")
                cite_text.append(f": {citation['description']}")
                content_parts.append(cite_text)

        # 无边框模式：直接返回 Group
        if not show_border:
            # 添加标题
            title_text = Text("✓ 根因已定位", style="green bold")
            return Group(title_text, Text(""), *content_parts)

        # 使用 Panel 包装（有边框）
        panel = Panel(
            Group(*content_parts),
            title="✓ 根因已定位",
            title_align="left",
            border_style="green",
            width=min(100, self.console.width) if self.console else 100,
            padding=(1, 2),
        )

        return panel

    def render_help(self, mode: str = "gar") -> Panel:
        """渲染帮助信息

        Args:
            mode: 诊断模式

        Returns:
            Rich Panel 对象
        """
        if mode == "rar":
            help_text = """
**RAR 模式可用命令：**
- `/help` - 显示此帮助
- `/reset` - 重新开始诊断
- `/exit` - 退出程序

直接输入问题描述或检查结果即可继续诊断。
            """
        else:
            help_text = """
**可用命令：**
- `/help` - 显示此帮助
- `/status` - 查看当前诊断状态
- `/reset` - 重新开始诊断
- `/exit` - 退出程序

直接输入诊断结果或观察到的现象即可继续诊断。
            """

        return Panel(
            Markdown(help_text.strip()),
            title="帮助",
            title_align="left",
            border_style="blue",
        )

    def _render_confidence_bar(self, idx: int, conf: float, desc: str) -> Text:
        """渲染置信度条

        Args:
            idx: 序号
            conf: 置信度 (0-1)
            desc: 描述

        Returns:
            Rich Text 对象
        """
        bar_filled = int(conf * 10)
        bar_empty = 10 - bar_filled

        line = Text()
        line.append(f"{idx}. ", style="dim")
        line.append("█" * bar_filled, style="green")
        line.append("░" * bar_empty, style="dim")
        line.append(f" {conf:.0%} ", style="bold")

        # 截断描述
        if len(desc) > 35:
            desc = desc[:35] + "..."
        line.append(desc)

        return line
