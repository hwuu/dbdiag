"""llm_service 单元测试"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.services.llm_service import THINK_TAG_PATTERN


class TestThinkTagPattern:
    """<think> 标签正则表达式测试"""

    def test_simple_think_tag(self):
        """测试: 简单的 think 标签"""
        text = "<think>这是思考过程</think>这是实际内容"
        result = THINK_TAG_PATTERN.sub("", text)
        assert result == "这是实际内容"

    def test_multiline_think_tag(self):
        """测试: 多行 think 标签"""
        text = """<think>
第一行思考
第二行思考
第三行思考
</think>
这是实际内容"""
        result = THINK_TAG_PATTERN.sub("", text)
        assert result.strip() == "这是实际内容"

    def test_think_tag_with_special_chars(self):
        """测试: 包含特殊字符的 think 标签"""
        text = "<think>思考 **markdown** `code` 123</think>正文内容"
        result = THINK_TAG_PATTERN.sub("", text)
        assert result == "正文内容"

    def test_no_think_tag(self):
        """测试: 没有 think 标签"""
        text = "这是普通内容，没有思考标签"
        result = THINK_TAG_PATTERN.sub("", text)
        assert result == text

    def test_multiple_think_tags(self):
        """测试: 多个 think 标签"""
        text = "<think>思考1</think>内容1<think>思考2</think>内容2"
        result = THINK_TAG_PATTERN.sub("", text)
        assert result == "内容1内容2"

    def test_empty_think_tag(self):
        """测试: 空的 think 标签"""
        text = "<think></think>内容"
        result = THINK_TAG_PATTERN.sub("", text)
        assert result == "内容"

    def test_think_tag_with_trailing_whitespace(self):
        """测试: think 标签后的空白被清理"""
        text = "<think>思考</think>   \n\n内容"
        result = THINK_TAG_PATTERN.sub("", text)
        # 正则会匹配标签后的空白
        assert result.strip() == "内容"


class TestCleanResponse:
    """_clean_response 方法测试"""

    def test_clean_response_with_think_tag(self):
        """测试: 清理包含 think 标签的响应"""
        from unittest.mock import Mock, patch

        with patch('dbdiag.services.llm_service.openai'):
            from dbdiag.services.llm_service import LLMService

            mock_config = Mock()
            mock_config.llm.api_key = "test"
            mock_config.llm.api_base = "http://test"
            mock_config.llm.model = "test"
            mock_config.llm.temperature = 0.0
            mock_config.llm.max_tokens = 100
            mock_config.llm.system_prompt = ""

            service = LLMService(mock_config)

            result = service._clean_response("<think>思考</think>实际回复")
            assert result == "实际回复"

    def test_clean_response_empty(self):
        """测试: 空响应"""
        from unittest.mock import Mock, patch

        with patch('dbdiag.services.llm_service.openai'):
            from dbdiag.services.llm_service import LLMService

            mock_config = Mock()
            mock_config.llm.api_key = "test"
            mock_config.llm.api_base = "http://test"
            mock_config.llm.model = "test"
            mock_config.llm.temperature = 0.0
            mock_config.llm.max_tokens = 100
            mock_config.llm.system_prompt = ""

            service = LLMService(mock_config)

            assert service._clean_response("") == ""
            assert service._clean_response(None) == ""

    def test_clean_response_strips_whitespace(self):
        """测试: 清理首尾空白"""
        from unittest.mock import Mock, patch

        with patch('dbdiag.services.llm_service.openai'):
            from dbdiag.services.llm_service import LLMService

            mock_config = Mock()
            mock_config.llm.api_key = "test"
            mock_config.llm.api_base = "http://test"
            mock_config.llm.model = "test"
            mock_config.llm.temperature = 0.0
            mock_config.llm.max_tokens = 100
            mock_config.llm.system_prompt = ""

            service = LLMService(mock_config)

            result = service._clean_response("  \n内容\n  ")
            assert result == "内容"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
