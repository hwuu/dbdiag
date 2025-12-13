"""Responder - 响应生成层

将 Agent Loop 的最终结果转换为自然语言响应。
"""

from typing import Optional, List, Dict, Any, AsyncGenerator

from dbdiag.services.llm_service import LLMService
from dbdiag.core.agent.stream_models import StreamMessage, StreamMessageType
from dbdiag.core.agent.models import (
    SessionState,
    AgentResponse,
    ResponseDetails,
    CallResult,
    CallError,
    Recommendation,
    Diagnosis,
    DiagnoseOutput,
    MatchPhenomenaOutput,
    QueryProgressOutput,
    QueryHypothesesOutput,
)


RESPONDER_SYSTEM_PROMPT = """你是一个数据库诊断助手。根据诊断结果生成自然、友好的响应。

## 要求

1. 用口语化的方式描述诊断进展和建议
2. **重要：推荐现象必须严格使用"推荐确认的现象"章节中提供的内容**：
   - **禁止自己编造推荐现象**
   - 必须使用提供的现象描述、观察方法、推荐原因
   - 可以适当润色语言，但内容必须与提供的信息一致
   - 如果没有提供推荐现象，则不要编造
3. 如果有工具调用失败，必须说明：
   - 什么操作执行不成功
   - 失败原因
   - 目前的状况是什么
   - 建议用户怎么做
4. 根据诊断状态调整语气：
   - exploring（早期）：鼓励用户继续提供信息
   - narrowing（缩小范围）：表达进展，引导确认关键现象
   - confirming（接近确认）：表达信心，但提醒还需确认
   - stuck（卡住）：委婉表达困难，建议换个方向
5. 如果有多个工具调用结果，自然地整合在一起
6. **诊断完成时**（diagnosis_complete=true）：
   - 明确告知用户已确定根因
   - 展示根因描述、置信度
   - 展示解决方案（solution）
   - **不再让用户确认其他现象**

## 输出格式

直接输出响应文本。推荐现象用编号列表展示，每个现象包含描述、观察方法、推荐原因。
诊断完成时，输出诊断结论和解决方案。
"""


class Responder:
    """响应生成层

    职责：
    1. 将工具执行结果转换为自然语言响应
    2. 生成用户友好的诊断建议
    3. 处理错误情况的友好提示
    """

    def __init__(self, llm_service: LLMService):
        """初始化 Responder

        Args:
            llm_service: LLM 服务
        """
        self._llm_service = llm_service

    def generate(
        self,
        session: SessionState,
        response_context: Dict[str, Any],
        call_results: List[CallResult],
        call_errors: List[CallError],
    ) -> AgentResponse:
        """生成响应

        Args:
            session: 当前会话状态
            response_context: 响应上下文（来自 Planner 的 response_context）
            call_results: 工具调用结果列表
            call_errors: 工具调用错误列表

        Returns:
            AgentResponse 响应
        """
        # 构建 prompt
        user_prompt = self._build_prompt(
            session, response_context, call_results, call_errors
        )

        # 调用 LLM 生成响应
        message = self._llm_service.generate(
            user_prompt,
            system_prompt=RESPONDER_SYSTEM_PROMPT,
        )

        # 构建结构化详情
        details = self._build_details(session, call_results, call_errors)

        return AgentResponse(
            message=message,
            details=details,
        )

    async def generate_stream(
        self,
        session: SessionState,
        response_context: Dict[str, Any],
        call_results: List[CallResult],
        call_errors: List[CallError],
    ) -> AsyncGenerator[StreamMessage, None]:
        """流式生成响应

        Args:
            session: 当前会话状态
            response_context: 响应上下文（来自 Planner 的 response_context）
            call_results: 工具调用结果列表
            call_errors: 工具调用错误列表

        Yields:
            StreamMessage: 流式消息（PROGRESS, CHUNK, FINAL）
        """
        # 发送进度消息
        yield StreamMessage(type=StreamMessageType.PROGRESS, content="生成响应中...")

        # 构建 prompt
        user_prompt = self._build_prompt(
            session, response_context, call_results, call_errors
        )

        # Debug: 打印发送给 LLM 的 prompt（调试时取消注释）
        # yield StreamMessage(
        #     type=StreamMessageType.PROGRESS,
        #     content=f"[DEBUG] Responder prompt:\n{user_prompt[:2000]}..."  # 截取前 2000 字符
        # )

        # 流式调用 LLM，收集完整响应
        full_message = ""
        async for chunk in self._llm_service.generate_stream(
            user_prompt,
            system_prompt=RESPONDER_SYSTEM_PROMPT,
        ):
            full_message += chunk
            yield StreamMessage(type=StreamMessageType.CHUNK, content=chunk)

        # 构建结构化详情
        details = self._build_details(session, call_results, call_errors)

        # 发送最终消息
        yield StreamMessage(
            type=StreamMessageType.FINAL,
            content=full_message,
            data=details.model_dump(),
        )

    def generate_simple(
        self,
        message: str,
        session: Optional[SessionState] = None,
    ) -> AgentResponse:
        """生成简单响应（不调用 LLM）

        用于简单场景，如问候、错误提示等。

        Args:
            message: 响应消息
            session: 会话状态（可选）

        Returns:
            AgentResponse 响应
        """
        details = None
        if session:
            details = ResponseDetails(
                status="exploring" if not session.hypotheses else "narrowing",
                top_hypothesis=session.top_hypothesis.root_cause_description if session.top_hypothesis else None,
                top_confidence=session.top_hypothesis.confidence if session.top_hypothesis else 0.0,
                call_results=[],
            )

        return AgentResponse(
            message=message,
            details=details,
        )

    def _build_prompt(
        self,
        session: SessionState,
        response_context: Dict[str, Any],
        call_results: List[CallResult],
        call_errors: List[CallError],
    ) -> str:
        """构建 user prompt"""
        sections = []

        # 响应类型
        response_type = response_context.get("type", "unknown")
        sections.append(f"## 响应类型: {response_type}")

        # 会话状态摘要
        sections.append("\n## 当前会话状态")
        sections.append(f"- 已确认现象: {session.confirmed_count} 个")
        sections.append(f"- 已否认现象: {session.denied_count} 个")
        if session.top_hypothesis:
            sections.append(f"- 最可能根因: {session.top_hypothesis.root_cause_description}")
            sections.append(f"- 置信度: {session.top_hypothesis.confidence:.0%}")

        # 工具调用结果
        if call_results:
            sections.append("\n## 工具调用结果")
            for result in call_results:
                status = "成功" if result.success else "失败"
                sections.append(f"- {result.tool}: {status} - {result.summary}")

        # 工具调用错误
        if call_errors:
            sections.append("\n## 工具调用错误")
            for error in call_errors:
                sections.append(f"- {error.tool}: {error.error_message}")

        # 响应上下文数据
        data = response_context.get("data", {})
        if data:
            sections.append("\n## 响应数据")
            sections.append(self._format_response_data(response_type, data))

        # 推荐现象
        if session.recommendations:
            sections.append("\n## 推荐确认的现象")
            for i, rec in enumerate(session.recommendations, 1):
                sections.append(f"\n### {i}. {rec.description}")
                sections.append(f"- 现象 ID: {rec.phenomenon_id}")
                sections.append(f"- 观察方法: {rec.observation_method}")
                sections.append(f"- 推荐原因: {rec.reason}")

        sections.append("\n请生成自然、友好的响应文本。")

        return "\n".join(sections)

    def _format_response_data(self, response_type: str, data: Dict[str, Any]) -> str:
        """格式化响应数据"""
        if response_type == "diagnosis_result":
            diagnosis_complete = data.get("diagnosis_complete", False)
            diagnosis = data.get("diagnosis")

            # 诊断已完成，输出最终结论
            if diagnosis_complete and diagnosis:
                conf = diagnosis.get('confidence', 0)
                if isinstance(conf, str):
                    try:
                        conf = float(conf)
                    except ValueError:
                        conf = 0
                lines = [
                    "**诊断已完成**",
                    f"- 根因: {diagnosis.get('root_cause_description', '未知')}",
                    f"- 置信度: {conf:.0%}",
                ]
                solution = diagnosis.get('solution', '')
                if solution:
                    lines.append(f"- 解决方案: {solution}")
                return "\n".join(lines)

            # 诊断进行中，输出当前假设
            hypotheses = data.get("hypotheses", [])
            if hypotheses:
                top = hypotheses[0]
                conf = top.get('confidence', 0)
                if isinstance(conf, str):
                    try:
                        conf = float(conf)
                    except ValueError:
                        conf = 0
                return f"最可能根因: {top.get('root_cause_description', '未知')} (置信度: {conf:.0%})"
            return "暂无假设"

        elif response_type == "clarification_needed":
            question = data.get("question", "")
            options = data.get("options", [])
            lines = [f"需要澄清: {question}"]
            if options:
                lines.append("选项:")
                for opt in options:
                    lines.append(f"  - {opt}")
            return "\n".join(lines)

        elif response_type == "progress_summary":
            return f"状态: {data.get('status', '未知')}, 轮次: {data.get('rounds', 0)}"

        elif response_type == "greeting":
            return "用户打招呼，请友好回应并引导开始诊断"

        elif response_type == "error":
            return f"错误: {data.get('message', '未知错误')}"

        else:
            import json
            return json.dumps(data, ensure_ascii=False, indent=2)

    def _build_details(
        self,
        session: SessionState,
        call_results: List[CallResult],
        call_errors: List[CallError],
    ) -> ResponseDetails:
        """构建结构化详情"""
        # 确定状态
        if not session.hypotheses:
            status = "exploring"
        elif session.top_hypothesis.confidence >= 0.95:
            status = "confirming"
        elif session.top_hypothesis.confidence >= 0.5:
            status = "narrowing"
        else:
            status = "exploring"

        # 获取诊断结论（如果有）
        diagnosis = None
        # 诊断结论在会话状态中不直接保存，而是在工具输出中
        # 这里暂时留空，由 DialogueManager 在需要时填充

        return ResponseDetails(
            status=status,
            top_hypothesis=session.top_hypothesis.root_cause_description if session.top_hypothesis else None,
            top_confidence=session.top_hypothesis.confidence if session.top_hypothesis else 0.0,
            call_results=call_results,
            recommendations=list(session.recommendations),
            diagnosis=diagnosis,
            call_errors=call_errors,
        )

    def generate_for_clarification(
        self,
        session: SessionState,
        match_output: MatchPhenomenaOutput,
    ) -> AgentResponse:
        """为澄清场景生成响应

        Args:
            session: 会话状态
            match_output: 现象匹配输出

        Returns:
            AgentResponse
        """
        # 找出需要澄清的项
        clarifications = [
            interp for interp in match_output.interpreted
            if interp.needs_clarification
        ]

        if not clarifications:
            return self.generate_simple("匹配成功。", session)

        # message 字段保留简单提示，结构化数据放在 details.clarifications 中
        # CLI 会根据 clarifications 字段来渲染
        message = "请根据以下选项进行澄清："

        return AgentResponse(
            message=message,
            details=ResponseDetails(
                status="exploring",
                top_hypothesis=session.top_hypothesis.root_cause_description if session.top_hypothesis else None,
                top_confidence=session.top_hypothesis.confidence if session.top_hypothesis else 0.0,
                call_results=[],
                clarifications=clarifications,
            ),
        )

    def generate_for_diagnose(
        self,
        session: SessionState,
        diagnose_output: DiagnoseOutput,
    ) -> AgentResponse:
        """为诊断结果生成响应

        Args:
            session: 会话状态
            diagnose_output: 诊断输出

        Returns:
            AgentResponse
        """
        response_context = {
            "type": "diagnosis_result",
            "data": {
                "diagnosis_complete": diagnose_output.diagnosis_complete,
                "hypotheses": [
                    {
                        "root_cause_id": h.root_cause_id,
                        "root_cause_description": h.root_cause_description,
                        "confidence": h.confidence,
                    }
                    for h in diagnose_output.hypotheses
                ],
            },
        }

        if diagnose_output.diagnosis:
            response_context["data"]["diagnosis"] = {
                "root_cause_description": diagnose_output.diagnosis.root_cause_description,
                "confidence": diagnose_output.diagnosis.confidence,
                "solution": diagnose_output.diagnosis.solution,
            }

        call_results = [
            CallResult(
                tool="diagnose",
                success=True,
                summary=f"诊断{'完成' if diagnose_output.diagnosis_complete else '进行中'}, "
                        f"假设数: {len(diagnose_output.hypotheses)}",
            )
        ]

        return self.generate(session, response_context, call_results, [])

    async def generate_for_diagnose_stream(
        self,
        session: SessionState,
        diagnose_output: DiagnoseOutput,
    ) -> AsyncGenerator[StreamMessage, None]:
        """流式生成诊断结果响应

        Args:
            session: 会话状态
            diagnose_output: 诊断输出

        Yields:
            StreamMessage: 流式消息
        """
        response_context = {
            "type": "diagnosis_result",
            "data": {
                "diagnosis_complete": diagnose_output.diagnosis_complete,
                "hypotheses": [
                    {
                        "root_cause_id": h.root_cause_id,
                        "root_cause_description": h.root_cause_description,
                        "confidence": h.confidence,
                    }
                    for h in diagnose_output.hypotheses
                ],
            },
        }

        if diagnose_output.diagnosis:
            response_context["data"]["diagnosis"] = {
                "root_cause_description": diagnose_output.diagnosis.root_cause_description,
                "confidence": diagnose_output.diagnosis.confidence,
                "solution": diagnose_output.diagnosis.solution,
            }

        call_results = [
            CallResult(
                tool="diagnose",
                success=True,
                summary=f"诊断{'完成' if diagnose_output.diagnosis_complete else '进行中'}, "
                        f"假设数: {len(diagnose_output.hypotheses)}",
            )
        ]

        async for msg in self.generate_stream(session, response_context, call_results, []):
            yield msg

    async def generate_for_clarification_stream(
        self,
        session: SessionState,
        match_output: MatchPhenomenaOutput,
    ) -> AsyncGenerator[StreamMessage, None]:
        """流式生成澄清响应

        澄清场景不需要 LLM 调用，直接返回结构化数据。

        Args:
            session: 会话状态
            match_output: 现象匹配输出

        Yields:
            StreamMessage: 流式消息（直接 FINAL）
        """
        # 找出需要澄清的项
        clarifications = [
            interp for interp in match_output.interpreted
            if interp.needs_clarification
        ]

        if not clarifications:
            # 无需澄清，直接返回成功消息
            yield StreamMessage(
                type=StreamMessageType.FINAL,
                content="匹配成功。",
                data=ResponseDetails(
                    status="exploring" if not session.hypotheses else "narrowing",
                    top_hypothesis=session.top_hypothesis.root_cause_description if session.top_hypothesis else None,
                    top_confidence=session.top_hypothesis.confidence if session.top_hypothesis else 0.0,
                    call_results=[],
                ).model_dump(),
            )
            return

        # 需要澄清，返回结构化数据
        message = "请根据以下选项进行澄清："
        details = ResponseDetails(
            status="exploring",
            top_hypothesis=session.top_hypothesis.root_cause_description if session.top_hypothesis else None,
            top_confidence=session.top_hypothesis.confidence if session.top_hypothesis else 0.0,
            call_results=[],
            clarifications=clarifications,
        )

        yield StreamMessage(
            type=StreamMessageType.FINAL,
            content=message,
            data=details.model_dump(),
        )
