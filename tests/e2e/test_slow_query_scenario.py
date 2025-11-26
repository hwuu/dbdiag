"""测试查询变慢场景的诊断流程"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.core.dialogue_manager import DialogueManager
from dbdiag.utils.config import load_config


@pytest.fixture
def dialogue_manager():
    """创建对话管理器实例"""
    config = load_config()
    db_path = str(Path("data") / "tickets.db")

    # 创建单例服务
    from dbdiag.services.llm_service import LLMService
    from dbdiag.services.embedding_service import EmbeddingService

    llm_service = LLMService(config)
    embedding_service = EmbeddingService(config)

    return DialogueManager(db_path, llm_service, embedding_service)


def test_slow_query_diagnosis_flow(dialogue_manager):
    """测试:查询变慢的完整诊断流程"""

    # 第 1 轮:用户描述问题
    print("\n=== 第 1 轮:用户描述问题 ===")
    user_problem = "查询变慢"
    response1 = dialogue_manager.start_conversation(user_problem)

    session_id = response1["session_id"]
    print(f"会话 ID: {session_id}")
    print(f"系统响应:\n{response1['message'][:200]}...\n")

    # 打印假设状态
    session_state = dialogue_manager.session_service.get_session(session_id)
    print(f"当前假设数: {len(session_state.active_hypotheses)}")
    for i, hyp in enumerate(session_state.active_hypotheses[:3], 1):
        print(f"  假设{i}: {hyp.root_cause[:50]}... (置信度: {hyp.confidence:.2f})")

    # 验证第一轮响应
    assert "session_id" in response1
    assert len(response1["message"]) > 0

    # 第 2 轮:用户确认 IO 问题
    print("\n=== 第 2 轮:用户确认 IO 问题 ===")
    user_message2 = "wait_io 占比确实很高"
    response2 = dialogue_manager.continue_conversation(session_id, user_message2)

    print(f"系统响应:\n{response2['message'][:200]}...\n")

    # 打印假设状态
    session_state = dialogue_manager.session_service.get_session(session_id)
    print(f"当前假设数: {len(session_state.active_hypotheses)}")
    for i, hyp in enumerate(session_state.active_hypotheses[:3], 1):
        print(f"  假设{i}: {hyp.root_cause[:50]}... (置信度: {hyp.confidence:.2f})")

    # 验证第二轮响应
    assert "message" in response2
    assert len(response2["message"]) > 0

    # 获取第一轮推荐的步骤 ID
    first_step_id = response1.get("step", {}).get("step_id")
    second_step_id = response2.get("step", {}).get("step_id")

    # 验证：第二轮不应该推荐相同的步骤
    print("=== 验证步骤追踪 ===")
    if first_step_id and second_step_id:
        if first_step_id == second_step_id:
            print(f"[ERROR] 系统重复推荐了相同的步骤: {first_step_id}")
            assert False, "系统不应该重复推荐已执行的步骤"
        else:
            print(f"[OK] 第一轮步骤: {first_step_id}")
            print(f"[OK] 第二轮步骤: {second_step_id}")
            print("[OK] 系统正确避免了重复推荐相同步骤")

    # 第 3-5 轮:继续测试，观察是否会收敛
    max_rounds = 5
    for round_num in range(3, max_rounds + 1):
        print(f"\n=== 第 {round_num} 轮:继续诊断 ===")
        response = dialogue_manager.continue_conversation(
            session_id, f"确认，观察到了相关现象，第{round_num}轮"
        )

        print(f"系统响应:\n{response['message'][:200]}...")

        # 打印假设状态
        session_state = dialogue_manager.session_service.get_session(session_id)
        print(f"\n当前假设数: {len(session_state.active_hypotheses)}")
        for i, hyp in enumerate(session_state.active_hypotheses[:3], 1):
            print(f"  假设{i}: {hyp.root_cause[:50]}... (置信度: {hyp.confidence:.2f})")

        # 检查是否已确认根因
        if response.get("action") == "confirm_root_cause":
            print(f"\n[SUCCESS] 在第 {round_num} 轮确认了根因!")
            print(f"根因: {response.get('root_cause')}")
            print(f"置信度: {response.get('confidence'):.2f}")
            break

        if response.get("step"):
            print(f"推荐步骤: {response['step'].get('step_id')}")
    else:
        print(f"\n[WARNING] {max_rounds} 轮后仍未确认根因，可能需要调整假设排他性参数")

    # 获取会话状态查看假设演化
    print("\n=== 会话状态 ===")
    session = dialogue_manager.get_session(session_id)
    print(f"已确认事实数: {session['confirmed_facts_count']}")
    print(f"活跃假设数: {session['active_hypotheses_count']}")
    print(f"对话轮次: {session['dialogue_turns']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
