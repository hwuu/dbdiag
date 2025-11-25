"""测试语义去重功能"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.core.recommender import RecommendationEngine
from dbdiag.models.session import SessionState, Hypothesis, ExecutedStep
from dbdiag.models.step import DiagnosticStep
from dbdiag.utils.config import load_config


def test_semantic_deduplication():
    """测试语义去重：相似的诊断步骤不应被重复推荐"""
    print("\n=== 测试语义去重功能 ===\n")

    # 加载配置
    config = load_config()
    db_path = str(Path("data") / "tickets.db")

    # 创建单例服务
    from dbdiag.services.llm_service import LLMService

    llm_service = LLMService(config)

    # 创建推荐引擎
    recommender = RecommendationEngine(db_path, llm_service)

    # 创建会话状态
    session = SessionState(
        session_id="test_session",
        user_problem="查询变慢",
        active_hypotheses=[
            Hypothesis(
                root_cause="索引膨胀导致 IO 瓶颈",
                confidence=0.70,
                supporting_step_ids=["DB-001_step_1", "DB-018_step_1", "DB-001_step_2"],
                next_recommended_step_id="DB-018_step_1",
                missing_facts=[],
            )
        ],
        executed_steps=[
            ExecutedStep(
                step_id="DB-001_step_1",
                result_summary="IO 确实很高",
            )
        ],
    )

    # 获取推荐
    recommendation = recommender.recommend_next_action(session)

    print(f"会话状态:")
    print(f"  已执行步骤: {[s.step_id for s in session.executed_steps]}")
    print(f"  当前假设支持步骤: {session.active_hypotheses[0].supporting_step_ids}")
    print(f"  下一步推荐: {session.active_hypotheses[0].next_recommended_step_id}\n")

    if recommendation["action"] == "recommend_step":
        step = recommendation["step"]
        print(f"推荐步骤:")
        print(f"  Step ID: {step.step_id}")
        print(f"  观察目标: {step.observed_fact}\n")

        # 验证：不应该推荐 DB-018_step_1（与 DB-001_step_1 语义相似）
        assert step.step_id != "DB-018_step_1", (
            f"语义去重失败！推荐了与已执行步骤相似的步骤。\n"
            f"已执行: DB-001_step_1 (检查 IO)\n"
            f"被推荐: {step.step_id} ({step.observed_fact})"
        )

        print("[OK] 语义去重成功：跳过了与已执行步骤相似的 DB-018_step_1")
        print(f"[OK] 推荐了不同的步骤: {step.step_id}")
    else:
        print(f"推荐动作: {recommendation['action']}")


if __name__ == "__main__":
    test_semantic_deduplication()
    print("\n" + "=" * 50)
    print("语义去重测试通过！")
    print("=" * 50)
