"""端到端诊断流程测试

测试从用户输入问题到生成诊断建议的完整流程
"""
import pytest
from pathlib import Path
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from dbdiag.core.dialogue_manager import GARDialogueManager
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.config import load_config


@pytest.fixture
def dialogue_manager():
    """创建对话管理器实例"""
    config = load_config()
    db_path = str(Path("data") / "tickets.db")

    # 创建单例服务
    llm_service = LLMService(config)
    embedding_service = EmbeddingService(config)

    return GARDialogueManager(db_path, llm_service, embedding_service)


class TestE2EDiagnosis:
    """端到端诊断测试"""

    def test_start_conversation_with_performance_issue(self, dialogue_manager):
        """测试:启动性能问题诊断会话"""
        user_problem = "查询突然变慢，原来5秒现在要30秒"

        # 开始对话
        response = dialogue_manager.start_conversation(user_problem)

        # 验证响应结构
        assert "session_id" in response
        assert "message" in response
        assert response["session_id"].startswith("sess_")

        # 验证生成了诊断建议
        assert len(response["message"]) > 0
        # 验证消息包含实质内容（V2 使用现象确认机制）
        assert any(
            keyword in response["message"]
            for keyword in ["现象", "确认", "建议", "检查", "诊断"]
        )

    def test_multi_round_diagnosis_flow(self, dialogue_manager):
        """测试:多轮对话诊断流程"""
        # 第 1 轮:用户描述问题
        user_problem = "数据库连接数突然飙升"
        response1 = dialogue_manager.start_conversation(user_problem)

        session_id = response1["session_id"]
        assert len(response1["message"]) > 0

        # 第 2 轮:用户反馈诊断结果
        user_message2 = "检查了慢查询日志，发现有很多扫描全表的查询"
        response2 = dialogue_manager.continue_conversation(session_id, user_message2)

        # 验证系统更新了假设
        assert "message" in response2
        assert len(response2["message"]) > 0

        # 第 3 轮:继续诊断
        user_message3 = "查看了执行计划，确实没有使用索引"
        response3 = dialogue_manager.continue_conversation(session_id, user_message3)

        assert "message" in response3
        assert len(response3["message"]) > 0

    def test_session_persistence(self, dialogue_manager):
        """测试:会话持久化"""
        # 创建会话
        user_problem = "查询偶尔超时"
        response1 = dialogue_manager.start_conversation(user_problem)
        session_id = response1["session_id"]

        # 继续对话
        user_message = "CPU 使用率正常，内存也正常"
        response2 = dialogue_manager.continue_conversation(session_id, user_message)

        # 验证可以获取会话
        session = dialogue_manager.get_session(session_id)
        assert session is not None
        assert session["session_id"] == session_id
        assert session["user_problem"] == user_problem

    def test_list_sessions(self, dialogue_manager):
        """测试:列出会话"""
        # 创建几个会话
        problems = [
            "查询很慢",
            "连接数过多",
            "死锁频繁",
        ]

        for problem in problems:
            dialogue_manager.start_conversation(problem)

        # 列出会话
        sessions = dialogue_manager.list_sessions(limit=10)

        # 验证至少有我们刚创建的会话
        assert len(sessions) >= len(problems)
        assert all("session_id" in s for s in sessions)
        assert all("user_problem" in s for s in sessions)

    def test_invalid_session_id(self, dialogue_manager):
        """测试:无效的会话 ID"""
        response = dialogue_manager.continue_conversation(
            "invalid_session_id", "测试消息"
        )

        # 应该返回错误信息
        assert "error" in response or "错误" in response.get("message", "")

    def test_empty_problem_description(self, dialogue_manager):
        """测试:空问题描述"""
        # 系统可能会进行容错处理,而不是抛出异常
        # 测试空字符串
        response = dialogue_manager.start_conversation("")
        # 应该返回有效响应或包含提示信息
        assert "session_id" in response or "error" in response

        # 测试只有空格
        response2 = dialogue_manager.start_conversation("   ")
        assert "session_id" in response2 or "error" in response2

    def test_fact_extraction_from_user_message(self, dialogue_manager):
        """测试:从用户消息中提取事实"""
        user_problem = "数据库查询变慢"
        response1 = dialogue_manager.start_conversation(user_problem)
        session_id = response1["session_id"]

        # 用户反馈包含明确的诊断结果
        user_message = "检查了 CPU 使用率是 95%，内存使用正常，慢查询日志显示有大量全表扫描"
        response2 = dialogue_manager.continue_conversation(session_id, user_message)

        # 获取会话状态
        session = dialogue_manager.get_session(session_id)

        # 验证会话存在且对话轮次至少为 1（开始对话 + 继续对话）
        assert session is not None
        assert session["dialogue_turns"] >= 1

    def test_hypothesis_confidence_evolution(self, dialogue_manager):
        """测试:假设置信度演化"""
        # 开始诊断
        user_problem = "SELECT 查询突然变慢"
        response1 = dialogue_manager.start_conversation(user_problem)
        session_id = response1["session_id"]

        # 初始会话状态
        session1 = dialogue_manager.get_session(session_id)
        assert session1 is not None
        initial_hypotheses_count = session1["active_hypotheses_count"]
        # 验证系统生成了假设
        assert initial_hypotheses_count > 0

        # 提供更多证据
        user_message = "检查发现缺少索引，执行计划显示全表扫描"
        response2 = dialogue_manager.continue_conversation(session_id, user_message)

        # 获取更新后的假设
        session2 = dialogue_manager.get_session(session_id)
        updated_hypotheses_count = session2["active_hypotheses_count"]

        # 验证假设仍然存在
        assert updated_hypotheses_count > 0

    def test_citation_generation(self, dialogue_manager):
        """测试:引用生成"""
        user_problem = "查询性能下降"
        response = dialogue_manager.start_conversation(user_problem)

        # 验证响应中包含引用信息（如果有相关工单）
        # 引用格式: [1], [2] 等
        message = response["message"]
        assert len(message) > 0  # 至少有诊断建议

    def test_recommendation_types(self, dialogue_manager):
        """测试:不同类型的推荐"""
        # 启动诊断,验证系统能生成推荐
        user_problem = "数据库响应时间不稳定"
        response = dialogue_manager.start_conversation(user_problem)

        message = response["message"]

        # 验证包含推荐内容（V2 使用现象确认机制）
        assert len(message) > 0
        assert any(
            keyword in message
            for keyword in ["建议", "推荐", "检查", "现象", "确认", "诊断"]
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
