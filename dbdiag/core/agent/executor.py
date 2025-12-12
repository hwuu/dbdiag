"""Executor - 工具执行器

管理工具注册和执行，确保工具调用的类型安全。
"""

from typing import Dict, Optional, Tuple, Any
import json

from pydantic import ValidationError

from dbdiag.core.agent.models import SessionState, ToolOutput, CallResult, CallError
from dbdiag.core.agent.tools.base import BaseTool


class Executor:
    """工具执行器

    职责：
    1. 管理工具注册
    2. 执行工具调用
    3. 处理工具执行结果
    """

    def __init__(self):
        """初始化执行器"""
        self._tools: Dict[str, BaseTool] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """注册工具

        Args:
            tool: 工具实例
        """
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """获取工具

        Args:
            name: 工具名称

        Returns:
            工具实例，不存在则返回 None
        """
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """列出所有已注册的工具名称

        Returns:
            工具名称列表
        """
        return list(self._tools.keys())

    def execute(
        self,
        session: SessionState,
        tool_name: str,
        tool_input: dict,
    ) -> Tuple[ToolOutput, SessionState, Optional[CallError]]:
        """执行工具

        Args:
            session: 当前会话状态
            tool_name: 工具名称
            tool_input: 工具输入参数

        Returns:
            (工具输出, 更新后的 session, 错误信息)
            如果执行成功，错误信息为 None
        """
        # 获取工具
        tool = self._tools.get(tool_name)
        if not tool:
            error = CallError(
                tool=tool_name,
                error_message=f"未知工具: {tool_name}",
            )
            return ToolOutput(success=False, error_message=error.error_message), session, error

        try:
            # 预处理输入参数（适配 LLM 可能返回的简化格式）
            processed_input = self._preprocess_input(tool_name, tool_input)

            # 验证并转换输入参数
            input_model = tool.input_schema(**processed_input)

            # 执行工具
            output, new_session = tool.execute(session, input_model)

            return output, new_session, None

        except ValidationError as e:
            error_msg = f"参数验证失败: {str(e)}"
            error = CallError(tool=tool_name, error_message=error_msg)
            return ToolOutput(success=False, error_message=error_msg), session, error

        except Exception as e:
            error_msg = f"工具执行失败: {str(e)}"
            error = CallError(tool=tool_name, error_message=error_msg)
            return ToolOutput(success=False, error_message=error_msg), session, error

    def _preprocess_input(self, tool_name: str, tool_input: dict) -> dict:
        """预处理工具输入参数

        将 LLM 可能返回的简化格式转换为标准格式。

        Args:
            tool_name: 工具名称
            tool_input: 原始工具输入

        Returns:
            预处理后的输入
        """
        if tool_input is None:
            return {}

        processed = dict(tool_input)

        if tool_name == "match_phenomena":
            # 处理 raw_observations：将字符串列表转换为 RawObservation 格式
            if "raw_observations" in processed:
                raw_obs = processed["raw_observations"]
                if isinstance(raw_obs, list):
                    converted = []
                    for item in raw_obs:
                        if isinstance(item, str):
                            # 字符串 -> RawObservation dict
                            converted.append({"description": item})
                        elif isinstance(item, dict):
                            # 已经是 dict，确保有 description 字段
                            if "description" not in item and len(item) == 1:
                                # 可能是 {"0": "xxx"} 格式
                                converted.append({"description": list(item.values())[0]})
                            else:
                                # 复制并清理 context 字段
                                item_copy = dict(item)
                                # context 必须是字符串或 None，不能是空字典等
                                if "context" in item_copy:
                                    ctx = item_copy["context"]
                                    if not isinstance(ctx, str):
                                        item_copy["context"] = None
                                converted.append(item_copy)
                        else:
                            # 其他类型，尝试转为字符串
                            converted.append({"description": str(item)})
                    processed["raw_observations"] = converted
                elif isinstance(raw_obs, str):
                    # 单个字符串
                    processed["raw_observations"] = [{"description": raw_obs}]

            # 处理 confirmations 和 denials：确保是字符串列表
            for field in ["confirmations", "denials"]:
                if field in processed:
                    value = processed[field]
                    if isinstance(value, list):
                        processed[field] = [str(v) for v in value]
                    elif value is not None:
                        processed[field] = [str(value)]

            # 处理 dialogue_history：将列表格式转换为字符串
            if "dialogue_history" in processed:
                dh = processed["dialogue_history"]
                if isinstance(dh, list):
                    # LLM 可能返回 [{'role': 'user', 'content': '...'}, ...] 格式
                    lines = []
                    for item in dh:
                        if isinstance(item, dict):
                            role = item.get("role", "unknown")
                            content = item.get("content", "")
                            prefix = "用户" if role == "user" else "助手"
                            lines.append(f"{prefix}: {content}")
                        elif isinstance(item, str):
                            lines.append(item)
                    processed["dialogue_history"] = "\n".join(lines)
                elif dh is None:
                    processed["dialogue_history"] = ""

            # 处理 pending_recommendations：确保是字典列表格式
            if "pending_recommendations" in processed:
                pr = processed["pending_recommendations"]
                if pr is None or pr == "":
                    processed["pending_recommendations"] = []
                elif isinstance(pr, str):
                    # 单个字符串（可能是现象ID）
                    processed["pending_recommendations"] = [{"phenomenon_id": pr, "description": ""}]
                elif isinstance(pr, list):
                    # 列表：检查元素类型
                    converted = []
                    for item in pr:
                        if isinstance(item, str):
                            # 字符串 -> 字典
                            converted.append({"phenomenon_id": item, "description": ""})
                        elif isinstance(item, dict):
                            converted.append(item)
                    processed["pending_recommendations"] = converted
                else:
                    processed["pending_recommendations"] = []

        elif tool_name == "diagnose":
            # 处理 confirmed_phenomena：将简化格式转换为完整格式
            if "confirmed_phenomena" in processed:
                confirmed = processed["confirmed_phenomena"]
                if isinstance(confirmed, list):
                    converted = []
                    for item in confirmed:
                        if isinstance(item, (str, int)):
                            # 字符串或数字（现象 ID 或编号）-> MatchedPhenomenon dict
                            converted.append({
                                "phenomenon_id": str(item),
                                "phenomenon_description": "",
                                "user_observation": "",
                                "match_score": 1.0,
                            })
                        elif isinstance(item, dict):
                            # 确保 phenomenon_id 是字符串
                            item_copy = dict(item)
                            if "phenomenon_id" in item_copy:
                                item_copy["phenomenon_id"] = str(item_copy["phenomenon_id"])
                            converted.append(item_copy)
                    processed["confirmed_phenomena"] = converted

            # 处理 denied_phenomena：确保是字符串列表
            if "denied_phenomena" in processed:
                value = processed["denied_phenomena"]
                if isinstance(value, list):
                    processed["denied_phenomena"] = [str(v) for v in value]
                elif value is not None:
                    processed["denied_phenomena"] = [str(value)]

        return processed

    def format_result_for_planner(
        self,
        tool_name: str,
        output: ToolOutput,
    ) -> str:
        """将工具执行结果格式化为 Planner 可理解的字符串

        Args:
            tool_name: 工具名称
            output: 工具输出

        Returns:
            格式化的结果字符串
        """
        # 将 Pydantic 模型转换为字典
        output_dict = output.model_dump(exclude_none=True)

        return f"工具 {tool_name} 执行结果:\n```json\n{json.dumps(output_dict, ensure_ascii=False, indent=2)}\n```"

    def create_call_result(
        self,
        tool_name: str,
        output: ToolOutput,
    ) -> CallResult:
        """创建工具调用结果摘要

        Args:
            tool_name: 工具名称
            output: 工具输出

        Returns:
            CallResult 摘要
        """
        summary = self._generate_summary(tool_name, output)
        return CallResult(
            tool=tool_name,
            success=output.success,
            summary=summary,
        )

    def _generate_summary(self, tool_name: str, output: ToolOutput) -> str:
        """生成工具执行摘要

        Args:
            tool_name: 工具名称
            output: 工具输出

        Returns:
            摘要字符串
        """
        if not output.success:
            return f"执行失败: {output.error_message}"

        # 根据不同工具类型生成摘要
        output_dict = output.model_dump()

        if tool_name == "match_phenomena":
            all_matched = output_dict.get("all_matched", False)
            interpreted = output_dict.get("interpreted", [])
            if all_matched:
                matched_count = len([i for i in interpreted if i.get("matched_phenomenon")])
                return f"匹配成功，共 {matched_count} 个现象"
            else:
                needs_clarif = len([i for i in interpreted if i.get("needs_clarification")])
                return f"需要澄清 {needs_clarif} 个描述"

        elif tool_name == "diagnose":
            hypotheses = output_dict.get("hypotheses", [])
            diagnosis_complete = output_dict.get("diagnosis_complete", False)
            if diagnosis_complete:
                diagnosis = output_dict.get("diagnosis", {})
                return f"诊断完成，根因: {diagnosis.get('root_cause_description', '未知')}"
            elif hypotheses:
                top = hypotheses[0]
                return f"假设数: {len(hypotheses)}，最高置信度: {top.get('confidence', 0):.0%}"
            else:
                return "无假设"

        elif tool_name == "query_progress":
            status = output_dict.get("status", "exploring")
            top_conf = output_dict.get("top_confidence", 0)
            return f"状态: {status}，最高置信度: {top_conf:.0%}"

        elif tool_name == "query_hypotheses":
            hypotheses = output_dict.get("hypotheses", [])
            return f"返回 {len(hypotheses)} 个假设"

        elif tool_name == "query_relations":
            results = output_dict.get("results", [])
            return f"返回 {len(results)} 个关联"

        return "执行成功"
