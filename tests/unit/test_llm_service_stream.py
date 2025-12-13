"""LLMService 流式方法单元测试"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from dbdiag.services.llm_service import LLMService


class MockStreamChunk:
    """模拟 OpenAI 流式响应的 chunk"""

    def __init__(self, content: str):
        self.choices = [MagicMock()]
        self.choices[0].delta.content = content


class MockAsyncStream:
    """模拟异步流"""

    def __init__(self, chunks: list):
        self.chunks = chunks
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.chunks):
            raise StopAsyncIteration
        chunk = self.chunks[self.index]
        self.index += 1
        return MockStreamChunk(chunk)


@pytest.fixture
def mock_config():
    """创建 mock 配置"""
    config = Mock()
    config.llm.api_key = "test-key"
    config.llm.api_base = "http://test.com"
    config.llm.model = "test-model"
    config.llm.temperature = 0.7
    config.llm.max_tokens = 1000
    config.llm.system_prompt = ""
    config.llm.timeout = 30
    config.llm.max_retries = 3
    config.llm.retry_delay = 0.01  # 测试用短延迟
    return config


@pytest.fixture
def llm_service(mock_config):
    """创建 LLMService 实例"""
    return LLMService(mock_config)


class TestLLMServiceStream:
    """LLMService 流式方法测试"""

    @pytest.mark.asyncio
    async def test_generate_stream_basic(self, llm_service):
        """测试：基本流式生成"""
        chunks = ["Hello", " ", "World"]

        with patch.object(
            llm_service, "_async_client", new_callable=Mock
        ) as mock_client:
            mock_client.chat.completions.create = AsyncMock(
                return_value=MockAsyncStream(chunks)
            )

            result = []
            async for chunk in llm_service.generate_stream("test prompt"):
                result.append(chunk)

            assert "".join(result) == "Hello World"

    @pytest.mark.asyncio
    async def test_generate_stream_with_think_tags(self, llm_service):
        """测试：流式生成过滤 <think> 标签"""
        chunks = ["Hello", " <think>", "思考中", "</think>", " World"]

        with patch.object(
            llm_service, "_async_client", new_callable=Mock
        ) as mock_client:
            mock_client.chat.completions.create = AsyncMock(
                return_value=MockAsyncStream(chunks)
            )

            result = []
            async for chunk in llm_service.generate_stream("test prompt"):
                result.append(chunk)

            assert "".join(result) == "Hello  World"

    @pytest.mark.asyncio
    async def test_generate_stream_think_tag_across_chunks(self, llm_service):
        """测试：<think> 标签跨 chunk"""
        chunks = ["Hello <thi", "nk>内部</thi", "nk> World"]

        with patch.object(
            llm_service, "_async_client", new_callable=Mock
        ) as mock_client:
            mock_client.chat.completions.create = AsyncMock(
                return_value=MockAsyncStream(chunks)
            )

            result = []
            async for chunk in llm_service.generate_stream("test prompt"):
                result.append(chunk)

            assert "".join(result) == "Hello  World"

    @pytest.mark.asyncio
    async def test_generate_stream_with_system_prompt(self, llm_service):
        """测试：流式生成带 system prompt"""
        chunks = ["Response"]

        with patch.object(
            llm_service, "_async_client", new_callable=Mock
        ) as mock_client:
            mock_client.chat.completions.create = AsyncMock(
                return_value=MockAsyncStream(chunks)
            )

            result = []
            async for chunk in llm_service.generate_stream(
                "test prompt",
                system_prompt="You are helpful.",
            ):
                result.append(chunk)

            # 验证 create 被调用时包含 system prompt
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs["messages"]
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "You are helpful."

    @pytest.mark.asyncio
    async def test_generate_stream_empty_chunks(self, llm_service):
        """测试：空 chunk 被跳过"""
        chunks = ["Hello", "", None, " World"]

        class MockStreamWithEmptyChunks:
            def __init__(self):
                self.chunks = chunks
                self.index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.index >= len(self.chunks):
                    raise StopAsyncIteration
                chunk = self.chunks[self.index]
                self.index += 1
                mock_chunk = MagicMock()
                mock_chunk.choices = [MagicMock()]
                mock_chunk.choices[0].delta.content = chunk
                return mock_chunk

        with patch.object(
            llm_service, "_async_client", new_callable=Mock
        ) as mock_client:
            mock_client.chat.completions.create = AsyncMock(
                return_value=MockStreamWithEmptyChunks()
            )

            result = []
            async for chunk in llm_service.generate_stream("test prompt"):
                result.append(chunk)

            assert "".join(result) == "Hello World"

    @pytest.mark.asyncio
    async def test_async_client_lazy_init(self, mock_config):
        """测试：异步客户端延迟初始化"""
        with patch("dbdiag.services.llm_service.AsyncOpenAI") as MockAsyncOpenAI:
            service = LLMService(mock_config)

            # 初始时 _async_client 为 None
            assert service._async_client is None

            # 访问 async_client 属性时才初始化
            _ = service.async_client

            MockAsyncOpenAI.assert_called_once_with(
                api_key="test-key",
                base_url="http://test.com",
            )
            assert service._async_client is not None

    @pytest.mark.asyncio
    async def test_generate_stream_retry_on_timeout(self, llm_service):
        """测试：超时后重试"""
        from openai import APITimeoutError

        chunks = ["Success"]
        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise APITimeoutError(request=Mock())
            return MockAsyncStream(chunks)

        with patch.object(
            llm_service, "_async_client", new_callable=Mock
        ) as mock_client:
            mock_client.chat.completions.create = mock_create

            # 设置较短的重试延迟
            llm_service.retry_delay = 0.01

            result = []
            async for chunk in llm_service.generate_stream("test prompt"):
                result.append(chunk)

            assert "".join(result) == "Success"
            assert call_count == 2  # 第一次失败，第二次成功

    @pytest.mark.asyncio
    async def test_generate_stream_retry_exhausted(self, llm_service):
        """测试：重试耗尽后抛出异常"""
        from openai import APITimeoutError

        async def mock_create(*args, **kwargs):
            raise APITimeoutError(request=Mock())

        with patch.object(
            llm_service, "_async_client", new_callable=Mock
        ) as mock_client:
            mock_client.chat.completions.create = mock_create

            # 设置较短的重试延迟
            llm_service.retry_delay = 0.01
            llm_service.max_retries = 2

            with pytest.raises(APITimeoutError):
                result = []
                async for chunk in llm_service.generate_stream("test prompt"):
                    result.append(chunk)

    @pytest.mark.asyncio
    async def test_generate_stream_non_retryable_error(self, llm_service):
        """测试：非重试类型的错误直接抛出"""
        async def mock_create(*args, **kwargs):
            raise ValueError("Invalid input")

        with patch.object(
            llm_service, "_async_client", new_callable=Mock
        ) as mock_client:
            mock_client.chat.completions.create = mock_create

            with pytest.raises(ValueError, match="Invalid input"):
                result = []
                async for chunk in llm_service.generate_stream("test prompt"):
                    result.append(chunk)
