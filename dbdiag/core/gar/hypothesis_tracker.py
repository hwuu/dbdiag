"""多假设追踪器

维护并行的根因假设，动态计算置信度
"""
from typing import List, Set, Dict, Optional
from collections import defaultdict

from dbdiag.models import SessionState, Hypothesis, Phenomenon
from dbdiag.core.gar.retriever import PhenomenonRetriever
from dbdiag.dao import TicketDAO, TicketPhenomenonDAO, PhenomenonRootCauseDAO
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.config import RecommenderConfig


class PhenomenonHypothesisTracker:
    """基于现象的假设追踪器

    从 phenomena 和 ticket_phenomena 关联表中检索根因假设。
    """

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService = None,
        progress_callback: Optional[callable] = None,
        recommender_config: Optional[RecommenderConfig] = None,
    ):
        """
        初始化假设追踪器

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务实例（单例）
            embedding_service: Embedding 服务实例（单例，可选）
            progress_callback: 进度回调函数，签名为 callback(message: str)
            recommender_config: 推荐引擎配置
        """
        self.db_path = db_path
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self.progress_callback = progress_callback
        self.config = recommender_config or RecommenderConfig()
        self.retriever = PhenomenonRetriever(db_path, embedding_service)
        self._ticket_dao = TicketDAO(db_path)
        self._ticket_phenomenon_dao = TicketPhenomenonDAO(db_path)
        self._phenomenon_root_cause_dao = PhenomenonRootCauseDAO(db_path)

    def _report_progress(self, message: str) -> None:
        """报告进度"""
        if self.progress_callback:
            self.progress_callback(message)

    def update_hypotheses(
        self,
        session: SessionState,
    ) -> SessionState:
        """
        更新会话的假设列表 (基于 confirmed_phenomena)

        Args:
            session: 当前会话状态

        Returns:
            更新后的会话状态
        """
        # 1. 检索可能的根因（基于现象和 ticket 关联）
        self._report_progress("检索根因候选...")
        root_cause_candidates = self._retrieve_root_cause_candidates(session)

        # 2. 为每个根因构建假设
        hypotheses = []
        total_candidates = len(root_cause_candidates)
        denied_ids = set(session.denied_phenomenon_ids)
        for idx, (root_cause_id, supporting_data) in enumerate(root_cause_candidates.items(), 1):
            # 显示评估进度
            self._report_progress(f"评估假设 ({idx}/{total_candidates}): {root_cause_id}")

            phenomena = supporting_data["phenomena"]
            ticket_ids = supporting_data["ticket_ids"]

            # 计算置信度（基于 confirmed_phenomena 和 denied_phenomena）
            confidence = self._compute_confidence(
                root_cause_id=root_cause_id,
                supporting_phenomena=phenomena,
                confirmed_phenomena=session.confirmed_phenomena,
                denied_phenomenon_ids=denied_ids,
            )

            # 识别缺失的现象
            missing_phenomena = self._identify_missing_phenomena(
                supporting_phenomena=phenomena,
                confirmed_phenomena=session.confirmed_phenomena,
            )

            # 推荐下一个现象
            next_phenomenon_id = self._recommend_next_phenomenon(
                supporting_phenomena=phenomena,
                confirmed_phenomenon_ids={
                    p.phenomenon_id for p in session.confirmed_phenomena
                },
            )

            hypotheses.append(
                Hypothesis(
                    root_cause_id=root_cause_id,
                    confidence=confidence,
                    missing_phenomena=missing_phenomena,
                    supporting_phenomenon_ids=[p.phenomenon_id for p in phenomena],
                    supporting_ticket_ids=ticket_ids,
                    next_recommended_phenomenon_id=next_phenomenon_id,
                )
            )

        # 3. 保留 Top-3 假设
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        # 假设排他性处理
        if len(hypotheses) > 1 and hypotheses[0].confidence > 0.45:
            confidence_gap = hypotheses[0].confidence - hypotheses[1].confidence
            if confidence_gap > 0.04:
                penalty_factor = 0.7
                for i in range(1, len(hypotheses)):
                    hypotheses[i] = Hypothesis(
                        root_cause_id=hypotheses[i].root_cause_id,
                        confidence=hypotheses[i].confidence * penalty_factor,
                        missing_phenomena=hypotheses[i].missing_phenomena,
                        supporting_phenomenon_ids=hypotheses[i].supporting_phenomenon_ids,
                        supporting_ticket_ids=hypotheses[i].supporting_ticket_ids,
                        next_recommended_phenomenon_id=hypotheses[i].next_recommended_phenomenon_id,
                    )

        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        session.active_hypotheses = hypotheses[:self.config.hypothesis_top_k]

        return session

    def _retrieve_root_cause_candidates(
        self,
        session: SessionState,
    ) -> Dict[str, Dict]:
        """
        检索根因候选

        Args:
            session: 会话状态

        Returns:
            {根因: {"phenomena": [...], "ticket_ids": [...]}}
        """
        # 从 session 读取混合模式候选现象
        boost_phenomenon_ids = set(session.hybrid_candidate_phenomenon_ids)

        # 构建查询上下文（只用 user_problem，保持稳定）
        query_context = session.user_problem

        # 检索相关现象（不排除已确认的，保持假设稳定性）
        retrieved_phenomena = self.retriever.retrieve(
            query=query_context,
            top_k=20,
            excluded_phenomenon_ids=set(),  # 不排除任何现象
        )

        root_cause_map = defaultdict(lambda: {"phenomena": [], "ticket_ids": set(), "boosted": False})

        for phenomenon, score in retrieved_phenomena:
            # 查找关联的 tickets（使用 DAO）
            ticket_rows = self._ticket_dao.get_by_phenomenon_id(phenomenon.phenomenon_id)

            for row in ticket_rows:
                root_cause_id = row["root_cause_id"]
                ticket_id = row["ticket_id"]

                root_cause_map[root_cause_id]["phenomena"].append(phenomenon)
                root_cause_map[root_cause_id]["ticket_ids"].add(ticket_id)

                # 标记是否来自混合模式增强
                if phenomenon.phenomenon_id in boost_phenomenon_ids:
                    root_cause_map[root_cause_id]["boosted"] = True

        # 混合模式：补充候选现象（可能检索没召回）
        if boost_phenomenon_ids:
            from dbdiag.dao import PhenomenonDAO
            phenomenon_dao = PhenomenonDAO(self.db_path)
            for pid in boost_phenomenon_ids:
                row_dict = phenomenon_dao.get_by_id(pid)
                if row_dict:
                    phenomenon = phenomenon_dao.dict_to_model(row_dict)
                    ticket_rows = self._ticket_dao.get_by_phenomenon_id(pid)
                    for row in ticket_rows:
                        root_cause_id = row["root_cause_id"]
                        ticket_id = row["ticket_id"]
                        # 避免重复添加
                        existing_pids = {p.phenomenon_id for p in root_cause_map[root_cause_id]["phenomena"]}
                        if pid not in existing_pids:
                            root_cause_map[root_cause_id]["phenomena"].append(phenomenon)
                        root_cause_map[root_cause_id]["ticket_ids"].add(ticket_id)
                        root_cause_map[root_cause_id]["boosted"] = True

        # 转换 set 为 list
        for root_cause in root_cause_map:
            root_cause_map[root_cause]["ticket_ids"] = list(
                root_cause_map[root_cause]["ticket_ids"]
            )

        return dict(root_cause_map)

    def _compute_confidence(
        self,
        root_cause_id: str,
        supporting_phenomena: List[Phenomenon],
        confirmed_phenomena: List,
        denied_phenomenon_ids: Set[str] = None,
    ) -> float:
        """
        计算假设的置信度 (基于 confirmed_phenomena 和 denied_phenomena)

        Args:
            root_cause_id: 根因 ID
            supporting_phenomena: 支持该根因的现象
            confirmed_phenomena: 已确认现象
            denied_phenomenon_ids: 已否定的现象 ID 集合

        Returns:
            置信度（0-1）
        """
        if not supporting_phenomena:
            return 0.0

        denied_phenomenon_ids = denied_phenomenon_ids or set()

        # 1. 现象确认进度（权重 60%）
        # 改进：查询数据库找出该根因关联的所有现象，而不是只看 supporting_phenomena
        confirmed_ids = {p.phenomenon_id for p in confirmed_phenomena}

        # 查询该根因关联的所有现象 ID
        related_phenomenon_ids = self._get_phenomena_for_root_cause(root_cause_id)

        # 计算确认的现象中有多少与该根因相关
        confirmed_relevant_count = len(confirmed_ids & related_phenomenon_ids)

        # 计算否定的现象中有多少与该根因相关
        denied_relevant_count = len(denied_phenomenon_ids & related_phenomenon_ids)

        # 进度 = 确认的相关现象数 / 该根因的总现象数（至少1）
        total_for_root_cause = max(len(related_phenomenon_ids), 1)
        progress = confirmed_relevant_count / total_for_root_cause

        # 2. 根因流行度（权重 20%）- 支持该根因的现象越多，流行度越高
        frequency_score = min(len(supporting_phenomena) / 5, 1.0)

        # 3. 基础相关性（权重 20%）- 当有确认时给满分
        relevance_score = 1.0 if confirmed_relevant_count > 0 else 0.5

        confidence = (
            0.6 * progress
            + 0.2 * frequency_score
            + 0.2 * relevance_score
        )

        # 4. 否定惩罚：每个被否定的相关现象降低 15% 置信度
        if denied_relevant_count > 0:
            denial_penalty = denied_relevant_count * 0.15
            confidence = confidence * (1 - denial_penalty)

        return min(max(confidence, 0.0), 1.0)

    def _get_phenomena_for_root_cause(self, root_cause_id: str) -> Set[str]:
        """
        获取与某个根因关联的所有现象 ID

        Args:
            root_cause_id: 根因 ID

        Returns:
            现象 ID 集合
        """
        return self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(root_cause_id)

    def _identify_missing_phenomena(
        self,
        supporting_phenomena: List[Phenomenon],
        confirmed_phenomena: List,
    ) -> List[str]:
        """
        识别缺失的关键现象

        Args:
            supporting_phenomena: 支持该根因的现象
            confirmed_phenomena: 已确认现象

        Returns:
            缺失现象描述列表
        """
        confirmed_ids = {p.phenomenon_id for p in confirmed_phenomena}
        missing = []

        for p in supporting_phenomena[:5]:
            if p.phenomenon_id not in confirmed_ids:
                missing.append(p.description)

        return missing[:3]

    def _recommend_next_phenomenon(
        self,
        supporting_phenomena: List[Phenomenon],
        confirmed_phenomenon_ids: Set[str],
    ) -> Optional[str]:
        """
        推荐下一个要确认的现象

        Args:
            supporting_phenomena: 支持该根因的现象
            confirmed_phenomenon_ids: 已确认的现象 ID

        Returns:
            推荐的现象 ID
        """
        for p in supporting_phenomena:
            if p.phenomenon_id not in confirmed_phenomenon_ids:
                return p.phenomenon_id

        return None
