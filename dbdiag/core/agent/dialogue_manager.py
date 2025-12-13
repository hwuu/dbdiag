"""AgentDialogueManager - Agent Loop 主控

协调 Planner、Executor、Responder 完成对话流程。
"""

import json
import uuid
from typing import Optional, List, Tuple, Callable, AsyncGenerator
from datetime import datetime

from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.core.agent.stream_models import StreamMessage, StreamMessageType
from dbdiag.core.agent.models import (
    SessionState,
    AgentResponse,
    AgentDecision,
    CallResult,
    CallError,
    MatchPhenomenaOutput,
    DiagnoseOutput,
)
from dbdiag.core.agent.planner import Planner
from dbdiag.core.agent.executor import Executor
from dbdiag.core.agent.responder import Responder
from dbdiag.core.agent.graph_engine import GraphEngine
from dbdiag.core.agent.tools import (
    DiagnoseTool,
    QueryProgressTool,
    QueryHypothesesTool,
    QueryRelationsTool,
    MatchPhenomenaTool,
)


class AgentDialogueManager:
    """Agent 对话管理器

    Agent Loop 主控，协调 Planner、Executor、Responder。

    流程：
    1. 接收用户输入
    2. Planner 决策下一步行动
    3. 如果是 call，Executor 执行工具，回到 2
    4. 如果是 respond，Responder 生成响应
    """

    # Agent Loop 最大迭代次数（防止无限循环）
    MAX_LOOP_ITERATIONS = 10

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        """初始化对话管理器

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务
            embedding_service: 向量服务
            progress_callback: 进度回调函数，用于输出 Agent Loop 过程信息
        """
        self._db_path = db_path
        self._llm_service = llm_service
        self._embedding_service = embedding_service
        self._progress_callback = progress_callback

        # 初始化组件
        self._planner = Planner(llm_service)
        self._executor = Executor()
        self._responder = Responder(llm_service)
        self._graph_engine = GraphEngine(db_path)

        # 注册工具
        self._register_tools()

        # 会话状态
        self._sessions: dict[str, SessionState] = {}

        # 对话历史（用于 Planner 上下文）
        self._dialogue_history: dict[str, List[Tuple[str, str]]] = {}  # session_id -> [(role, content), ...]

    def _register_tools(self):
        """注册所有工具"""
        # 确定性工具
        self._executor.register_tool(DiagnoseTool(self._graph_engine))
        self._executor.register_tool(QueryProgressTool(self._graph_engine))
        self._executor.register_tool(QueryHypothesesTool(self._graph_engine))
        self._executor.register_tool(QueryRelationsTool(self._graph_engine))

        # LLM 工具（传递进度回调）
        self._executor.register_tool(MatchPhenomenaTool(
            self._db_path,
            self._embedding_service,
            self._llm_service,
            progress_callback=self._progress_callback,
        ))

    def create_session(self, user_problem: str = "") -> str:
        """创建新会话

        Args:
            user_problem: 用户问题描述

        Returns:
            session_id
        """
        session_id = str(uuid.uuid4())[:8]
        session = SessionState(
            session_id=session_id,
            user_problem=user_problem,
        )
        self._sessions[session_id] = session
        self._dialogue_history[session_id] = []
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """获取会话状态

        Args:
            session_id: 会话 ID

        Returns:
            SessionState，不存在则返回 None
        """
        return self._sessions.get(session_id)

    def process_input(
        self,
        session_id: str,
        user_input: str,
    ) -> AgentResponse:
        """处理用户输入

        Args:
            session_id: 会话 ID
            user_input: 用户输入文本

        Returns:
            AgentResponse 响应
        """
        # 获取会话
        session = self._sessions.get(session_id)
        if not session:
            return self._responder.generate_simple(
                f"会话 {session_id} 不存在。请创建新会话。"
            )

        # 记录用户输入到对话历史
        self._add_to_history(session_id, "user", user_input)

        # 执行 Agent Loop
        response, updated_session = self._run_agent_loop(
            session,
            f"用户输入: {user_input}",
        )

        # 更新会话
        self._sessions[session_id] = updated_session

        # 记录助手响应到对话历史
        self._add_to_history(session_id, "assistant", response.message)

        return response

    async def process_stream(
        self,
        session_id: str,
        user_input: str,
    ) -> AsyncGenerator[StreamMessage, None]:
        """流式处理用户输入

        Args:
            session_id: 会话 ID
            user_input: 用户输入文本

        Yields:
            StreamMessage: 流式消息
        """
        # 获取会话
        session = self._sessions.get(session_id)
        if not session:
            yield StreamMessage(
                type=StreamMessageType.FINAL,
                content=f"会话 {session_id} 不存在。请创建新会话。",
                data=None,
            )
            return

        # 记录用户输入到对话历史
        self._add_to_history(session_id, "user", user_input)

        # 流式执行 Agent Loop
        full_message = ""
        final_data = None

        async for msg in self._run_agent_loop_stream(
            session,
            f"用户输入: {user_input}",
        ):
            yield msg

            # 收集完整响应
            if msg.type == StreamMessageType.CHUNK:
                full_message += msg.content or ""
            elif msg.type == StreamMessageType.FINAL:
                full_message = msg.content or full_message
                final_data = msg.data
                # 更新会话（需要从 final_data 中恢复会话状态）

        # 记录助手响应到对话历史
        if full_message:
            self._add_to_history(session_id, "assistant", full_message)

    def _run_agent_loop(
        self,
        session: SessionState,
        initial_context: str,
    ) -> Tuple[AgentResponse, SessionState]:
        """运行 Agent Loop

        Args:
            session: 当前会话状态
            initial_context: 初始上下文（用户输入）

        Returns:
            (响应, 更新后的会话)
        """
        current_session = session
        loop_context = initial_context
        call_results: List[CallResult] = []
        call_errors: List[CallError] = []

        # 获取对话历史
        dialogue_history = self._format_dialogue_history(session.session_id)

        # 保存本轮 match_phenomena 的匹配结果（用于传递给 diagnose）
        pending_matched_phenomena: List[dict] = []

        for iteration in range(self.MAX_LOOP_ITERATIONS):
            # 1. Planner 决策
            self._report_progress("Planner 思考中...")
            decision = self._planner.decide(
                current_session,
                loop_context,
                dialogue_history,
            )

            # 2. 根据决策执行
            if decision.decision == "call" and decision.tool:
                # 报告准备执行工具
                self._report_progress(f"准备调用工具: {decision.tool}")

                # 执行工具
                tool_input = decision.tool_input or {}

                # 特殊处理 match_phenomena：注入上下文
                if decision.tool == "match_phenomena":
                    tool_input = self._enrich_match_phenomena_input(
                        tool_input,
                        current_session,
                        dialogue_history,
                    )

                # 特殊处理 diagnose：注入 match_phenomena 的匹配结果
                if decision.tool == "diagnose":
                    tool_input = self._enrich_diagnose_input(
                        tool_input,
                        pending_matched_phenomena,
                        current_session,
                    )

                output, current_session, error = self._executor.execute(
                    current_session,
                    decision.tool,
                    tool_input,
                )

                if error:
                    call_errors.append(error)
                    self._report_progress(f"工具 {decision.tool} 执行失败: {error.error_message}")
                else:
                    call_result = self._executor.create_call_result(decision.tool, output)
                    call_results.append(call_result)
                    self._report_progress(f"工具 {decision.tool} 执行成功: {call_result.summary}")

                # 更新 loop_context 为工具执行结果
                loop_context = self._executor.format_result_for_planner(
                    decision.tool, output
                )

                # 特殊处理：match_phenomena 成功时，保存匹配结果
                if decision.tool == "match_phenomena" and isinstance(output, MatchPhenomenaOutput):
                    if output.all_matched:
                        # 提取匹配成功的现象，保存供 diagnose 使用（去重）
                        existing_ids = {p["phenomenon_id"] for p in pending_matched_phenomena}
                        for interp in output.interpreted:
                            if interp.matched_phenomenon:
                                pid = interp.matched_phenomenon.phenomenon_id
                                if pid not in existing_ids:
                                    pending_matched_phenomena.append({
                                        "phenomenon_id": pid,
                                        "phenomenon_description": interp.matched_phenomenon.phenomenon_description,
                                        "user_observation": interp.matched_phenomenon.user_observation,
                                        "match_score": interp.matched_phenomenon.match_score,
                                    })
                                    existing_ids.add(pid)
                        self._report_progress(f"保存匹配结果: {len(pending_matched_phenomena)} 个现象")
                    else:
                        self._report_progress("现象匹配需要澄清，准备生成响应...")
                        response = self._responder.generate_for_clarification(
                            current_session, output
                        )
                        return response, current_session

                # 特殊处理：diagnose 执行后，直接生成响应（不再让 Planner 决策）
                if decision.tool == "diagnose" and isinstance(output, DiagnoseOutput):
                    self._report_progress(f"诊断完成: 假设数={len(output.hypotheses)}, 推荐数={len(output.recommendations)}, 完成={output.diagnosis_complete}")
                    if output.hypotheses:
                        top = output.hypotheses[0]
                        self._report_progress(f"  Top假设: {top.root_cause_id} ({top.confidence:.0%})")
                    if output.recommendations:
                        self._report_progress(f"  推荐现象: {[r.phenomenon_id for r in output.recommendations]}")
                    self._report_progress("准备生成响应...")
                    response = self._responder.generate_for_diagnose(
                        current_session, output
                    )
                    return response, current_session

            elif decision.decision == "respond":
                # 生成响应
                self._report_progress("准备生成响应...")
                response_context = decision.response_context or {"type": "unknown", "data": {}}
                response = self._responder.generate(
                    current_session,
                    response_context,
                    call_results,
                    call_errors,
                )
                return response, current_session

            else:
                # 无效决策，直接回复
                self._report_progress("决策无效，生成默认响应...")
                response = self._responder.generate_simple(
                    "抱歉，我不太理解。请尝试描述你观察到的数据库问题。",
                    current_session,
                )
                return response, current_session

        # 达到最大迭代次数
        self._report_progress("达到最大迭代次数，结束循环")
        response = self._responder.generate_simple(
            "处理时间过长，请重新描述你的问题。",
            current_session,
        )
        return response, current_session

    async def _run_agent_loop_stream(
        self,
        session: SessionState,
        initial_context: str,
    ) -> AsyncGenerator[StreamMessage, None]:
        """流式运行 Agent Loop

        Args:
            session: 当前会话状态
            initial_context: 初始上下文（用户输入）

        Yields:
            StreamMessage: 流式消息
        """
        current_session = session
        loop_context = initial_context
        call_results: List[CallResult] = []
        call_errors: List[CallError] = []

        # 获取对话历史
        dialogue_history = self._format_dialogue_history(session.session_id)

        # 保存本轮 match_phenomena 的匹配结果（用于传递给 diagnose）
        pending_matched_phenomena: List[dict] = []

        for iteration in range(self.MAX_LOOP_ITERATIONS):
            # 1. Planner 决策
            yield StreamMessage(type=StreamMessageType.PROGRESS, content="Planner 思考中...")
            decision = self._planner.decide(
                current_session,
                loop_context,
                dialogue_history,
            )

            # 2. 根据决策执行
            if decision.decision == "call" and decision.tool:
                # 报告准备执行工具
                yield StreamMessage(
                    type=StreamMessageType.PROGRESS,
                    content=f"准备调用工具: {decision.tool}"
                )

                # 执行工具
                tool_input = decision.tool_input or {}

                # 特殊处理 match_phenomena：注入上下文
                if decision.tool == "match_phenomena":
                    tool_input = self._enrich_match_phenomena_input(
                        tool_input,
                        current_session,
                        dialogue_history,
                    )

                # 特殊处理 diagnose：注入 match_phenomena 的匹配结果
                if decision.tool == "diagnose":
                    tool_input = self._enrich_diagnose_input(
                        tool_input,
                        pending_matched_phenomena,
                        current_session,
                    )

                output, current_session, error = self._executor.execute(
                    current_session,
                    decision.tool,
                    tool_input,
                )

                if error:
                    call_errors.append(error)
                    yield StreamMessage(
                        type=StreamMessageType.PROGRESS,
                        content=f"工具 {decision.tool} 执行失败: {error.error_message}"
                    )
                else:
                    call_result = self._executor.create_call_result(decision.tool, output)
                    call_results.append(call_result)
                    yield StreamMessage(
                        type=StreamMessageType.PROGRESS,
                        content=f"工具 {decision.tool} 执行成功: {call_result.summary}"
                    )

                # 更新 loop_context 为工具执行结果
                loop_context = self._executor.format_result_for_planner(
                    decision.tool, output
                )

                # 特殊处理：match_phenomena 成功时，保存匹配结果
                if decision.tool == "match_phenomena" and isinstance(output, MatchPhenomenaOutput):
                    if output.all_matched:
                        # 提取匹配成功的现象，保存供 diagnose 使用（去重）
                        existing_ids = {p["phenomenon_id"] for p in pending_matched_phenomena}
                        for interp in output.interpreted:
                            if interp.matched_phenomenon:
                                pid = interp.matched_phenomenon.phenomenon_id
                                if pid not in existing_ids:
                                    pending_matched_phenomena.append({
                                        "phenomenon_id": pid,
                                        "phenomenon_description": interp.matched_phenomenon.phenomenon_description,
                                        "user_observation": interp.matched_phenomenon.user_observation,
                                        "match_score": interp.matched_phenomenon.match_score,
                                    })
                                    existing_ids.add(pid)
                        yield StreamMessage(
                            type=StreamMessageType.PROGRESS,
                            content=f"保存匹配结果: {len(pending_matched_phenomena)} 个现象"
                        )
                    else:
                        yield StreamMessage(
                            type=StreamMessageType.PROGRESS,
                            content="现象匹配需要澄清，准备生成响应..."
                        )
                        # 在生成响应前保存会话（确保 CLI 能获取到最新状态）
                        self._sessions[session.session_id] = current_session
                        # 流式生成澄清响应
                        async for msg in self._responder.generate_for_clarification_stream(
                            current_session, output
                        ):
                            yield msg
                        return

                # 特殊处理：diagnose 执行后，直接生成响应
                if decision.tool == "diagnose" and isinstance(output, DiagnoseOutput):
                    yield StreamMessage(
                        type=StreamMessageType.PROGRESS,
                        content=f"诊断完成: 假设数={len(output.hypotheses)}, 推荐数={len(output.recommendations)}, 完成={output.diagnosis_complete}"
                    )
                    if output.hypotheses:
                        top = output.hypotheses[0]
                        yield StreamMessage(
                            type=StreamMessageType.PROGRESS,
                            content=f"  Top假设: {top.root_cause_id} ({top.confidence:.0%})"
                        )
                    # Debug: 显示 diagnose 返回的推荐（调试时取消注释）
                    # if output.recommendations:
                    #     yield StreamMessage(
                    #         type=StreamMessageType.PROGRESS,
                    #         content=f"  推荐现象: {[r.phenomenon_id for r in output.recommendations]}"
                    #     )
                    # # Debug: 显示 session 中的推荐
                    # if current_session.recommendations:
                    #     yield StreamMessage(
                    #         type=StreamMessageType.PROGRESS,
                    #         content=f"  Session推荐: {[r.phenomenon_id for r in current_session.recommendations]}"
                    #     )
                    # else:
                    #     yield StreamMessage(
                    #         type=StreamMessageType.PROGRESS,
                    #         content="  Session推荐: 无（session.recommendations 为空）"
                    #     )
                    # 在生成响应前保存会话（确保 CLI 能获取到最新状态）
                    self._sessions[session.session_id] = current_session
                    yield StreamMessage(
                        type=StreamMessageType.PROGRESS,
                        content="准备生成响应..."
                    )
                    # 流式生成诊断响应
                    async for msg in self._responder.generate_for_diagnose_stream(
                        current_session, output
                    ):
                        yield msg
                    return

            elif decision.decision == "respond":
                # 在生成响应前保存会话（确保 CLI 能获取到最新状态）
                self._sessions[session.session_id] = current_session
                # 生成响应
                yield StreamMessage(
                    type=StreamMessageType.PROGRESS,
                    content="准备生成响应..."
                )
                response_context = decision.response_context or {"type": "unknown", "data": {}}
                # 流式生成响应
                async for msg in self._responder.generate_stream(
                    current_session,
                    response_context,
                    call_results,
                    call_errors,
                ):
                    yield msg
                return

            else:
                # 无效决策，直接回复
                yield StreamMessage(
                    type=StreamMessageType.PROGRESS,
                    content="决策无效，生成默认响应..."
                )
                yield StreamMessage(
                    type=StreamMessageType.FINAL,
                    content="抱歉，我不太理解。请尝试描述你观察到的数据库问题。",
                    data=None,
                )
                return

        # 达到最大迭代次数
        yield StreamMessage(
            type=StreamMessageType.PROGRESS,
            content="达到最大迭代次数，结束循环"
        )
        yield StreamMessage(
            type=StreamMessageType.FINAL,
            content="处理时间过长，请重新描述你的问题。",
            data=None,
        )

    def _enrich_match_phenomena_input(
        self,
        tool_input: dict,
        session: SessionState,
        dialogue_history: str,
    ) -> dict:
        """为 match_phenomena 注入上下文

        Args:
            tool_input: 原始工具输入
            session: 会话状态
            dialogue_history: 对话历史

        Returns:
            增强后的工具输入
        """
        enriched = dict(tool_input)

        # 注入对话历史
        if "dialogue_history" not in enriched or not enriched["dialogue_history"]:
            enriched["dialogue_history"] = dialogue_history

        # 注入待确认现象
        if "pending_recommendations" not in enriched or not enriched["pending_recommendations"]:
            enriched["pending_recommendations"] = self._planner.build_pending_recommendations_for_input(
                session.recommendations
            )

        # 将序号转换为真正的现象 ID
        confirmations = enriched.get("confirmations", [])
        if confirmations and session.recommendations:
            converted = []
            for confirm_id in confirmations:
                confirm_str = str(confirm_id)
                # 检查是否是序号（纯数字）
                if confirm_str.isdigit():
                    idx = int(confirm_str) - 1  # 序号从 1 开始
                    if 0 <= idx < len(session.recommendations):
                        rec = session.recommendations[idx]
                        converted.append(rec.phenomenon_id)
                        self._report_progress(f"  序号 {confirm_str} -> {rec.phenomenon_id}")
                    else:
                        # 序号越界，保留原值
                        converted.append(confirm_str)
                else:
                    # 已经是现象 ID
                    converted.append(confirm_str)
            enriched["confirmations"] = converted

        return enriched

    def _enrich_diagnose_input(
        self,
        tool_input: dict,
        pending_matched_phenomena: List[dict],
        session: SessionState,
    ) -> dict:
        """为 diagnose 注入 match_phenomena 的匹配结果

        Args:
            tool_input: 原始工具输入
            pending_matched_phenomena: 本轮 match_phenomena 匹配成功的现象列表
            session: 会话状态（用于将序号转换为现象 ID）

        Returns:
            增强后的工具输入
        """
        enriched = dict(tool_input)

        # 合并 Planner 提供的和自动收集的 confirmed_phenomena
        existing = enriched.get("confirmed_phenomena", [])
        if not isinstance(existing, list):
            existing = []

        # 将序号转换为真正的现象 ID
        converted_existing = []
        for item in existing:
            if isinstance(item, dict):
                pid = item.get("phenomenon_id", "")
            else:
                pid = str(item)

            # 检查是否是序号（纯数字）
            if pid.isdigit():
                idx = int(pid) - 1  # 序号从 1 开始
                if 0 <= idx < len(session.recommendations):
                    # 转换为真正的现象 ID
                    rec = session.recommendations[idx]
                    converted_existing.append({
                        "phenomenon_id": rec.phenomenon_id,
                        "phenomenon_description": rec.description,
                        "user_observation": "用户确认",
                        "match_score": 1.0,
                    })
                    self._report_progress(f"  序号 {pid} -> {rec.phenomenon_id}")
            else:
                # 已经是现象 ID，需要确保所有必填字段都存在
                # 尝试从 session.recommendations 查找描述
                description = ""
                if isinstance(item, dict):
                    description = item.get("phenomenon_description", "")
                if not description:
                    for rec in session.recommendations:
                        if rec.phenomenon_id == pid:
                            description = rec.description
                            break

                user_obs = ""
                if isinstance(item, dict):
                    user_obs = item.get("user_observation", "")
                if not user_obs:
                    user_obs = "用户确认"

                match_score = 1.0
                if isinstance(item, dict) and "match_score" in item:
                    match_score = item["match_score"]

                converted_existing.append({
                    "phenomenon_id": pid,
                    "phenomenon_description": description,
                    "user_observation": user_obs,
                    "match_score": match_score,
                })

        existing = converted_existing

        # 添加自动收集的匹配结果（去重）
        existing_ids = {p.get("phenomenon_id") for p in existing if isinstance(p, dict)}
        for matched in pending_matched_phenomena:
            if matched["phenomenon_id"] not in existing_ids:
                existing.append(matched)
                existing_ids.add(matched["phenomenon_id"])

        # 修正 match_score 范围（Planner 可能返回百分比形式如 98 而非 0.98）
        for item in existing:
            if isinstance(item, dict) and "match_score" in item:
                score = item["match_score"]
                if isinstance(score, (int, float)) and score > 1:
                    item["match_score"] = score / 100.0

        enriched["confirmed_phenomena"] = existing
        self._report_progress(f"注入 diagnose 输入: {len(existing)} 个确认现象")

        return enriched

    def _add_to_history(self, session_id: str, role: str, content: str):
        """添加到对话历史

        Args:
            session_id: 会话 ID
            role: 角色（user/assistant）
            content: 内容
        """
        if session_id not in self._dialogue_history:
            self._dialogue_history[session_id] = []

        self._dialogue_history[session_id].append((role, content))

        # 保留最近 10 轮对话
        if len(self._dialogue_history[session_id]) > 20:
            self._dialogue_history[session_id] = self._dialogue_history[session_id][-20:]

    def _format_dialogue_history(self, session_id: str) -> str:
        """格式化对话历史

        Args:
            session_id: 会话 ID

        Returns:
            格式化的对话历史字符串
        """
        history = self._dialogue_history.get(session_id, [])
        if not history:
            return "无"

        lines = []
        for role, content in history[-10:]:  # 最近 5 轮（10 条消息）
            prefix = "用户" if role == "user" else "助手"
            # 截断过长的内容
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"{prefix}: {content}")

        return "\n".join(lines)

    def reset_session(self, session_id: str) -> bool:
        """重置会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        if session_id not in self._sessions:
            return False

        old_session = self._sessions[session_id]
        new_session = SessionState(
            session_id=session_id,
            user_problem=old_session.user_problem,
        )
        self._sessions[session_id] = new_session
        self._dialogue_history[session_id] = []
        return True

    def _report_progress(self, message: str):
        """报告进度

        Args:
            message: 进度消息
        """
        if self._progress_callback:
            self._progress_callback(message)
