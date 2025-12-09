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

    LOGO_GAR2 = """
██████╗ ██████╗ ██████╗ ██╗ █████╗  ██████╗        ██████╗ ██████╗
██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗██╔════╝       ██╔════╝ ╚════██╗
██║  ██║██████╔╝██║  ██║██║███████║██║  ███╗█████╗██║  ███╗ █████╔╝
██║  ██║██╔══██╗██║  ██║██║██╔══██║██║   ██║╚════╝██║   ██║██╔═══╝
██████╔╝██████╔╝██████╔╝██║██║  ██║╚██████╔╝      ╚██████╔╝███████╗
╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝        ╚═════╝ ╚══════╝
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
            mode: 诊断模式 (gar/hyb/rar/gar2)

        Returns:
            LOGO 字符串
        """
        logos = {
            "gar": self.LOGO_GAR,
            "hyb": self.LOGO_HYB,
            "rar": self.LOGO_RAR,
            "gar2": self.LOGO_GAR2,
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

        # Top 假设（由调用方决定数量）
        if hypotheses:
            content_parts.append(Text(""))  # 空行
            for i, (conf, desc) in enumerate(hypotheses, 1):
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
            phenomena_with_reasons: [{"phenomenon": Phenomenon, "reason": str, "score_details": dict}, ...]

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
            score_details = item.get("score_details", {})

            # 标题行
            title = Text()
            title.append(f"[{i}] ", style="bold yellow")
            title.append(phenomenon.phenomenon_id, style="bold yellow")

            # 得分详情
            if score_details:
                w = score_details.get("weights", {})
                v = score_details.get("values", {})
                score = score_details.get("score", 0)
                score_text = Text()
                score_text.append(" (", style="dim")
                score_text.append(f"{score:.3f}[score] = ", style="dim")
                score_text.append(f"{w.get('popularity', 0)} * {v.get('popularity', 0):.2f}[pop]", style="dim")
                score_text.append(f" + {w.get('specificity', 0)} * {v.get('specificity', 0):.2f}[spec]", style="dim")
                score_text.append(f" + {w.get('hypothesis_priority', 0)} * {v.get('hypothesis_priority', 0):.2f}[hyp]", style="dim")
                score_text.append(f" + {w.get('information_gain', 0)} * {v.get('information_gain', 0):.2f}[ig]", style="dim")
                score_text.append(")", style="dim")
                title.append(score_text)

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

        parts.append(Text("请输入检查结果（输入格式: 1确认 2否定 或 描述新观察）。", style="bold yellow"))

        return Group(*parts)

    def render_rar_recommendation(
        self,
        recommendations: list,
    ) -> Group:
        """渲染 RAR 推荐

        Args:
            recommendations: [{"observation": str, "method": str, "why": str, "related_root_causes": list}, ...]

        Returns:
            Rich Group 对象
        """
        if not recommendations:
            return Group(Text("暂无推荐，请提供更多信息", style="yellow"))

        parts = []

        # 标题
        parts.append(Text(f"建议确认以下 {len(recommendations)} 个现象：", style="bold yellow"))
        parts.append(Text(""))

        # 渲染每个推荐
        for i, rec in enumerate(recommendations, 1):
            obs = rec.get("observation", "")
            method = rec.get("method", "")
            why = rec.get("why", "")
            related = rec.get("related_root_causes", [])

            # 标题行
            title = Text()
            title.append(f"[{i}] ", style="bold yellow")
            title.append(obs, style="bold")
            parts.append(title)

            # 观察方法
            if method:
                parts.append(Text("    观察方法:", style="dim"))
                parts.append(Text(f"    {method.strip()}"))

            # 推荐原因
            if why:
                parts.append(Text(f"    推荐原因: {why}", style="italic dim"))

            # 相关根因
            if related:
                parts.append(Text(f"    可能根因: {', '.join(related)}", style="cyan"))

            parts.append(Text(""))  # 空行

        parts.append(Text("请输入检查结果（输入格式: 1确认 2否定 或 描述新观察）。", style="bold yellow"))

        return Group(*parts)

    def render_diagnosis_result(
        self,
        root_cause: str,
        diagnosis_summary: str = "",
        citations: list = None,
        show_border: bool = True,
        observed_phenomena: list = None,
        reasoning: str = "",
        solution: str = "",
        forced: bool = False,
        unconfirmed_phenomena: list = None,
    ) -> Union[Panel, Group]:
        """渲染诊断结果

        Args:
            root_cause: 根因描述
            diagnosis_summary: 诊断总结（Markdown，GAR 使用）
            citations: 引用工单 [{"ticket_id": str, "description": str}, ...]
            show_border: 是否显示边框（默认 True）
            observed_phenomena: 观察到的现象列表（RAR 使用）
            reasoning: 推理链路（RAR 使用）
            solution: 恢复措施（RAR 使用）
            forced: 是否强制诊断（RAR 使用，信息不足时）
            unconfirmed_phenomena: 未确认的现象列表（GAR2 使用）

        Returns:
            Rich Panel 或 Group 对象
        """
        content_parts = []

        # 根因
        info = Text()
        info.append("根因: ", style="bold")
        info.append(f"{root_cause}\n", style="green bold")
        content_parts.append(info)

        # 诊断报告（Markdown 渲染）- GAR 使用
        if diagnosis_summary:
            md = Markdown(diagnosis_summary, justify="left")
            content_parts.append(md)
            content_parts.append(Text(""))

        # RAR/GAR2 专用：构建 Markdown 诊断报告
        if observed_phenomena or reasoning or solution or unconfirmed_phenomena:
            diagnosis_md_parts = []

            if observed_phenomena:
                diagnosis_md_parts.append("### 观察到的现象\n")
                for i, obs in enumerate(observed_phenomena, 1):
                    # 支持 dict 或 str 格式
                    if isinstance(obs, dict):
                        diagnosis_md_parts.append(f"{i}. {obs.get('description', obs)}\n")
                    else:
                        diagnosis_md_parts.append(f"{i}. {obs}\n")
                diagnosis_md_parts.append("\n")

            if reasoning:
                diagnosis_md_parts.append("### 推导过程\n")
                diagnosis_md_parts.append(f"{reasoning}\n\n")

            if solution:
                diagnosis_md_parts.append("### 恢复措施\n")
                diagnosis_md_parts.append(f"{solution}\n\n")

            if unconfirmed_phenomena:
                diagnosis_md_parts.append("### 待确认现象\n")
                diagnosis_md_parts.append("以下现象可进一步确认以提高诊断准确性：\n")
                for i, p in enumerate(unconfirmed_phenomena, 1):
                    if isinstance(p, dict):
                        desc = p.get('description', '')
                        method = p.get('observation_method', '')
                        if method:
                            diagnosis_md_parts.append(f"{i}. {desc}\n   - 观察方法: {method}\n")
                        else:
                            diagnosis_md_parts.append(f"{i}. {desc}\n")
                    else:
                        diagnosis_md_parts.append(f"{i}. {p}\n")
                diagnosis_md_parts.append("\n")

            if diagnosis_md_parts:
                md = Markdown("".join(diagnosis_md_parts), justify="left")
                content_parts.append(md)
                content_parts.append(Text(""))

        # 引用工单
        if citations:
            content_parts.append(Text("引用工单", style="bold"))
            content_parts.append(Text(""))
            for i, citation in enumerate(citations, 1):
                cite_text = Text()
                cite_text.append(f"[{i}] ", style="dim")
                # 支持两种格式：dict 或 str
                if isinstance(citation, dict):
                    cite_text.append(f"{citation['ticket_id']}", style="bold cyan")
                    if citation.get('description'):
                        cite_text.append(f": {citation['description']}")
                else:
                    cite_text.append(f"{citation}", style="bold cyan")
                content_parts.append(cite_text)

        # 无边框模式：直接返回 Group
        if not show_border:
            title_style = "green bold" if not forced else "yellow bold"
            title_text = Text("✓ 根因已定位" if not forced else "⚠ 根因已定位（信息不足）", style=title_style)
            return Group(title_text, Text(""), *content_parts)

        # 使用 Panel 包装（有边框）
        panel = Panel(
            Group(*content_parts),
            title="✓ 根因已定位" if not forced else "⚠ 根因已定位（信息不足）",
            title_align="left",
            border_style="green" if not forced else "yellow",
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
        elif mode == "gar2":
            help_text = """
**GAR2 模式可用命令：**
- `/help` - 显示此帮助
- `/status` - 查看当前诊断状态
- `/reset` - 重新开始诊断
- `/exit` - 退出程序

**反馈格式：**
- `1确认 2否定` - 确认或否认推荐的现象
- `全否定` - 否认所有推荐的现象
- `确认` - 确认所有推荐的现象
- 直接描述新观察到的现象
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
