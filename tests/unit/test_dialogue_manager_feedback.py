"""测试 GARDialogueManager 用户反馈处理逻辑"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from dbdiag.models import SessionState, RecommendedPhenomenon, Phenomenon


class TestMarkConfirmedPhenomenaFromFeedback:
    """测试 _mark_confirmed_phenomena_from_feedback 方法"""

    @pytest.fixture
    def mock_dialogue_manager(self):
        """创建 mock dialogue manager"""
        with patch('dbdiag.core.gar.dialogue_manager.SessionService'), \
             patch('dbdiag.core.gar.dialogue_manager.PhenomenonHypothesisTracker'), \
             patch('dbdiag.core.gar.dialogue_manager.PhenomenonRecommendationEngine'), \
             patch('dbdiag.core.gar.dialogue_manager.ResponseGenerator'), \
             patch('dbdiag.core.gar.dialogue_manager.PhenomenonDAO'):

            from dbdiag.core.gar.dialogue_manager import GARDialogueManager

            mock_llm = Mock()
            mock_embedding = Mock()

            manager = GARDialogueManager(
                db_path=":memory:",
                llm_service=mock_llm,
                embedding_service=mock_embedding,
            )

            # Mock _get_phenomenon_by_id
            def mock_get_phenomenon(pid):
                return Phenomenon(
                    phenomenon_id=pid,
                    description=f"描述 {pid}",
                    observation_method="观察方法",
                    source_anomaly_ids=[],
                    cluster_size=1,
                )
            manager._get_phenomenon_by_id = mock_get_phenomenon

            yield manager

    @pytest.fixture
    def session_with_recommended(self):
        """创建带有推荐现象的会话"""
        session = SessionState(
            session_id="test-session",
            user_problem="查询变慢",
        )
        # 添加推荐的现象
        session.recommended_phenomena = [
            RecommendedPhenomenon(phenomenon_id="P-0001", round_number=1),
            RecommendedPhenomenon(phenomenon_id="P-0002", round_number=1),
            RecommendedPhenomenon(phenomenon_id="P-0003", round_number=1),
        ]
        return session

    def test_batch_format_confirm_deny(self, mock_dialogue_manager, session_with_recommended):
        """测试批量确认/否定格式: '1确认 2否定 3确认'"""
        new_obs = mock_dialogue_manager._mark_confirmed_phenomena_from_feedback(
            "1确认 2否定 3确认",
            session_with_recommended
        )

        # 检查确认/否定结果
        assert len(session_with_recommended.confirmed_phenomena) == 2
        assert len(session_with_recommended.denied_phenomena) == 1

        confirmed_ids = {p.phenomenon_id for p in session_with_recommended.confirmed_phenomena}
        assert "P-0001" in confirmed_ids
        assert "P-0003" in confirmed_ids

        denied_ids = {p.phenomenon_id for p in session_with_recommended.denied_phenomena}
        assert "P-0002" in denied_ids

        # 简单格式不返回新观察
        assert new_obs == []

    def test_simple_confirm_all(self, mock_dialogue_manager, session_with_recommended):
        """测试简单确认格式: '确认'"""
        new_obs = mock_dialogue_manager._mark_confirmed_phenomena_from_feedback(
            "确认",
            session_with_recommended
        )

        assert len(session_with_recommended.confirmed_phenomena) == 3
        assert len(session_with_recommended.denied_phenomena) == 0
        assert new_obs == []

    def test_simple_deny_all(self, mock_dialogue_manager, session_with_recommended):
        """测试简单否定格式: '全否定'"""
        new_obs = mock_dialogue_manager._mark_confirmed_phenomena_from_feedback(
            "全否定",
            session_with_recommended
        )

        assert len(session_with_recommended.confirmed_phenomena) == 0
        assert len(session_with_recommended.denied_phenomena) == 3
        assert new_obs == []

    def test_natural_language_llm_extraction(self, mock_dialogue_manager, session_with_recommended):
        """测试自然语言使用 LLM 提取"""
        # Mock LLM 返回
        mock_dialogue_manager.llm_service.generate_simple.return_value = '''
{
  "feedback": {
    "P-0001": "confirmed",
    "P-0002": "denied",
    "P-0003": "unknown"
  },
  "new_observations": ["发现很多慢查询", "连接数较高"]
}
'''

        new_obs = mock_dialogue_manager._mark_confirmed_phenomena_from_feedback(
            "IO 正常，索引涨了 6 倍，另外发现很多慢查询",
            session_with_recommended
        )

        # 检查 LLM 被调用
        assert mock_dialogue_manager.llm_service.generate_simple.called

        # 检查确认/否定结果
        assert len(session_with_recommended.confirmed_phenomena) == 1
        assert len(session_with_recommended.denied_phenomena) == 1

        # 检查新观察
        assert len(new_obs) == 2
        assert "发现很多慢查询" in new_obs
        assert "连接数较高" in new_obs

    def test_llm_extraction_with_markdown_codeblock(self, mock_dialogue_manager, session_with_recommended):
        """测试 LLM 返回带 markdown 代码块的 JSON"""
        mock_dialogue_manager.llm_service.generate_simple.return_value = '''```json
{
  "feedback": {
    "P-0001": "confirmed"
  },
  "new_observations": []
}
```'''

        new_obs = mock_dialogue_manager._mark_confirmed_phenomena_from_feedback(
            "wait_io 占比 65%",
            session_with_recommended
        )

        assert len(session_with_recommended.confirmed_phenomena) == 1
        assert new_obs == []

    def test_llm_failure_fallback(self, mock_dialogue_manager, session_with_recommended):
        """测试 LLM 失败时回退到关键词匹配"""
        mock_dialogue_manager.llm_service.generate_simple.side_effect = Exception("LLM error")

        new_obs = mock_dialogue_manager._mark_confirmed_phenomena_from_feedback(
            "IO 正常，观察到一些异常",
            session_with_recommended
        )

        # 回退到关键词匹配，包含 "正常"/"异常" 关键词会确认所有现象
        assert len(session_with_recommended.confirmed_phenomena) == 3
        assert new_obs == []

    def test_empty_pending_phenomena(self, mock_dialogue_manager):
        """测试没有待确认现象时"""
        session = SessionState(
            session_id="test-session",
            user_problem="查询变慢",
        )

        new_obs = mock_dialogue_manager._mark_confirmed_phenomena_from_feedback(
            "1确认",
            session
        )

        assert len(session.confirmed_phenomena) == 0
        assert new_obs == []


class TestSessionStateNewObservations:
    """测试 SessionState 的 new_observations 字段"""

    def test_new_observations_default_empty(self):
        """测试 new_observations 默认为空列表"""
        session = SessionState(
            session_id="test",
            user_problem="问题",
        )
        assert session.new_observations == []

    def test_new_observations_serialization(self):
        """测试 new_observations 序列化/反序列化"""
        session = SessionState(
            session_id="test",
            user_problem="问题",
            new_observations=["观察1", "观察2"],
        )

        data = session.to_dict()
        restored = SessionState.from_dict(data)

        assert restored.new_observations == ["观察1", "观察2"]
