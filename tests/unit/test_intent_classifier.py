"""IntentClassifier 单元测试"""

import pytest
import json
from unittest.mock import Mock, MagicMock

from dbdiag.core.intent.models import UserIntent, IntentType, QueryType
from dbdiag.core.intent.classifier import IntentClassifier


class TestUserIntent:
    """UserIntent 数据模型测试"""

    def test_default_values(self):
        """默认值测试"""
        intent = UserIntent()
        assert intent.intent_type == IntentType.FEEDBACK
        assert intent.confirmations == []
        assert intent.denials == []
        assert intent.new_observations == []
        assert intent.query_type is None
        assert intent.confidence == 1.0

    def test_has_feedback(self):
        """has_feedback 属性测试"""
        # 无反馈
        intent = UserIntent()
        assert intent.has_feedback is False

        # 有确认
        intent = UserIntent(confirmations=["P-0001"])
        assert intent.has_feedback is True

        # 有否认
        intent = UserIntent(denials=["P-0002"])
        assert intent.has_feedback is True

        # 有新观察
        intent = UserIntent(new_observations=["IO 正常"])
        assert intent.has_feedback is True

    def test_has_query(self):
        """has_query 属性测试"""
        intent = UserIntent()
        assert intent.has_query is False

        intent = UserIntent(query_type=QueryType.PROGRESS)
        assert intent.has_query is True

    def test_is_empty(self):
        """is_empty 属性测试"""
        intent = UserIntent()
        assert intent.is_empty is True

        intent = UserIntent(new_observations=["test"])
        assert intent.is_empty is False

        intent = UserIntent(query_type=QueryType.CONCLUSION)
        assert intent.is_empty is False


class TestIntentClassifier:
    """IntentClassifier 测试"""

    def _create_classifier(self, llm_response: str) -> IntentClassifier:
        """创建 mock 分类器"""
        mock_llm = Mock()
        mock_llm.generate.return_value = llm_response
        return IntentClassifier(mock_llm)

    # ==================== I-101 Feedback 测试 ====================

    def test_feedback_simple_confirm(self):
        """简单确认测试"""
        llm_response = json.dumps({
            "intent_type": "feedback",
            "confirmations": ["P-0001"],
            "denials": [],
            "new_observations": [],
            "query_type": None,
            "confidence": 0.95
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "1确认",
            recommended_phenomenon_ids=["P-0001", "P-0002"],
        )

        assert intent.intent_type == IntentType.FEEDBACK
        assert intent.confirmations == ["P-0001"]
        assert intent.denials == []
        assert intent.has_feedback is True
        assert intent.has_query is False

    def test_feedback_batch_confirm_deny(self):
        """批量确认否定测试"""
        llm_response = json.dumps({
            "intent_type": "feedback",
            "confirmations": ["P-0001", "P-0003"],
            "denials": ["P-0002"],
            "new_observations": [],
            "query_type": None,
            "confidence": 0.92
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "1确认 2否定 3确认",
            recommended_phenomenon_ids=["P-0001", "P-0002", "P-0003"],
        )

        assert intent.intent_type == IntentType.FEEDBACK
        assert intent.confirmations == ["P-0001", "P-0003"]
        assert intent.denials == ["P-0002"]

    def test_feedback_natural_language(self):
        """自然语言反馈测试"""
        llm_response = json.dumps({
            "intent_type": "feedback",
            "confirmations": [],
            "denials": [],
            "new_observations": ["IO 正常", "CPU 使用率 95%"],
            "query_type": None,
            "confidence": 0.88
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "IO 正常，CPU 使用率 95%",
            recommended_phenomenon_ids=[],
        )

        assert intent.intent_type == IntentType.FEEDBACK
        assert intent.new_observations == ["IO 正常", "CPU 使用率 95%"]

    def test_feedback_multiple_observations_i303(self):
        """多个观察测试 (I-303)"""
        llm_response = json.dumps({
            "intent_type": "feedback",
            "confirmations": [],
            "denials": [],
            "new_observations": ["IO 正常", "CPU 很高", "内存快满了"],
            "query_type": None,
            "confidence": 0.90
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "IO 正常，CPU 很高，内存也快满了",
            recommended_phenomenon_ids=[],
        )

        assert intent.intent_type == IntentType.FEEDBACK
        assert len(intent.new_observations) == 3
        assert "IO 正常" in intent.new_observations
        assert "CPU 很高" in intent.new_observations
        assert "内存快满了" in intent.new_observations

    # ==================== I-102 Query 测试 ====================

    def test_query_progress(self):
        """查询进展测试"""
        llm_response = json.dumps({
            "intent_type": "query",
            "confirmations": [],
            "denials": [],
            "new_observations": [],
            "query_type": "progress",
            "confidence": 0.95
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "现在都检查了什么？",
            recommended_phenomenon_ids=["P-0001"],
        )

        assert intent.intent_type == IntentType.QUERY
        assert intent.query_type == QueryType.PROGRESS
        assert intent.has_feedback is False
        assert intent.has_query is True

    def test_query_conclusion(self):
        """查询结论测试"""
        llm_response = json.dumps({
            "intent_type": "query",
            "confirmations": [],
            "denials": [],
            "new_observations": [],
            "query_type": "conclusion",
            "confidence": 0.93
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "根据现有信息，有什么结论？",
            recommended_phenomenon_ids=["P-0001"],
        )

        assert intent.intent_type == IntentType.QUERY
        assert intent.query_type == QueryType.CONCLUSION

    def test_query_hypotheses(self):
        """查询假设测试"""
        llm_response = json.dumps({
            "intent_type": "query",
            "confirmations": [],
            "denials": [],
            "new_observations": [],
            "query_type": "hypotheses",
            "confidence": 0.91
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "还有哪些可能的原因？",
            recommended_phenomenon_ids=["P-0001"],
        )

        assert intent.intent_type == IntentType.QUERY
        assert intent.query_type == QueryType.HYPOTHESES

    # ==================== Mixed 测试 ====================

    def test_mixed_feedback_and_query(self):
        """混合意图测试"""
        llm_response = json.dumps({
            "intent_type": "mixed",
            "confirmations": [],
            "denials": [],
            "new_observations": ["IO 正常"],
            "query_type": "conclusion",
            "confidence": 0.89
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "IO 正常，现在有什么结论？",
            recommended_phenomenon_ids=["P-0001"],
        )

        assert intent.intent_type == IntentType.MIXED
        assert intent.new_observations == ["IO 正常"]
        assert intent.query_type == QueryType.CONCLUSION
        assert intent.has_feedback is True
        assert intent.has_query is True

    def test_mixed_confirm_and_query(self):
        """确认+查询混合测试"""
        llm_response = json.dumps({
            "intent_type": "mixed",
            "confirmations": ["P-0001"],
            "denials": [],
            "new_observations": [],
            "query_type": "progress",
            "confidence": 0.87
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "1确认，顺便问一下检查了多少了？",
            recommended_phenomenon_ids=["P-0001", "P-0002"],
        )

        assert intent.intent_type == IntentType.MIXED
        assert intent.confirmations == ["P-0001"]
        assert intent.query_type == QueryType.PROGRESS

    # ==================== 边界情况测试 ====================

    def test_empty_input(self):
        """空输入测试"""
        classifier = self._create_classifier("")
        intent = classifier.classify("")

        assert intent.is_empty is True

    def test_llm_failure_fallback(self):
        """LLM 失败兜底测试"""
        mock_llm = Mock()
        mock_llm.generate.side_effect = Exception("LLM Error")
        classifier = IntentClassifier(mock_llm)

        intent = classifier.classify(
            "IO 正常",
            recommended_phenomenon_ids=["P-0001"],
        )

        # 兜底：作为新观察
        assert intent.intent_type == IntentType.FEEDBACK
        assert intent.new_observations == ["IO 正常"]
        assert intent.confidence == 0.5

    def test_invalid_json_fallback(self):
        """无效 JSON 兜底测试"""
        classifier = self._create_classifier("这不是 JSON")

        intent = classifier.classify(
            "IO 正常",
            recommended_phenomenon_ids=["P-0001"],
        )

        # 兜底：作为新观察
        assert intent.intent_type == IntentType.FEEDBACK
        assert intent.confidence < 1.0

    def test_invalid_phenomenon_id_filtered(self):
        """无效现象 ID 过滤测试"""
        llm_response = json.dumps({
            "intent_type": "feedback",
            "confirmations": ["P-0001", "P-9999"],  # P-9999 不在推荐列表中
            "denials": [],
            "new_observations": [],
            "query_type": None,
            "confidence": 0.90
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "1确认",
            recommended_phenomenon_ids=["P-0001", "P-0002"],
        )

        # P-9999 应该被过滤
        assert intent.confirmations == ["P-0001"]

    def test_markdown_code_block_handling(self):
        """Markdown 代码块处理测试"""
        llm_response = """```json
{
  "intent_type": "feedback",
  "confirmations": ["P-0001"],
  "denials": [],
  "new_observations": [],
  "query_type": null,
  "confidence": 0.95
}
```"""
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "1确认",
            recommended_phenomenon_ids=["P-0001"],
        )

        assert intent.confirmations == ["P-0001"]

    def test_no_recommended_phenomena(self):
        """无推荐现象时的测试"""
        llm_response = json.dumps({
            "intent_type": "feedback",
            "confirmations": [],
            "denials": [],
            "new_observations": ["查询变慢了"],
            "query_type": None,
            "confidence": 0.92
        })
        classifier = self._create_classifier(llm_response)

        intent = classifier.classify(
            "查询变慢了",
            recommended_phenomenon_ids=[],
        )

        assert intent.new_observations == ["查询变慢了"]


class TestValidatePhenomenonId:
    """现象 ID 验证测试"""

    def test_validate_full_id(self):
        """完整 ID 验证"""
        mock_llm = Mock()
        classifier = IntentClassifier(mock_llm)

        assert classifier._validate_phenomenon_id("P-0001", ["P-0001", "P-0002"]) is True
        assert classifier._validate_phenomenon_id("P-9999", ["P-0001", "P-0002"]) is False

    def test_validate_numeric_index(self):
        """数字索引验证"""
        mock_llm = Mock()
        classifier = IntentClassifier(mock_llm)

        # "1" -> P-0001, "2" -> P-0002
        assert classifier._validate_phenomenon_id("1", ["P-0001", "P-0002"]) is True
        assert classifier._validate_phenomenon_id("2", ["P-0001", "P-0002"]) is True
        assert classifier._validate_phenomenon_id("3", ["P-0001", "P-0002"]) is False
        assert classifier._validate_phenomenon_id("0", ["P-0001", "P-0002"]) is False

    def test_validate_empty(self):
        """空值验证"""
        mock_llm = Mock()
        classifier = IntentClassifier(mock_llm)

        assert classifier._validate_phenomenon_id("", ["P-0001"]) is False
        assert classifier._validate_phenomenon_id(None, ["P-0001"]) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
