"""下一步推荐引擎

基于当前假设状态决定下一步行动
"""
import sqlite3
import json
from typing import Optional, List, Dict
from collections import defaultdict

from dbdiag.models.session import SessionState, Hypothesis
from dbdiag.models.phenomenon import Phenomenon
from dbdiag.services.llm_service import LLMService


class PhenomenonRecommendationEngine:
    """基于现象的推荐引擎

    使用 phenomena 表进行下一步推荐。
    """

    def __init__(self, db_path: str, llm_service: LLMService):
        """
        初始化推荐引擎

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务实例（单例）
        """
        self.db_path = db_path
        self.llm_service = llm_service

    def recommend_next_action(
        self, session: SessionState
    ) -> Dict[str, any]:
        """
        推荐下一步行动（批量推荐多个现象）

        Args:
            session: 会话状态

        Returns:
            推荐动作字典 {"action": "...", "phenomena": [...], "reason": "..."}
        """
        if not session.active_hypotheses:
            return self._ask_for_initial_info(session)

        top_hypothesis = session.active_hypotheses[0]

        # 阶段 1: 高置信度 -> 确认根因（阈值 80%）
        if top_hypothesis.confidence >= 0.80:
            return self._generate_root_cause_confirmation(session, top_hypothesis)

        # 阶段 2 & 3: 收集多个现象进行批量推荐
        phenomena_to_recommend = self._collect_phenomena_for_recommendation(
            session, max_count=3
        )

        if phenomena_to_recommend:
            return self._generate_phenomena_recommendation(session, phenomena_to_recommend)

        # 阶段 4: 没有更多现象可推荐，但置信度中等 -> 也确认根因
        if top_hypothesis.confidence >= 0.50:
            return self._generate_root_cause_confirmation(session, top_hypothesis)

        # 兜底：询问关键信息
        return self._ask_for_key_symptom(session, top_hypothesis)

    def _ask_for_initial_info(self, session: SessionState) -> Dict:
        """询问初始信息"""
        return {
            "action": "ask_initial_info",
            "message": "请描述您遇到的数据库问题，包括具体症状和表现。",
        }

    def _generate_root_cause_confirmation(
        self, session: SessionState, hypothesis: Hypothesis
    ) -> Dict:
        """生成根因确认响应"""
        return {
            "action": "confirm_root_cause",
            "root_cause": hypothesis.root_cause,
            "confidence": hypothesis.confidence,
            "supporting_phenomenon_ids": hypothesis.supporting_phenomenon_ids,
            "supporting_ticket_ids": hypothesis.supporting_ticket_ids,
            "message": f"根因已定位：{hypothesis.root_cause} (置信度: {hypothesis.confidence:.0%})",
        }

    def _collect_phenomena_for_recommendation(
        self, session: SessionState, max_count: int = 3
    ) -> List[Dict]:
        """
        收集多个现象进行批量推荐

        策略：
        1. 从每个活跃假设中收集未确认/未否定的现象
        2. 按假设置信度权重排序（与高置信度假设相关的现象优先）
        3. 去重并返回 top-N

        Args:
            session: 会话状态
            max_count: 最大推荐数量

        Returns:
            现象信息列表，每项包含 phenomenon 和 related_hypotheses
        """
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}
        denied_ids = set(session.denied_phenomenon_ids)  # 排除被否定的现象

        # 收集所有候选现象及其权重
        phenomenon_scores: Dict[str, Dict] = {}

        for hyp in session.active_hypotheses[:5]:  # 考虑更多假设
            for phenomenon_id in hyp.supporting_phenomenon_ids:
                if phenomenon_id in confirmed_ids:
                    continue  # 跳过已确认的
                if phenomenon_id in denied_ids:
                    continue  # 跳过被否定的

                if phenomenon_id not in phenomenon_scores:
                    phenomenon = self._get_phenomenon_by_id(phenomenon_id)
                    if phenomenon:
                        phenomenon_scores[phenomenon_id] = {
                            "phenomenon": phenomenon,
                            "weight": 0.0,
                            "max_confidence": 0.0,  # 关联假设的最高置信度
                            "hypothesis_count": 0,
                            "related_hypotheses": [],  # 关联的假设
                        }

                if phenomenon_id in phenomenon_scores:
                    # 权重 = 假设置信度累加
                    phenomenon_scores[phenomenon_id]["weight"] += hyp.confidence
                    phenomenon_scores[phenomenon_id]["hypothesis_count"] += 1
                    # 记录最高置信度
                    phenomenon_scores[phenomenon_id]["max_confidence"] = max(
                        phenomenon_scores[phenomenon_id]["max_confidence"],
                        hyp.confidence
                    )
                    # 记录关联的假设
                    phenomenon_scores[phenomenon_id]["related_hypotheses"].append({
                        "root_cause": hyp.root_cause,
                        "confidence": hyp.confidence,
                    })

        # 排序：优先推荐与高置信度假设相关的现象
        ranked = sorted(
            phenomenon_scores.values(),
            key=lambda x: (
                x["max_confidence"],    # 关联假设的最高置信度优先
                x["weight"],            # 权重高的优先（被多个假设支持）
            ),
            reverse=True,
        )

        return ranked[:max_count]

    def _find_discriminating_phenomenon(
        self,
        hypothesis1: Hypothesis,
        hypothesis2: Optional[Hypothesis],
        session: SessionState,
    ) -> Optional[Phenomenon]:
        """
        找到能区分两个假设的现象

        Args:
            hypothesis1: 假设 1
            hypothesis2: 假设 2（可选）
            session: 会话状态

        Returns:
            区分性现象
        """
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}

        if not hypothesis2:
            return self._get_next_unconfirmed_phenomenon(hypothesis1, session)

        # 找到 hypothesis1 独有的现象
        unique_phenomena_h1 = set(hypothesis1.supporting_phenomenon_ids) - set(
            hypothesis2.supporting_phenomenon_ids
        )

        # 选择还未确认的现象
        for phenomenon_id in unique_phenomena_h1:
            if phenomenon_id not in confirmed_ids:
                phenomenon = self._get_phenomenon_by_id(phenomenon_id)
                if phenomenon and not self._is_similar_to_confirmed(phenomenon, session):
                    return phenomenon

        return self._get_next_unconfirmed_phenomenon(hypothesis1, session)

    def _find_common_recommended_phenomena(
        self, hypotheses: List[Hypothesis], session: SessionState
    ) -> List[Phenomenon]:
        """
        从多个假设中找到共同推荐的现象（投票）

        Args:
            hypotheses: 假设列表
            session: 会话状态

        Returns:
            按投票数排序的现象列表
        """
        phenomenon_votes = defaultdict(lambda: {"phenomenon": None, "weighted_votes": 0.0})

        for hyp in hypotheses:
            next_phenomenon = self._get_next_unconfirmed_phenomenon(hyp, session)
            if not next_phenomenon:
                continue

            phenomenon_id = next_phenomenon.phenomenon_id

            if phenomenon_votes[phenomenon_id]["phenomenon"] is None:
                phenomenon_votes[phenomenon_id]["phenomenon"] = next_phenomenon

            phenomenon_votes[phenomenon_id]["weighted_votes"] += hyp.confidence

        ranked = sorted(
            phenomenon_votes.values(),
            key=lambda x: x["weighted_votes"],
            reverse=True,
        )

        return [v["phenomenon"] for v in ranked if v["phenomenon"]]

    def _get_next_unconfirmed_phenomenon(
        self, hypothesis: Hypothesis, session: SessionState
    ) -> Optional[Phenomenon]:
        """获取假设的下一个未确认现象"""
        confirmed_ids = {p.phenomenon_id for p in session.confirmed_phenomena}

        if hypothesis.next_recommended_phenomenon_id:
            if hypothesis.next_recommended_phenomenon_id not in confirmed_ids:
                phenomenon = self._get_phenomenon_by_id(hypothesis.next_recommended_phenomenon_id)
                if phenomenon and not self._is_similar_to_confirmed(phenomenon, session):
                    return phenomenon

        for phenomenon_id in hypothesis.supporting_phenomenon_ids:
            if phenomenon_id not in confirmed_ids:
                phenomenon = self._get_phenomenon_by_id(phenomenon_id)
                if phenomenon and not self._is_similar_to_confirmed(phenomenon, session):
                    return phenomenon

        return None

    def _is_similar_to_confirmed(
        self, candidate: Phenomenon, session: SessionState
    ) -> bool:
        """
        判断候选现象是否与已确认现象语义相似

        Args:
            candidate: 候选现象
            session: 会话状态

        Returns:
            True 如果相似，False 否则
        """
        if not session.confirmed_phenomena:
            return False

        confirmed_descriptions = []
        for cp in session.confirmed_phenomena:
            phenomenon = self._get_phenomenon_by_id(cp.phenomenon_id)
            if phenomenon:
                confirmed_descriptions.append(phenomenon.description)

        if not confirmed_descriptions:
            return False

        system_prompt = """你是一个数据库诊断专家。判断两个现象是否语义相似。

语义相似的标准：
1. 检查的是同一个系统指标或现象
2. 即使具体的 SQL 不同，但目的相同
3. 即使阈值不同，但检查的对象相同

输出格式: 只输出 "yes" 或 "no"
"""

        user_prompt = f"""候选现象: {candidate.description}

已确认现象:
{chr(10).join([f"- {desc}" for desc in confirmed_descriptions])}

候选现象是否与任一已确认现象语义相似？"""

        try:
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=system_prompt,
            )
            return response.strip().lower() in ["yes", "是"]

        except Exception:
            candidate_keywords = set(candidate.description.lower().split())
            for desc in confirmed_descriptions:
                desc_keywords = set(desc.lower().split())
                overlap = len(candidate_keywords & desc_keywords)
                if overlap >= len(candidate_keywords) * 0.5:
                    return True
            return False

    def _get_phenomenon_by_id(self, phenomenon_id: str) -> Optional[Phenomenon]:
        """根据 ID 获取现象"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    phenomenon_id, description, observation_method,
                    source_anomaly_ids, cluster_size
                FROM phenomena
                WHERE phenomenon_id = ?
                """,
                (phenomenon_id,),
            )
            row = cursor.fetchone()

            if row:
                source_ids = row["source_anomaly_ids"]
                if isinstance(source_ids, str):
                    source_ids = json.loads(source_ids)

                return Phenomenon(
                    phenomenon_id=row["phenomenon_id"],
                    description=row["description"],
                    observation_method=row["observation_method"],
                    source_anomaly_ids=source_ids,
                    cluster_size=row["cluster_size"],
                )

            return None
        finally:
            conn.close()

    def _generate_phenomena_recommendation(
        self, session: SessionState, phenomena_info: List[Dict]
    ) -> Dict:
        """生成批量现象推荐响应（包含关联假设信息）"""
        phenomena = [item["phenomenon"] for item in phenomena_info]

        # 为每个现象附加关联假设信息
        phenomena_with_reasons = []
        for item in phenomena_info:
            phenomenon = item["phenomenon"]
            related_hypotheses = item.get("related_hypotheses", [])

            # 构建原因说明
            if related_hypotheses:
                # 取置信度最高的假设作为主要原因
                top_hyp = max(related_hypotheses, key=lambda h: h["confidence"])
                reason = f"可能与「{top_hyp['root_cause']}」相关"
            else:
                reason = ""

            phenomena_with_reasons.append({
                "phenomenon": phenomenon,
                "reason": reason,
                "related_hypotheses": related_hypotheses,
            })

        return {
            "action": "recommend_phenomenon",
            "phenomena": phenomena,  # 保持兼容
            "phenomena_with_reasons": phenomena_with_reasons,  # 新增：包含原因
            "phenomenon": phenomena[0] if phenomena else None,  # 兼容旧接口
            "message": f"建议确认以下 {len(phenomena)} 个现象",
        }

    def _generate_phenomenon_recommendation(
        self, session: SessionState, phenomenon: Phenomenon
    ) -> Dict:
        """生成现象推荐响应"""
        return {
            "action": "recommend_phenomenon",
            "phenomenon": phenomenon,
            "message": f"建议确认以下现象：\n\n现象描述：{phenomenon.description}\n\n观察方法：\n{phenomenon.observation_method}",
        }

    def _ask_for_key_symptom(
        self, session: SessionState, hypothesis: Hypothesis
    ) -> Dict:
        """询问关键症状"""
        if hypothesis.missing_facts:
            missing_fact = hypothesis.missing_facts[0]
            return {
                "action": "ask_symptom",
                "message": f"请确认是否观察到以下现象：{missing_fact}",
            }

        return {
            "action": "ask_general",
            "message": "请提供更多关于问题的详细信息。",
        }
