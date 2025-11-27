"""测试 phenomenon 数据模型"""
import pytest
from datetime import datetime
from dbdiag.models import (
    RawAnomaly,
    Phenomenon,
    TicketAnomaly,
)


class TestRawAnomaly:
    """测试原始异常模型"""

    def test_create_raw_anomaly(self):
        """测试创建原始异常"""
        anomaly = RawAnomaly(
            id="TICKET-001_anomaly_1",
            ticket_id="TICKET-001",
            anomaly_index=1,
            description="wait_io 事件占比 65%，远超日常 20% 水平",
            observation_method="SELECT event, count FROM pg_stat_activity WHERE wait_event IS NOT NULL",
            why_relevant="IO 等待高说明磁盘读写存在瓶颈，是查询变慢的直接原因",
        )

        assert anomaly.id == "TICKET-001_anomaly_1"
        assert anomaly.ticket_id == "TICKET-001"
        assert anomaly.anomaly_index == 1
        assert "wait_io" in anomaly.description
        assert "SELECT" in anomaly.observation_method
        assert "IO 等待" in anomaly.why_relevant

    def test_raw_anomaly_optional_fields(self):
        """测试原始异常可选字段"""
        anomaly = RawAnomaly(
            id="TICKET-001_anomaly_1",
            ticket_id="TICKET-001",
            anomaly_index=1,
            description="test",
            observation_method="test",
            why_relevant="test",
        )

        # created_at 应该有默认值
        assert anomaly.created_at is not None
        assert isinstance(anomaly.created_at, datetime)

    def test_raw_anomaly_to_dict(self):
        """测试原始异常序列化"""
        anomaly = RawAnomaly(
            id="TICKET-001_anomaly_1",
            ticket_id="TICKET-001",
            anomaly_index=1,
            description="test",
            observation_method="test",
            why_relevant="test",
        )

        data = anomaly.model_dump()
        assert data["id"] == "TICKET-001_anomaly_1"
        assert data["ticket_id"] == "TICKET-001"


class TestPhenomenon:
    """测试标准现象模型"""

    def test_create_phenomenon(self):
        """测试创建标准现象"""
        phenomenon = Phenomenon(
            phenomenon_id="P-0001",
            description="wait_io 事件占比异常高（超过阈值 60%）",
            observation_method="SELECT wait_event_type, wait_event, COUNT(*) FROM pg_stat_activity WHERE wait_event IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC",
            source_anomaly_ids=["TICKET-001_anomaly_1", "TICKET-005_anomaly_2"],
            cluster_size=2,
        )

        assert phenomenon.phenomenon_id == "P-0001"
        assert "wait_io" in phenomenon.description
        assert len(phenomenon.source_anomaly_ids) == 2
        assert phenomenon.cluster_size == 2

    def test_phenomenon_optional_embedding(self):
        """测试标准现象可选的 embedding 字段"""
        phenomenon = Phenomenon(
            phenomenon_id="P-0001",
            description="test",
            observation_method="test",
            source_anomaly_ids=[],
            cluster_size=0,
        )

        # embedding 默认为 None
        assert phenomenon.embedding is None

    def test_phenomenon_with_embedding(self):
        """测试标准现象带 embedding"""
        embedding = [0.1, 0.2, 0.3, 0.4]
        phenomenon = Phenomenon(
            phenomenon_id="P-0001",
            description="test",
            observation_method="test",
            source_anomaly_ids=[],
            cluster_size=0,
            embedding=embedding,
        )

        assert phenomenon.embedding == embedding

    def test_phenomenon_to_dict(self):
        """测试标准现象序列化"""
        phenomenon = Phenomenon(
            phenomenon_id="P-0001",
            description="test",
            observation_method="test",
            source_anomaly_ids=["a", "b"],
            cluster_size=2,
        )

        data = phenomenon.model_dump()
        assert data["phenomenon_id"] == "P-0001"
        assert data["source_anomaly_ids"] == ["a", "b"]


class TestTicketAnomaly:
    """测试工单-现象关联模型"""

    def test_create_ticket_anomaly(self):
        """测试创建工单-现象关联"""
        ticket_anomaly = TicketAnomaly(
            id="TICKET-001_anomaly_1",
            ticket_id="TICKET-001",
            phenomenon_id="P-0001",
            why_relevant="IO 等待高说明磁盘读写瓶颈，导致查询扫描效率下降",
        )

        assert ticket_anomaly.id == "TICKET-001_anomaly_1"
        assert ticket_anomaly.ticket_id == "TICKET-001"
        assert ticket_anomaly.phenomenon_id == "P-0001"
        assert "IO 等待" in ticket_anomaly.why_relevant

    def test_ticket_anomaly_optional_raw_anomaly_id(self):
        """测试工单-现象关联可选的原始异常ID"""
        ticket_anomaly = TicketAnomaly(
            id="TICKET-001_anomaly_1",
            ticket_id="TICKET-001",
            phenomenon_id="P-0001",
            why_relevant="test",
        )

        # raw_anomaly_id 默认为 None
        assert ticket_anomaly.raw_anomaly_id is None

    def test_ticket_anomaly_with_raw_anomaly_id(self):
        """测试工单-现象关联带原始异常ID"""
        ticket_anomaly = TicketAnomaly(
            id="TICKET-001_anomaly_1",
            ticket_id="TICKET-001",
            phenomenon_id="P-0001",
            why_relevant="test",
            raw_anomaly_id="TICKET-001_anomaly_1",
        )

        assert ticket_anomaly.raw_anomaly_id == "TICKET-001_anomaly_1"

    def test_ticket_anomaly_to_dict(self):
        """测试工单-现象关联序列化"""
        ticket_anomaly = TicketAnomaly(
            id="TICKET-001_anomaly_1",
            ticket_id="TICKET-001",
            phenomenon_id="P-0001",
            why_relevant="test",
        )

        data = ticket_anomaly.model_dump()
        assert data["ticket_id"] == "TICKET-001"
        assert data["phenomenon_id"] == "P-0001"
