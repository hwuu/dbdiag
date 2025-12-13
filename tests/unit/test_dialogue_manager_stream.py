"""AgentDialogueManager 流式方法单元测试"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from dbdiag.core.agent.dialogue_manager import AgentDialogueManager
from dbdiag.core.agent.stream_models import StreamMessage, StreamMessageType
from dbdiag.core.agent.models import (
    SessionState,
    AgentDecision,
    DiagnoseOutput,
    Hypothesis,
    MatchPhenomenaOutput,
    InterpretedObservation,
    MatchedPhenomenon,
)


@pytest.fixture
def mock_llm_service():
    """创建 mock LLM 服务"""
    service = Mock()
    service.generate = Mock(return_value="LLM 响应")
    return service


@pytest.fixture
def mock_embedding_service():
    """创建 mock 向量服务"""
    service = Mock()
    return service


@pytest.fixture
def dialogue_manager(mock_llm_service, mock_embedding_service, tmp_path):
    """创建 DialogueManager 实例"""
    db_path = str(tmp_path / "test.db")
    return AgentDialogueManager(
        db_path=db_path,
        llm_service=mock_llm_service,
        embedding_service=mock_embedding_service,
    )


class TestDialogueManagerProcessStream:
    """DialogueManager process_stream 测试"""

    @pytest.mark.asyncio
    async def test_process_stream_session_not_found(self, dialogue_manager):
        """测试：会话不存在"""
        messages = []
        async for msg in dialogue_manager.process_stream("nonexistent", "hello"):
            messages.append(msg)

        assert len(messages) == 1
        assert messages[0].type == StreamMessageType.FINAL
        assert "不存在" in messages[0].content

    @pytest.mark.asyncio
    async def test_process_stream_basic(self, dialogue_manager, mock_llm_service):
        """测试：基本流式处理"""
        # 创建会话
        session_id = dialogue_manager.create_session("测试问题")

        # Mock Planner 返回 respond 决策
        with patch.object(
            dialogue_manager._planner, "decide"
        ) as mock_decide:
            mock_decide.return_value = AgentDecision(
                decision="respond",
                response_context={"type": "greeting", "data": {}},
            )

            # Mock Responder 流式响应
            async def mock_generate_stream(*args, **kwargs):
                yield StreamMessage(type=StreamMessageType.PROGRESS, content="生成中...")
                yield StreamMessage(type=StreamMessageType.CHUNK, content="Hello")
                yield StreamMessage(type=StreamMessageType.CHUNK, content=" World")
                yield StreamMessage(type=StreamMessageType.FINAL, content="Hello World", data={})

            dialogue_manager._responder.generate_stream = mock_generate_stream

            messages = []
            async for msg in dialogue_manager.process_stream(session_id, "hello"):
                messages.append(msg)

            # 验证消息流
            assert len(messages) >= 3  # 至少有 PROGRESS + CHUNK + FINAL

            # 检查是否包含各种消息类型
            types = [msg.type for msg in messages]
            assert StreamMessageType.PROGRESS in types
            assert StreamMessageType.FINAL in types


class TestDialogueManagerAgentLoopStream:
    """DialogueManager _run_agent_loop_stream 测试"""

    @pytest.mark.asyncio
    async def test_agent_loop_stream_call_then_respond(
        self, dialogue_manager, mock_llm_service
    ):
        """测试：调用工具后响应"""
        session_id = dialogue_manager.create_session("测试问题")
        session = dialogue_manager.get_session(session_id)

        call_count = 0

        def mock_decide(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 第一次调用 diagnose
                return AgentDecision(
                    decision="call",
                    tool="diagnose",
                    tool_input={"confirmed_phenomena": []},
                )
            else:
                # 第二次 respond（不会到达，因为 diagnose 后直接返回）
                return AgentDecision(
                    decision="respond",
                    response_context={"type": "diagnosis_result", "data": {}},
                )

        with patch.object(dialogue_manager._planner, "decide", side_effect=mock_decide):
            # Mock Executor
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
            )
            with patch.object(
                dialogue_manager._executor, "execute"
            ) as mock_execute:
                mock_execute.return_value = (diagnose_output, session, None)

                with patch.object(
                    dialogue_manager._executor, "create_call_result"
                ) as mock_call_result:
                    mock_call_result.return_value = Mock(
                        tool="diagnose", success=True, summary="OK"
                    )

                    with patch.object(
                        dialogue_manager._executor, "format_result_for_planner"
                    ) as mock_format:
                        mock_format.return_value = "诊断结果"

                        # Mock Responder 流式响应
                        async def mock_diagnose_stream(*args, **kwargs):
                            yield StreamMessage(type=StreamMessageType.PROGRESS, content="生成中...")
                            yield StreamMessage(type=StreamMessageType.CHUNK, content="诊断")
                            yield StreamMessage(type=StreamMessageType.FINAL, content="诊断结果", data={})

                        dialogue_manager._responder.generate_for_diagnose_stream = mock_diagnose_stream

                        messages = []
                        async for msg in dialogue_manager._run_agent_loop_stream(
                            session, "用户输入"
                        ):
                            messages.append(msg)

                        # 验证消息流包含进度和最终响应
                        types = [msg.type for msg in messages]
                        assert StreamMessageType.PROGRESS in types
                        assert StreamMessageType.FINAL in types

    @pytest.mark.asyncio
    async def test_agent_loop_stream_invalid_decision(
        self, dialogue_manager, mock_llm_service
    ):
        """测试：无效决策（decision 既不是 call 也不是 respond）"""
        session_id = dialogue_manager.create_session("测试问题")
        session = dialogue_manager.get_session(session_id)

        with patch.object(
            dialogue_manager._planner, "decide"
        ) as mock_decide:
            # 使用 Mock 对象模拟无效决策
            invalid_decision = Mock()
            invalid_decision.decision = "invalid"
            invalid_decision.tool = None
            mock_decide.return_value = invalid_decision

            messages = []
            async for msg in dialogue_manager._run_agent_loop_stream(
                session, "用户输入"
            ):
                messages.append(msg)

            # 无效决策应返回默认响应
            assert len(messages) >= 2
            final_msg = messages[-1]
            assert final_msg.type == StreamMessageType.FINAL
            assert "不太理解" in final_msg.content

    @pytest.mark.asyncio
    async def test_agent_loop_stream_max_iterations(
        self, dialogue_manager, mock_llm_service
    ):
        """测试：达到最大迭代次数"""
        session_id = dialogue_manager.create_session("测试问题")
        session = dialogue_manager.get_session(session_id)

        # 始终返回 call 但工具不触发返回
        with patch.object(
            dialogue_manager._planner, "decide"
        ) as mock_decide:
            mock_decide.return_value = AgentDecision(
                decision="call",
                tool="query_progress",
                tool_input={},
            )

            with patch.object(
                dialogue_manager._executor, "execute"
            ) as mock_execute:
                mock_execute.return_value = (Mock(), session, None)

                with patch.object(
                    dialogue_manager._executor, "create_call_result"
                ) as mock_call_result:
                    mock_call_result.return_value = Mock(
                        tool="query_progress", success=True, summary="OK"
                    )

                    with patch.object(
                        dialogue_manager._executor, "format_result_for_planner"
                    ) as mock_format:
                        mock_format.return_value = "进度"

                        messages = []
                        async for msg in dialogue_manager._run_agent_loop_stream(
                            session, "用户输入"
                        ):
                            messages.append(msg)

                        # 应该在达到最大迭代后结束
                        final_msg = messages[-1]
                        assert final_msg.type == StreamMessageType.FINAL
                        assert "时间过长" in final_msg.content
