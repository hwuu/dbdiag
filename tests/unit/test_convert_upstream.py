"""convert_upstream 单元测试"""
import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import asyncio

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.scripts.convert_upstream import (
    UpstreamConverter,
    convert_upstream_data,
)


class TestUpstreamConverter:
    """UpstreamConverter 测试"""

    def test_convert_direct_mapping_fields(self):
        """测试: 直接映射字段应正确转换"""
        mock_llm = Mock()
        # Mock LLM 返回空 anomalies 和默认 metadata
        mock_llm.generate_simple.side_effect = [
            '[]',  # anomalies
            '{"db_type": "PostgreSQL", "version": "", "module": "unknown", "severity": "medium"}',  # metadata
        ]

        converter = UpstreamConverter(mock_llm, concurrency=1)

        upstream_item = {
            "流程ID": "TICKET-001",
            "问题描述": "查询变慢",
            "问题跟因": "索引膨胀",
            "恢复方法和规避措施": "REINDEX",
            "分析过程": "",
        }

        result = asyncio.run(converter._convert_one(upstream_item))

        assert result is not None
        assert result["ticket_id"] == "TICKET-001"
        assert result["description"] == "查询变慢"
        assert result["root_cause"] == "索引膨胀"
        assert result["solution"] == "REINDEX"

    def test_extract_anomalies_success(self):
        """测试: 成功从分析过程提取 anomalies"""
        mock_llm = Mock()
        mock_llm.generate_simple.return_value = '''[
            {
                "description": "wait_io 占比 65%",
                "observation_method": "SELECT wait_event FROM pg_stat_activity",
                "why_relevant": "IO 等待高"
            }
        ]'''

        converter = UpstreamConverter(mock_llm, concurrency=1)

        result = asyncio.run(converter._extract_anomalies("分析过程文本"))

        assert len(result) == 1
        assert result[0]["description"] == "wait_io 占比 65%"
        assert result[0]["observation_method"] == "SELECT wait_event FROM pg_stat_activity"
        assert result[0]["why_relevant"] == "IO 等待高"

    def test_extract_anomalies_with_markdown_code_block(self):
        """测试: 处理 LLM 返回的 markdown 代码块"""
        mock_llm = Mock()
        mock_llm.generate_simple.return_value = '''```json
[
    {
        "description": "索引膨胀",
        "observation_method": "查看索引大小",
        "why_relevant": "导致 IO 增加"
    }
]
```'''

        converter = UpstreamConverter(mock_llm, concurrency=1)

        result = asyncio.run(converter._extract_anomalies("分析过程"))

        assert len(result) == 1
        assert result[0]["description"] == "索引膨胀"

    def test_extract_anomalies_empty_input(self):
        """测试: 空分析过程返回空列表"""
        mock_llm = Mock()
        converter = UpstreamConverter(mock_llm, concurrency=1)

        result = asyncio.run(converter._extract_anomalies(""))

        assert result == []
        mock_llm.generate_simple.assert_not_called()

    def test_infer_metadata_success(self):
        """测试: 成功推断 metadata"""
        mock_llm = Mock()
        mock_llm.generate_simple.return_value = '''{
            "db_type": "PostgreSQL",
            "version": "14.5",
            "module": "query_optimizer",
            "severity": "high"
        }'''

        converter = UpstreamConverter(mock_llm, concurrency=1)

        result = asyncio.run(converter._infer_metadata(
            "查询变慢",
            "索引膨胀",
            "REINDEX",
        ))

        assert result["db_type"] == "PostgreSQL"
        assert result["version"] == "14.5"
        assert result["module"] == "query_optimizer"
        assert result["severity"] == "high"

    def test_infer_metadata_default_on_error(self):
        """测试: LLM 错误时返回默认 metadata"""
        mock_llm = Mock()
        mock_llm.generate_simple.side_effect = Exception("LLM error")

        converter = UpstreamConverter(mock_llm, concurrency=1)

        result = asyncio.run(converter._infer_metadata(
            "查询变慢",
            "索引膨胀",
            "REINDEX",
        ))

        assert result["db_type"] == "PostgreSQL"
        assert result["module"] == "unknown"
        assert result["severity"] == "medium"

    def test_convert_one_skip_empty_ticket_id(self):
        """测试: 空 ticket_id 应跳过"""
        mock_llm = Mock()
        converter = UpstreamConverter(mock_llm, concurrency=1)

        upstream_item = {
            "流程ID": "",
            "问题描述": "查询变慢",
        }

        result = asyncio.run(converter._convert_one(upstream_item))

        assert result is None

    def test_concurrency_limit(self):
        """测试: 并发数应被限制在 1-16"""
        mock_llm = Mock()

        converter_low = UpstreamConverter(mock_llm, concurrency=0)
        assert converter_low.concurrency == 1

        converter_high = UpstreamConverter(mock_llm, concurrency=100)
        assert converter_high.concurrency == 16

        converter_normal = UpstreamConverter(mock_llm, concurrency=8)
        assert converter_normal.concurrency == 8


class TestConvertUpstreamData:
    """convert_upstream_data 集成测试"""

    def test_convert_upstream_data_success(self):
        """测试: 成功转换上游数据文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 准备上游数据
            upstream_data = [
                {
                    "流程ID": "T-001",
                    "问题描述": "查询变慢",
                    "问题跟因": "索引膨胀",
                    "恢复方法和规避措施": "REINDEX",
                    "分析过程": "发现 wait_io 高",
                }
            ]
            upstream_path = os.path.join(tmpdir, "upstream.json")
            with open(upstream_path, "w", encoding="utf-8") as f:
                json.dump(upstream_data, f, ensure_ascii=False)

            output_path = os.path.join(tmpdir, "output.json")

            # Mock LLM
            with patch('dbdiag.scripts.convert_upstream.LLMService') as MockLLM:
                mock_llm = Mock()
                mock_llm.generate_simple.side_effect = [
                    '[{"description": "wait_io 高", "observation_method": "", "why_relevant": ""}]',
                    '{"db_type": "PostgreSQL", "version": "", "module": "query_optimizer", "severity": "medium"}',
                ]
                MockLLM.return_value = mock_llm

                convert_upstream_data(upstream_path, output_path, concurrency=1)

            # 验证输出
            assert os.path.exists(output_path)
            with open(output_path, "r", encoding="utf-8") as f:
                result = json.load(f)

            assert len(result) == 1
            assert result[0]["ticket_id"] == "T-001"
            assert result[0]["description"] == "查询变慢"
            assert result[0]["root_cause"] == "索引膨胀"
            assert result[0]["solution"] == "REINDEX"
            assert len(result[0]["anomalies"]) == 1

    def test_convert_upstream_data_invalid_format(self):
        """测试: 非数组格式应报错"""
        with tempfile.TemporaryDirectory() as tmpdir:
            upstream_path = os.path.join(tmpdir, "upstream.json")
            with open(upstream_path, "w", encoding="utf-8") as f:
                json.dump({"key": "value"}, f)

            output_path = os.path.join(tmpdir, "output.json")

            with patch('dbdiag.scripts.convert_upstream.LLMService'):
                with pytest.raises(ValueError, match="必须是 JSON 数组"):
                    convert_upstream_data(upstream_path, output_path, concurrency=1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
