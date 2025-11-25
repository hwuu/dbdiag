"""测试查询变慢场景的诊断流程"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.dialogue_manager import DialogueManager
from app.utils.config import load_config


@pytest.fixture
def dialogue_manager():
    """创建对话管理器实例"""
    config = load_config()
    db_path = str(Path("data") / "tickets.db")
    return DialogueManager(db_path, config)


def test_slow_query_diagnosis_flow(dialogue_manager):
    """测试:查询变慢的完整诊断流程"""

    # 第 1 轮:用户描述问题
    print("\n=== 第 1 轮:用户描述问题 ===")
    user_problem = "查询变慢"
    response1 = dialogue_manager.start_conversation(user_problem)

    session_id = response1["session_id"]
    print(f"会话 ID: {session_id}")
    print(f"系统响应:\n{response1['message']}\n")

    # 验证第一轮响应
    assert "session_id" in response1
    assert len(response1["message"]) > 0

    # 第 2 轮:用户反馈"IO 正常"
    print("=== 第 2 轮:用户反馈 'IO 正常' ===")
    user_message2 = "io 正常"
    response2 = dialogue_manager.continue_conversation(session_id, user_message2)

    print(f"系统响应:\n{response2['message']}\n")

    # 验证第二轮响应
    assert "message" in response2
    assert len(response2["message"]) > 0

    # 获取第一轮推荐的步骤 ID
    first_step_id = response1.get("step", {}).get("step_id")
    second_step_id = response2.get("step", {}).get("step_id")

    # 验证：第二轮不应该推荐相同的步骤（保守策略：可以推荐同一假设的其他步骤）
    print("=== 验证步骤追踪 ===")
    if first_step_id and second_step_id:
        if first_step_id == second_step_id:
            print(f"[ERROR] 系统重复推荐了相同的步骤: {first_step_id}")
            assert False, "系统不应该重复推荐已执行的步骤"
        else:
            print(f"[OK] 第一轮步骤: {first_step_id}")
            print(f"[OK] 第二轮步骤: {second_step_id}")
            print("[OK] 系统正确避免了重复推荐相同步骤")

    # 第 3 轮:继续对话
    print("\n=== 第 3 轮:继续诊断 ===")
    user_message3 = "CPU 使用率也正常"
    response3 = dialogue_manager.continue_conversation(session_id, user_message3)

    print(f"系统响应:\n{response3['message']}\n")

    assert "message" in response3

    # 获取会话状态查看假设演化
    print("=== 会话状态 ===")
    session = dialogue_manager.get_session(session_id)
    print(f"已确认事实数: {session['confirmed_facts_count']}")
    print(f"活跃假设数: {session['active_hypotheses_count']}")
    print(f"对话轮次: {session['dialogue_turns']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
