"""输入分析器单元测试"""

import pytest
from unittest.mock import MagicMock

from dbdiag.core.gar2.input_analyzer import InputAnalyzer, SymptomDelta


class TestSymptomDelta:
    """SymptomDelta 测试"""

    def test_empty_delta(self):
        delta = SymptomDelta()
        assert delta.is_empty

    def test_non_empty_with_confirmations(self):
        delta = SymptomDelta(confirmations=["P-001"])
        assert not delta.is_empty

    def test_non_empty_with_denials(self):
        delta = SymptomDelta(denials=["P-001"])
        assert not delta.is_empty

    def test_non_empty_with_observations(self):
        delta = SymptomDelta(new_observations=["慢查询"])
        assert not delta.is_empty


class TestInputAnalyzer:
    """InputAnalyzer 测试"""

    def setup_method(self):
        self.analyzer = InputAnalyzer()
        self.recommended_ids = ["P-001", "P-002", "P-003"]

    # ===== 空输入 =====

    def test_empty_input(self):
        delta = self.analyzer.analyze("", self.recommended_ids)
        assert delta.is_empty

    def test_whitespace_input(self):
        delta = self.analyzer.analyze("   ", self.recommended_ids)
        assert delta.is_empty

    # ===== 全局否定 =====

    def test_deny_all(self):
        for keyword in ["全否定", "都否定", "都不是", "全部否定"]:
            delta = self.analyzer.analyze(keyword, self.recommended_ids)
            assert delta.denials == self.recommended_ids
            assert delta.confirmations == []

    # ===== 全局确认 =====

    def test_confirm_all(self):
        for keyword in ["确认", "是", "是的", "看到了"]:
            delta = self.analyzer.analyze(keyword, self.recommended_ids)
            assert delta.confirmations == self.recommended_ids
            assert delta.denials == []

    # ===== 批量格式 =====

    def test_batch_confirm(self):
        delta = self.analyzer.analyze("1确认 2确认 3确认", self.recommended_ids)
        assert delta.confirmations == ["P-001", "P-002", "P-003"]
        assert delta.denials == []

    def test_batch_deny(self):
        delta = self.analyzer.analyze("1否定 2否定", self.recommended_ids)
        assert delta.denials == ["P-001", "P-002"]
        assert delta.confirmations == []

    def test_batch_mixed(self):
        delta = self.analyzer.analyze("1确认 2否定 3确认", self.recommended_ids)
        assert delta.confirmations == ["P-001", "P-003"]
        assert delta.denials == ["P-002"]

    def test_batch_alternative_keywords(self):
        delta = self.analyzer.analyze("1是 2否 3正常", self.recommended_ids)
        assert delta.confirmations == ["P-001", "P-003"]
        assert delta.denials == ["P-002"]

    def test_batch_out_of_range(self):
        delta = self.analyzer.analyze("1确认 5确认", self.recommended_ids)
        # 5 超出范围，应该被忽略
        assert delta.confirmations == ["P-001"]

    def test_batch_with_extra_observation(self):
        delta = self.analyzer.analyze(
            "1确认 2否定，另外我发现慢查询很多",
            self.recommended_ids,
        )
        assert delta.confirmations == ["P-001"]
        assert delta.denials == ["P-002"]
        assert delta.new_observations == ["我发现慢查询很多"]

    def test_batch_with_short_extra_ignored(self):
        # 太短的额外内容应该被忽略
        delta = self.analyzer.analyze("1确认，ok", self.recommended_ids)
        assert delta.confirmations == ["P-001"]
        assert delta.new_observations == []

    # ===== 无推荐现象 =====

    def test_no_recommended_phenomena(self):
        delta = self.analyzer.analyze("wait_io 占比 65%", [])
        assert delta.new_observations == ["wait_io 占比 65%"]
        assert delta.confirmations == []
        assert delta.denials == []

    # ===== 自然语言（无 LLM）=====

    def test_natural_language_without_llm(self):
        # 没有 LLM 服务时，自然语言作为新观察
        delta = self.analyzer.analyze(
            "IO 正常，索引涨了 6 倍",
            self.recommended_ids,
        )
        assert delta.new_observations == ["IO 正常，索引涨了 6 倍"]

    # ===== 自然语言（有 LLM）=====

    def test_natural_language_with_llm(self):
        mock_llm = MagicMock()
        mock_llm.generate_simple.return_value = '''
        {
            "feedback": {
                "P-001": "denied",
                "P-002": "confirmed",
                "P-003": "unknown"
            },
            "new_observations": ["慢查询很多"]
        }
        '''
        analyzer = InputAnalyzer(llm_service=mock_llm)

        delta = analyzer.analyze(
            "IO 正常，索引涨了 6 倍，另外慢查询很多",
            self.recommended_ids,
            {"P-001": "wait_io 高", "P-002": "索引增长", "P-003": "统计信息过期"},
        )

        assert delta.confirmations == ["P-002"]
        assert delta.denials == ["P-001"]
        assert delta.new_observations == ["慢查询很多"]

    def test_llm_returns_markdown_json(self):
        mock_llm = MagicMock()
        mock_llm.generate_simple.return_value = '''```json
        {
            "feedback": {"P-001": "confirmed"},
            "new_observations": []
        }
        ```'''
        analyzer = InputAnalyzer(llm_service=mock_llm)

        delta = analyzer.analyze("IO 很高", self.recommended_ids)
        assert delta.confirmations == ["P-001"]

    def test_llm_failure_fallback(self):
        mock_llm = MagicMock()
        mock_llm.generate_simple.side_effect = Exception("API error")
        analyzer = InputAnalyzer(llm_service=mock_llm)

        delta = analyzer.analyze("IO 正常", self.recommended_ids)
        # 失败时作为新观察
        assert delta.new_observations == ["IO 正常"]
