"""纯文本格式化器

负责将系统响应格式化为简洁的纯文本输出，适合 CLI 环境。
"""
from typing import Dict, Any


class TextFormatter:
    """纯文本格式化器"""

    @staticmethod
    def format_welcome() -> str:
        """格式化欢迎信息"""
        return """
=== 数据库诊断助手 ===

请描述您遇到的数据库问题（或输入 /help 查看命令）：
""".strip()

    @staticmethod
    def format_step_recommendation(response: Dict[str, Any]) -> str:
        """
        格式化步骤推荐 (V1, deprecated)

        Args:
            response: 系统响应字典

        Returns:
            格式化的文本
        """
        step = response.get("step", {})
        message = response.get("message", "")

        output = ["\n--- 推荐诊断步骤 ---\n"]

        if isinstance(step, dict):
            # 观察目标
            if "observed_fact" in step:
                output.append(f"观察目标: {step['observed_fact']}\n")

            # 操作方法
            if "observation_method" in step:
                output.append("操作方法:")
                method_lines = step["observation_method"].strip().split("\n")
                for line in method_lines:
                    output.append(f"    {line}")
                output.append("")

            # 诊断目的
            if "analysis_result" in step:
                output.append(f"诊断目的: {step['analysis_result']}\n")

        # 引用信息
        citations = response.get("citations", [])
        if citations:
            output.append("引用工单:")
            for i, citation in enumerate(citations, 1):
                output.append(f"  [{i}] {citation.get('ticket_id', 'N/A')}: {citation.get('description', 'N/A')}")
                output.append(f"      根因: {citation.get('root_cause', 'N/A')}")
            output.append("")

        output.append("请输入检查结果：")

        return "\n".join(output)

    @staticmethod
    def format_phenomenon_recommendation(response: Dict[str, Any]) -> str:
        """
        格式化现象推荐 (V2，支持批量，包含关联假设)

        Args:
            response: 系统响应字典

        Returns:
            格式化的文本
        """
        # 优先使用包含原因的新格式
        phenomena_with_reasons = response.get("phenomena_with_reasons", [])

        # 如果没有新格式，回退到旧格式
        if not phenomena_with_reasons:
            phenomena = response.get("phenomena", [])
            if not phenomena and response.get("phenomenon"):
                phenomena = [response["phenomenon"]]

            if not phenomena:
                return response.get("message", "")

            output = [f"\n--- 建议确认以下 {len(phenomena)} 个现象 ---\n"]

            for i, phenomenon in enumerate(phenomena, 1):
                output.append(f"[{i}] {phenomenon.phenomenon_id}")
                output.append(f"    描述: {phenomenon.description}")
                if phenomenon.observation_method:
                    output.append("    观察方法:")
                    method_lines = phenomenon.observation_method.strip().split("\n")
                    for line in method_lines:
                        output.append(f"        {line}")
                output.append("")

            output.append("请输入检查结果（如：1确认 2否定 3确认）：")
            return "\n".join(output)

        # 新格式：包含关联假设
        output = [f"\n--- 建议确认以下 {len(phenomena_with_reasons)} 个现象 ---\n"]

        for i, item in enumerate(phenomena_with_reasons, 1):
            phenomenon = item["phenomenon"]
            reason = item.get("reason", "")

            output.append(f"[{i}] {phenomenon.phenomenon_id}")
            if reason:
                output.append(f"    推荐原因: {reason}")
            output.append(f"    描述: {phenomenon.description}")
            if phenomenon.observation_method:
                output.append("    观察方法:")
                method_lines = phenomenon.observation_method.strip().split("\n")
                for line in method_lines:
                    output.append(f"        {line}")
            output.append("")

        output.append("请输入检查结果（如：1确认 2否定 3确认）：")

        return "\n".join(output)

    @staticmethod
    def format_root_cause_confirmation(response: Dict[str, Any]) -> str:
        """
        格式化根因确认

        Args:
            response: 系统响应字典

        Returns:
            格式化的文本
        """
        root_cause = response.get("root_cause", "未知")
        confidence = response.get("confidence", 0.0)

        output = ["\n" + "=" * 50]
        output.append("根因已定位！")
        output.append("=" * 50)
        output.append(f"\n根因: {root_cause}")
        output.append(f"置信度: {confidence:.0%}\n")

        message = response.get("message", "")
        if message:
            output.append(message)

        return "\n".join(output)

    @staticmethod
    def format_status(session_info: Dict[str, Any]) -> str:
        """
        格式化状态信息

        Args:
            session_info: 会话信息字典

        Returns:
            格式化的文本
        """
        output = ["\n--- 当前诊断状态 ---\n"]
        output.append(f"会话 ID: {session_info.get('session_id', 'N/A')}")
        output.append(f"问题描述: {session_info.get('user_problem', 'N/A')}")
        output.append(f"已确认事实数: {session_info.get('confirmed_facts_count', 0)}")
        output.append(f"活跃假设数: {session_info.get('active_hypotheses_count', 0)}")
        output.append(f"对话轮次: {session_info.get('dialogue_turns', 0)}\n")

        return "\n".join(output)

    @staticmethod
    def format_help() -> str:
        """格式化帮助信息"""
        return """
--- 可用命令 ---

/help       显示此帮助信息
/status     查看当前诊断进展
/history    查看对话历史（最近5轮）
/reset      重新开始新的诊断会话
/exit       退出程序

直接输入诊断结果或观察到的现象即可继续诊断。
""".strip()

    @staticmethod
    def format_error(error_message: str) -> str:
        """
        格式化错误信息

        Args:
            error_message: 错误消息

        Returns:
            格式化的文本
        """
        return f"\n[错误] {error_message}\n"

    @staticmethod
    def format_system_message(message: str) -> str:
        """
        格式化系统消息

        Args:
            message: 系统消息

        Returns:
            格式化的文本
        """
        return f"\n[系统] {message}\n"
