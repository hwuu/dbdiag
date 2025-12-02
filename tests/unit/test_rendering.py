"""渲染器单元测试"""
import pytest
from unittest.mock import MagicMock
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.console import Group

from dbdiag.cli.rendering import DiagnosisRenderer
from dbdiag.models.common import Phenomenon


class TestDiagnosisRenderer:
    """DiagnosisRenderer 测试"""

    @pytest.fixture
    def renderer(self):
        """创建渲染器实例"""
        console = Console(force_terminal=True, width=100)
        return DiagnosisRenderer(console)

    @pytest.fixture
    def sample_phenomenon(self):
        """创建示例现象"""
        return Phenomenon(
            phenomenon_id="P-0001",
            description="wait_io 事件占比异常高",
            observation_method="SELECT wait_event_type, count(*) FROM pg_stat_activity...",
            source_anomaly_ids=["A-0001", "A-0002"],
            cluster_size=2,
            embedding=None,
        )

    # ===== get_logo 测试 =====

    def test_get_logo_gar(self, renderer):
        """测试获取 GAR LOGO"""
        logo = renderer.get_logo("gar")
        assert logo.strip()  # 非空
        assert len(logo) > 100  # LOGO 应该有足够长度

    def test_get_logo_hyb(self, renderer):
        """测试获取 HYB LOGO"""
        logo = renderer.get_logo("hyb")
        assert logo.strip()
        assert len(logo) > 100

    def test_get_logo_rar(self, renderer):
        """测试获取 RAR LOGO"""
        logo = renderer.get_logo("rar")
        assert logo.strip()
        assert len(logo) > 100

    def test_get_logo_default(self, renderer):
        """测试未知模式返回默认 LOGO"""
        logo = renderer.get_logo("unknown")
        assert logo == renderer.get_logo("gar")

    # ===== render_status_bar 测试 =====

    def test_render_status_bar_basic(self, renderer):
        """测试渲染状态栏（基础）"""
        result = renderer.render_status_bar(
            round_count=2,
            recommended=5,
            confirmed=3,
            denied=1,
        )
        assert isinstance(result, Group)

    def test_render_status_bar_with_hypotheses(self, renderer):
        """测试渲染状态栏（含假设）"""
        hypotheses = [
            (0.85, "索引膨胀导致 IO 瓶颈"),
            (0.65, "锁等待导致性能下降"),
            (0.45, "连接池耗尽"),
        ]
        result = renderer.render_status_bar(
            round_count=3,
            recommended=8,
            confirmed=5,
            denied=2,
            hypotheses=hypotheses,
        )
        assert isinstance(result, Group)

    def test_render_status_bar_empty_hypotheses(self, renderer):
        """测试渲染状态栏（无假设）"""
        result = renderer.render_status_bar(
            round_count=1,
            recommended=0,
            confirmed=0,
            denied=0,
            hypotheses=[],
        )
        assert isinstance(result, Group)

    # ===== render_phenomenon_recommendation 测试 =====

    def test_render_phenomenon_recommendation_basic(self, renderer, sample_phenomenon):
        """测试渲染现象推荐（基础）"""
        phenomena_with_reasons = [
            {"phenomenon": sample_phenomenon, "reason": "与假设 A 相关"},
        ]
        result = renderer.render_phenomenon_recommendation(phenomena_with_reasons)
        assert isinstance(result, Group)

    def test_render_phenomenon_recommendation_multiple(self, renderer, sample_phenomenon):
        """测试渲染多个现象推荐"""
        p2 = Phenomenon(
            phenomenon_id="P-0002",
            description="索引大小异常增长",
            observation_method="SELECT pg_relation_size(indexrelid)...",
            source_anomaly_ids=["A-0003"],
            cluster_size=1,
            embedding=None,
        )
        phenomena_with_reasons = [
            {"phenomenon": sample_phenomenon, "reason": "原因1"},
            {"phenomenon": p2, "reason": "原因2"},
        ]
        result = renderer.render_phenomenon_recommendation(phenomena_with_reasons)
        assert isinstance(result, Group)

    def test_render_phenomenon_recommendation_empty(self, renderer):
        """测试渲染空推荐"""
        result = renderer.render_phenomenon_recommendation([])
        assert isinstance(result, Group)

    def test_render_phenomenon_recommendation_no_reason(self, renderer, sample_phenomenon):
        """测试渲染无原因的推荐"""
        phenomena_with_reasons = [
            {"phenomenon": sample_phenomenon, "reason": ""},
        ]
        result = renderer.render_phenomenon_recommendation(phenomena_with_reasons)
        assert isinstance(result, Group)

    def test_render_phenomenon_recommendation_empty_observation_method(self, renderer):
        """测试渲染空观察方法的现象"""
        p = Phenomenon(
            phenomenon_id="P-0003",
            description="某个现象",
            observation_method="",  # 空字符串
            source_anomaly_ids=["A-0004"],
            cluster_size=1,
            embedding=None,
        )
        phenomena_with_reasons = [{"phenomenon": p, "reason": "测试"}]
        result = renderer.render_phenomenon_recommendation(phenomena_with_reasons)
        assert isinstance(result, Group)

    # ===== render_diagnosis_result 测试 =====

    def test_render_diagnosis_result_basic(self, renderer):
        """测试渲染诊断结果（基础）"""
        result = renderer.render_diagnosis_result(
            root_cause="索引膨胀导致 IO 瓶颈",
        )
        assert isinstance(result, Panel)

    def test_render_diagnosis_result_with_summary(self, renderer):
        """测试渲染诊断结果（含总结）"""
        result = renderer.render_diagnosis_result(
            root_cause="索引膨胀导致 IO 瓶颈",
            diagnosis_summary="### 分析\n用户确认了 wait_io 高...",
        )
        assert isinstance(result, Panel)

    def test_render_diagnosis_result_with_citations(self, renderer):
        """测试渲染诊断结果（含引用）"""
        citations = [
            {"ticket_id": "T-0001", "description": "类似问题工单"},
            {"ticket_id": "T-0018", "description": "索引膨胀案例"},
        ]
        result = renderer.render_diagnosis_result(
            root_cause="索引膨胀导致 IO 瓶颈",
            diagnosis_summary="诊断总结...",
            citations=citations,
        )
        assert isinstance(result, Panel)

    def test_render_diagnosis_result_full(self, renderer):
        """测试渲染完整诊断结果"""
        citations = [
            {"ticket_id": "T-0001", "description": "工单1"},
        ]
        result = renderer.render_diagnosis_result(
            root_cause="索引膨胀导致 IO 瓶颈",
            diagnosis_summary="### 分析\n详细分析...\n\n### 恢复措施\n1. REINDEX...",
            citations=citations,
        )
        assert isinstance(result, Panel)
        assert result.title == "✓ 根因已定位"

    # ===== render_help 测试 =====

    def test_render_help_gar(self, renderer):
        """测试渲染 GAR 帮助"""
        result = renderer.render_help("gar")
        assert isinstance(result, Panel)
        assert result.title == "帮助"

    def test_render_help_rar(self, renderer):
        """测试渲染 RAR 帮助"""
        result = renderer.render_help("rar")
        assert isinstance(result, Panel)

    def test_render_help_default(self, renderer):
        """测试渲染默认帮助"""
        result = renderer.render_help()
        assert isinstance(result, Panel)

    # ===== _render_confidence_bar 测试 =====

    def test_render_confidence_bar_high(self, renderer):
        """测试渲染高置信度条"""
        result = renderer._render_confidence_bar(1, 0.85, "高置信度假设")
        assert isinstance(result, Text)

    def test_render_confidence_bar_low(self, renderer):
        """测试渲染低置信度条"""
        result = renderer._render_confidence_bar(2, 0.25, "低置信度假设")
        assert isinstance(result, Text)

    def test_render_confidence_bar_zero(self, renderer):
        """测试渲染零置信度条"""
        result = renderer._render_confidence_bar(3, 0.0, "零置信度")
        assert isinstance(result, Text)

    def test_render_confidence_bar_full(self, renderer):
        """测试渲染满置信度条"""
        result = renderer._render_confidence_bar(1, 1.0, "满置信度")
        assert isinstance(result, Text)

    def test_render_confidence_bar_long_description(self, renderer):
        """测试渲染长描述（会被截断）"""
        long_desc = "这是一个非常非常非常非常非常非常非常非常非常非常长的描述"
        result = renderer._render_confidence_bar(1, 0.5, long_desc)
        assert isinstance(result, Text)

    # ===== 边界情况测试 =====

    def test_renderer_without_console(self):
        """测试不提供 console 时使用默认 console"""
        renderer = DiagnosisRenderer()
        assert renderer.console is not None

    def test_render_status_bar_large_numbers(self, renderer):
        """测试大数字统计"""
        result = renderer.render_status_bar(
            round_count=999,
            recommended=9999,
            confirmed=8888,
            denied=7777,
        )
        assert isinstance(result, Group)
