"""测试 CLI 格式化器"""
import pytest

from dbdiag.cli.formatter import TextFormatter


class TestTextFormatter:
    """测试文本格式化器"""

    def test_format_welcome(self):
        """测试欢迎信息格式化"""
        result = TextFormatter.format_welcome()

        assert "数据库诊断助手" in result
        assert "请描述您遇到的数据库问题" in result

    def test_format_step_recommendation(self):
        """测试步骤推荐格式化"""
        response = {
            "action": "recommend_step",
            "step": {
                "step_id": "TICKET-001_step_1",
                "observed_fact": "检查 IO 等待",
                "observation_method": "SELECT * FROM pg_stat_activity;",
                "analysis_result": "确定瓶颈类型",
            },
            "message": "基于 TICKET-001 推荐",
        }

        result = TextFormatter.format_step_recommendation(response)

        assert "观察目标" in result
        assert "检查 IO 等待" in result
        assert "操作方法" in result
        assert "SELECT" in result
        assert "诊断目的" in result
        assert "确定瓶颈类型" in result

    def test_format_step_recommendation_with_citations(self):
        """测试带引用的步骤推荐格式化"""
        response = {
            "action": "recommend_step",
            "step": {
                "step_id": "DB-018_step_1",
                "observed_fact": "检查 IO 等待",
                "observation_method": "SELECT * FROM pg_stat_activity;",
                "analysis_result": "确定 IO 瓶颈",
            },
            "citations": [
                {
                    "ticket_id": "DB-018",
                    "description": "定时任务执行报错",
                    "root_cause": "频繁更新导致索引碎片化",
                }
            ],
            "message": "基于历史工单推荐",
        }

        result = TextFormatter.format_step_recommendation(response)

        # 验证基本内容
        assert "观察目标" in result
        assert "检查 IO 等待" in result

        # 验证引用信息
        assert "引用工单" in result
        assert "[1] DB-018" in result
        assert "定时任务执行报错" in result
        assert "根因: 频繁更新导致索引碎片化" in result

    def test_format_root_cause_confirmation(self):
        """测试根因确认格式化"""
        response = {
            "action": "confirm_root_cause",
            "root_cause": "索引膨胀导致 IO 瓶颈",
            "confidence": 0.88,
            "message": "详细说明...",
        }

        result = TextFormatter.format_root_cause_confirmation(response)

        assert "根因已定位" in result
        assert "索引膨胀导致 IO 瓶颈" in result
        assert "88%" in result

    def test_format_status(self):
        """测试状态信息格式化"""
        session_info = {
            "session_id": "sess_123",
            "user_problem": "查询变慢",
            "confirmed_facts_count": 2,
            "active_hypotheses_count": 3,
            "dialogue_turns": 5,
        }

        result = TextFormatter.format_status(session_info)

        assert "当前诊断状态" in result
        assert "sess_123" in result
        assert "查询变慢" in result
        assert "2" in result
        assert "3" in result
        assert "5" in result

    def test_format_help(self):
        """测试帮助信息格式化"""
        result = TextFormatter.format_help()

        assert "/help" in result
        assert "/status" in result
        assert "/history" in result
        assert "/reset" in result
        assert "/exit" in result

    def test_format_error(self):
        """测试错误信息格式化"""
        result = TextFormatter.format_error("测试错误")

        assert "[错误]" in result
        assert "测试错误" in result

    def test_format_system_message(self):
        """测试系统消息格式化"""
        result = TextFormatter.format_system_message("测试消息")

        assert "[系统]" in result
        assert "测试消息" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
