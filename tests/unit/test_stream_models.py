"""ThinkTagFilter 和 StreamMessage 单元测试"""

import pytest
from dbdiag.services.llm_service import ThinkTagFilter
from dbdiag.core.agent.stream_models import (
    StreamMessage,
    StreamMessageType,
)


class TestThinkTagFilter:
    """ThinkTagFilter 测试"""

    def test_no_think_tag(self):
        """测试：无 think 标签，原样输出"""
        f = ThinkTagFilter()
        result = f.process("Hello World")
        assert result == "Hello World"

    def test_complete_think_tag(self):
        """测试：完整 think 标签，过滤内部内容"""
        f = ThinkTagFilter()
        result = f.process("Hello <think>内部思考</think> World")
        assert result == "Hello  World"

    def test_multiple_think_tags(self):
        """测试：多个 think 标签"""
        f = ThinkTagFilter()
        result = f.process("A<think>1</think>B<think>2</think>C")
        assert result == "ABC"

    def test_nested_angle_brackets(self):
        """测试：非 think 的尖括号标签，保留"""
        f = ThinkTagFilter()
        result = f.process("Hello <div>test</div> World")
        assert result == "Hello <div>test</div> World"

    def test_partial_open_tag(self):
        """测试：跨 chunk 的 <think> 开始标签"""
        f = ThinkTagFilter()
        r1 = f.process("Hello <thi")
        r2 = f.process("nk>内部</think> World")
        assert r1 == "Hello "
        assert r2 == " World"

    def test_partial_close_tag(self):
        """测试：跨 chunk 的 </think> 结束标签"""
        f = ThinkTagFilter()
        r1 = f.process("Hello <think>内部</thi")
        r2 = f.process("nk> World")
        assert r1 == "Hello "
        assert r2 == " World"

    def test_incomplete_open_tag_at_end(self):
        """测试：流结束时未完成的 < 开始"""
        f = ThinkTagFilter()
        r1 = f.process("Hello <thi")
        remaining = f.flush()
        assert r1 == "Hello "
        assert remaining == "<thi"

    def test_flush_in_normal_state(self):
        """测试：正常状态下 flush 返回空"""
        f = ThinkTagFilter()
        f.process("Hello World")
        remaining = f.flush()
        assert remaining == ""

    def test_flush_in_think_state(self):
        """测试：在 think 块内 flush 返回空"""
        f = ThinkTagFilter()
        f.process("Hello <think>内部")
        remaining = f.flush()
        assert remaining == ""

    def test_single_char_at_a_time(self):
        """测试：单字符输入"""
        f = ThinkTagFilter()
        text = "A<think>B</think>C"
        result = ""
        for char in text:
            result += f.process(char)
        assert result == "AC"

    def test_empty_think_tag(self):
        """测试：空 think 标签"""
        f = ThinkTagFilter()
        result = f.process("Hello <think></think> World")
        assert result == "Hello  World"

    def test_think_tag_at_start(self):
        """测试：think 标签在开头"""
        f = ThinkTagFilter()
        result = f.process("<think>思考</think>Hello")
        assert result == "Hello"

    def test_think_tag_at_end(self):
        """测试：think 标签在结尾"""
        f = ThinkTagFilter()
        result = f.process("Hello<think>思考</think>")
        assert result == "Hello"

    def test_reset(self):
        """测试：reset 重置状态"""
        f = ThinkTagFilter()
        f.process("Hello <think>内部")
        f.reset()
        result = f.process("World")
        assert result == "World"

    def test_less_than_not_think(self):
        """测试：< 后不是 think"""
        f = ThinkTagFilter()
        result = f.process("a < b > c")
        assert result == "a < b > c"

    def test_think_with_newlines(self):
        """测试：think 块内含换行"""
        f = ThinkTagFilter()
        result = f.process("Hello <think>line1\nline2\nline3</think> World")
        assert result == "Hello  World"


class TestStreamMessage:
    """StreamMessage 测试"""

    def test_progress_message(self):
        """测试：创建进度消息"""
        msg = StreamMessage(
            type=StreamMessageType.PROGRESS,
            content="Processing...",
        )
        assert msg.type == StreamMessageType.PROGRESS
        assert msg.content == "Processing..."
        assert msg.data is None

    def test_chunk_message(self):
        """测试：创建 chunk 消息"""
        msg = StreamMessage(
            type=StreamMessageType.CHUNK,
            content="Hello",
        )
        assert msg.type == StreamMessageType.CHUNK
        assert msg.content == "Hello"

    def test_final_message(self):
        """测试：创建 final 消息"""
        msg = StreamMessage(
            type=StreamMessageType.FINAL,
            content="Complete response",
            data={"status": "ok"},
        )
        assert msg.type == StreamMessageType.FINAL
        assert msg.content == "Complete response"
        assert msg.data == {"status": "ok"}

    def test_error_message(self):
        """测试：创建 error 消息"""
        msg = StreamMessage(
            type=StreamMessageType.ERROR,
            content="Something went wrong",
        )
        assert msg.type == StreamMessageType.ERROR
        assert msg.content == "Something went wrong"

    def test_message_serialization(self):
        """测试：消息序列化"""
        msg = StreamMessage(
            type=StreamMessageType.CHUNK,
            content="test",
        )
        data = msg.model_dump()
        assert data["type"] == "chunk"
        assert data["content"] == "test"
