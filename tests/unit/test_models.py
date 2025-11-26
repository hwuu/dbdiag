"""DiagnosticStep 模型单元测试

注意：DiagnosticStep 已标记为 deprecated，请使用 Phenomenon 替代。
此测试文件保留用于验证向后兼容性。
"""
import pytest
import warnings
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.models.step import DiagnosticStep


class TestDiagnosticStep:
    """DiagnosticStep 模型测试 (DEPRECATED)"""

    def test_create_step_minimal(self):
        """测试:创建最小步骤"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            step = DiagnosticStep(
                step_id="step_001",
                ticket_id="T001",
                step_index=0,
                observed_fact="查询很慢",
                observation_method="EXPLAIN",
                analysis_result="缺少索引",
                ticket_description="性能问题",
                ticket_root_cause="缺少索引",
            )

            assert step.step_id == "step_001"
            assert step.ticket_id == "T001"
            assert step.step_index == 0
            assert step.fact_embedding is None
            assert step.method_embedding is None

            # 验证 deprecation 警告
            assert len(w) >= 1
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)

    def test_create_step_with_embeddings(self):
        """测试:创建带向量的步骤"""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            step = DiagnosticStep(
                step_id="step_002",
                ticket_id="T002",
                step_index=1,
                observed_fact="连接数过多",
                observation_method="SELECT count(*)",
                analysis_result="连接泄漏",
                ticket_description="连接问题",
                ticket_root_cause="连接泄漏",
                fact_embedding=[0.1, 0.2, 0.3],
                method_embedding=[0.4, 0.5, 0.6],
            )

            assert step.fact_embedding == [0.1, 0.2, 0.3]
            assert step.method_embedding == [0.4, 0.5, 0.6]

    def test_missing_required_field(self):
        """测试:缺少必需字段时抛出异常"""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            with pytest.raises(Exception):  # Pydantic ValidationError
                DiagnosticStep(
                    step_id="step_003",
                    # 缺少其他必需字段
                )

    def test_step_serialization(self):
        """测试:步骤序列化"""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            step = DiagnosticStep(
                step_id="step_004",
                ticket_id="T004",
                step_index=2,
                observed_fact="CPU 高",
                observation_method="top",
                analysis_result="查询负载高",
                ticket_description="CPU 问题",
                ticket_root_cause="查询未优化",
            )

            # 转为字典
            step_dict = step.model_dump()
            assert step_dict["step_id"] == "step_004"
            assert step_dict["ticket_id"] == "T004"

            # 从字典创建
            step2 = DiagnosticStep(**step_dict)
            assert step2.step_id == step.step_id
            assert step2.observed_fact == step.observed_fact

    def test_deprecation_warning(self):
        """测试:DiagnosticStep 应触发 deprecation 警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DiagnosticStep(
                step_id="step_dep",
                ticket_id="T_dep",
                step_index=0,
                observed_fact="test",
                observation_method="test",
                analysis_result="test",
                ticket_description="test",
                ticket_root_cause="test",
            )

            # 验证触发了 DeprecationWarning
            deprecation_warnings = [
                warning for warning in w
                if issubclass(warning.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
