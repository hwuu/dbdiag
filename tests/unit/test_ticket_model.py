"""Ticket 模型单元测试"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.models.ticket import Ticket


class TestTicket:
    """Ticket 模型测试"""

    def test_create_minimal_ticket(self):
        """测试:创建最小工单"""
        ticket = Ticket(
            ticket_id="T001",
            metadata={},
            description="查询性能下降",
            root_cause="缺少索引",
            solution="添加索引",
        )

        assert ticket.ticket_id == "T001"
        assert ticket.description == "查询性能下降"
        assert ticket.root_cause == "缺少索引"
        assert ticket.solution == "添加索引"
        assert ticket.metadata == {}

    def test_create_ticket_with_metadata(self):
        """测试:创建带元数据的工单"""
        ticket = Ticket(
            ticket_id="T002",
            metadata={
                "db_type": "PostgreSQL",
                "version": "14.5",
                "environment": "production",
                "severity": "high",
            },
            description="连接数过多",
            root_cause="连接泄漏",
            solution="修复连接池配置",
        )

        assert ticket.metadata["db_type"] == "PostgreSQL"
        assert ticket.metadata["version"] == "14.5"
        assert ticket.metadata["environment"] == "production"
        assert ticket.metadata["severity"] == "high"

    def test_ticket_serialization(self):
        """测试:工单序列化"""
        ticket = Ticket(
            ticket_id="T003",
            metadata={"db_type": "MySQL", "version": "8.0"},
            description="慢查询",
            root_cause="未使用索引",
            solution="优化查询",
        )

        # 转为字典
        ticket_dict = ticket.model_dump()
        assert ticket_dict["ticket_id"] == "T003"
        assert ticket_dict["metadata"]["db_type"] == "MySQL"

        # 从字典创建
        ticket2 = Ticket(**ticket_dict)
        assert ticket2.ticket_id == ticket.ticket_id
        assert ticket2.metadata == ticket.metadata

    def test_ticket_with_complex_metadata(self):
        """测试:复杂元数据的工单"""
        ticket = Ticket(
            ticket_id="T004",
            metadata={
                "db_type": "PostgreSQL",
                "version": "13.8",
                "tables": ["users", "orders", "products"],
                "indexes": {
                    "users": ["idx_email", "idx_created_at"],
                    "orders": ["idx_user_id", "idx_status"],
                },
                "performance_metrics": {
                    "avg_query_time": 5.2,
                    "max_query_time": 30.5,
                    "qps": 1500,
                },
            },
            description="多表查询性能问题",
            root_cause="JOIN 缺少索引",
            solution="在关联字段上添加索引",
        )

        # 验证嵌套元数据
        assert len(ticket.metadata["tables"]) == 3
        assert "idx_email" in ticket.metadata["indexes"]["users"]
        assert ticket.metadata["performance_metrics"]["avg_query_time"] == 5.2

    def test_missing_required_fields(self):
        """测试:缺少必需字段"""
        with pytest.raises(Exception):  # Pydantic ValidationError
            Ticket(
                ticket_id="T005",
                # 缺少其他必需字段
            )

    def test_ticket_equality(self):
        """测试:工单比较"""
        ticket1 = Ticket(
            ticket_id="T006",
            metadata={"db_type": "MySQL"},
            description="性能问题",
            root_cause="索引缺失",
            solution="添加索引",
        )

        ticket2 = Ticket(
            ticket_id="T006",
            metadata={"db_type": "MySQL"},
            description="性能问题",
            root_cause="索引缺失",
            solution="添加索引",
        )

        # Pydantic 模型支持相等性比较
        assert ticket1.ticket_id == ticket2.ticket_id
        assert ticket1.model_dump() == ticket2.model_dump()

    def test_ticket_update_metadata(self):
        """测试:更新工单元数据"""
        ticket = Ticket(
            ticket_id="T007",
            metadata={"db_type": "PostgreSQL"},
            description="连接问题",
            root_cause="连接池配置",
            solution="调整配置",
        )

        # 更新元数据
        ticket.metadata["resolved"] = True
        ticket.metadata["resolution_time"] = "2h"

        assert ticket.metadata["resolved"] is True
        assert ticket.metadata["resolution_time"] == "2h"

    def test_empty_metadata(self):
        """测试:空元数据"""
        ticket = Ticket(
            ticket_id="T008",
            metadata={},
            description="测试问题",
            root_cause="测试原因",
            solution="测试方案",
        )

        assert isinstance(ticket.metadata, dict)
        assert len(ticket.metadata) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
