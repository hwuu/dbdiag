"""Responder 流式方法单元测试"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock

from dbdiag.core.agent.responder import Responder
from dbdiag.core.agent.stream_models import StreamMessage, StreamMessageType
from dbdiag.core.agent.models import (
    SessionState,
    CallResult,
    CallError,
    DiagnoseOutput,
    Hypothesis,
    Diagnosis,
    MatchPhenomenaOutput,
    InterpretedObservation,
    ClarificationOption,
    MatchedPhenomenon,
)


@pytest.fixture
def mock_llm_service():
    """创建 mock LLM 服务"""
    service = Mock()
    return service


@pytest.fixture
def responder(mock_llm_service):
    """创建 Responder 实例"""
    return Responder(mock_llm_service)


@pytest.fixture
def session():
    """创建测试会话"""
    return SessionState(session_id="test-session")


class TestResponderStream:
    """Responder 流式方法测试"""

    @pytest.mark.asyncio
    async def test_generate_stream_basic(self, responder, session, mock_llm_service):
        """测试：基本流式生成"""
        # Mock LLM 流式响应
        async def mock_stream(*args, **kwargs):
            yield "Hello"
            yield " "
            yield "World"

        mock_llm_service.generate_stream = mock_stream

        response_context = {"type": "diagnosis_result", "data": {}}
        call_results = [CallResult(tool="diagnose", success=True, summary="OK")]

        messages = []
        async for msg in responder.generate_stream(
            session, response_context, call_results, []
        ):
            messages.append(msg)

        # 检查消息序列：1 PROGRESS + 3 CHUNK + 1 FINAL
        assert len(messages) == 5
        assert messages[0].type == StreamMessageType.PROGRESS
        assert messages[0].content == "生成响应中..."
        assert messages[1].type == StreamMessageType.CHUNK
        assert messages[1].content == "Hello"
        assert messages[2].type == StreamMessageType.CHUNK
        assert messages[2].content == " "
        assert messages[3].type == StreamMessageType.CHUNK
        assert messages[3].content == "World"
        assert messages[4].type == StreamMessageType.FINAL
        assert messages[4].content == "Hello World"
        assert messages[4].data is not None

    @pytest.mark.asyncio
    async def test_generate_stream_with_errors(self, responder, session, mock_llm_service):
        """测试：带错误的流式生成"""
        async def mock_stream(*args, **kwargs):
            yield "Response with errors"

        mock_llm_service.generate_stream = mock_stream

        response_context = {"type": "error", "data": {"message": "Something failed"}}
        call_errors = [CallError(tool="match_phenomena", error_message="No match")]

        messages = []
        async for msg in responder.generate_stream(
            session, response_context, [], call_errors
        ):
            messages.append(msg)

        # 应该包含错误信息在 details 中
        final_msg = messages[-1]
        assert final_msg.type == StreamMessageType.FINAL
        assert final_msg.data["call_errors"] is not None


class TestResponderDiagnoseStream:
    """Responder 诊断流式测试"""

    @pytest.mark.asyncio
    async def test_generate_for_diagnose_stream_in_progress(
        self, responder, session, mock_llm_service
    ):
        """测试：诊断进行中流式输出"""
        async def mock_stream(*args, **kwargs):
            yield "诊断进行中..."

        mock_llm_service.generate_stream = mock_stream

        diagnose_output = DiagnoseOutput(
            diagnosis_complete=False,
            hypotheses=[
                Hypothesis(
                    root_cause_id="RC-001",
                    root_cause_description="测试根因",
                    confidence=0.7,
                    supporting_facts=[],
                )
            ],
            diagnosis=None,
        )

        messages = []
        async for msg in responder.generate_for_diagnose_stream(session, diagnose_output):
            messages.append(msg)

        # 验证消息序列
        assert len(messages) >= 2  # 至少 PROGRESS + FINAL
        assert messages[0].type == StreamMessageType.PROGRESS

        final_msg = messages[-1]
        assert final_msg.type == StreamMessageType.FINAL

    @pytest.mark.asyncio
    async def test_generate_for_diagnose_stream_complete(
        self, responder, session, mock_llm_service
    ):
        """测试：诊断完成流式输出"""
        async def mock_stream(*args, **kwargs):
            yield "诊断完成！根因是..."

        mock_llm_service.generate_stream = mock_stream

        diagnose_output = DiagnoseOutput(
            diagnosis_complete=True,
            hypotheses=[
                Hypothesis(
                    root_cause_id="RC-001",
                    root_cause_description="慢查询导致锁等待",
                    confidence=0.95,
                    supporting_facts=[],
                )
            ],
            diagnosis=Diagnosis(
                root_cause_id="RC-001",
                root_cause_description="慢查询导致锁等待",
                confidence=0.95,
                solution="优化查询语句",
                supporting_facts=[],
            ),
        )

        messages = []
        async for msg in responder.generate_for_diagnose_stream(session, diagnose_output):
            messages.append(msg)

        final_msg = messages[-1]
        assert final_msg.type == StreamMessageType.FINAL


class TestResponderClarificationStream:
    """Responder 澄清流式测试"""

    @pytest.mark.asyncio
    async def test_generate_for_clarification_stream_no_clarification(
        self, responder, session
    ):
        """测试：无需澄清直接返回"""
        match_output = MatchPhenomenaOutput(
            interpreted=[
                InterpretedObservation(
                    raw_description="查询慢",
                    needs_clarification=False,
                    matched_phenomenon=MatchedPhenomenon(
                        phenomenon_id="P-0001",
                        phenomenon_description="查询响应时间超过阈值",
                        user_observation="查询慢",
                        match_score=0.9,
                    ),
                    clarification_options=[],
                )
            ],
            all_matched=True,
        )

        messages = []
        async for msg in responder.generate_for_clarification_stream(session, match_output):
            messages.append(msg)

        # 无需澄清，直接返回 FINAL
        assert len(messages) == 1
        assert messages[0].type == StreamMessageType.FINAL
        assert messages[0].content == "匹配成功。"

    @pytest.mark.asyncio
    async def test_generate_for_clarification_stream_needs_clarification(
        self, responder, session
    ):
        """测试：需要澄清返回选项"""
        match_output = MatchPhenomenaOutput(
            interpreted=[
                InterpretedObservation(
                    raw_description="性能问题",
                    needs_clarification=True,
                    matched_phenomenon=None,
                    clarification_question="请问您遇到的是哪种性能问题？",
                    clarification_options=[
                        ClarificationOption(
                            phenomenon_id="P-0001",
                            description="CPU 使用率高",
                            observation_method="检查 top 或 htop 输出",
                        ),
                        ClarificationOption(
                            phenomenon_id="P-0002",
                            description="内存不足",
                            observation_method="检查 free -m 输出",
                        ),
                    ],
                )
            ],
            all_matched=False,
        )

        messages = []
        async for msg in responder.generate_for_clarification_stream(session, match_output):
            messages.append(msg)

        # 需要澄清，返回带 clarifications 的 FINAL
        assert len(messages) == 1
        assert messages[0].type == StreamMessageType.FINAL
        assert messages[0].content == "请根据以下选项进行澄清："
        assert messages[0].data is not None
        assert "clarifications" in messages[0].data
        assert len(messages[0].data["clarifications"]) == 1
