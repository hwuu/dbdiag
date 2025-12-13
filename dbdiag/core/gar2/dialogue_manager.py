"""GAR2 对话管理器

基于观察的诊断推理对话管理器。

主流程：
1. IntentClassifier 识别用户意图 → UserIntent
2. 根据意图类型分发：
   - feedback: ObservationMatcher 匹配 → 更新 Symptom → 计算置信度
   - query: 生成状态总结响应
   - mixed: 先处理 feedback，再生成 query 响应
3. ConfidenceCalculator 图传播 → 根因置信度
4. 决策：高置信度 → 诊断 | 否则 → 推荐现象
"""

import uuid
from typing import Dict, Any, Optional, List, Callable

from dbdiag.core.gar2.models import (
    Observation,
    Symptom,
    HypothesisV2,
    SessionStateV2,
    MatchResult,
)
from dbdiag.core.gar2.observation_matcher import ObservationMatcher
from dbdiag.core.gar2.confidence_calculator import ConfidenceCalculator
from dbdiag.core.intent import IntentClassifier, UserIntent, QueryType
from dbdiag.core.intent.models import IntentType
from dbdiag.dao import PhenomenonDAO, PhenomenonRootCauseDAO, RootCauseDAO, TicketDAO
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService


class GAR2DialogueManager:
    """GAR2 对话管理器

    基于观察的诊断推理引擎。
    """

    # 置信度阈值
    HIGH_CONFIDENCE_THRESHOLD = 0.95
    MEDIUM_CONFIDENCE_THRESHOLD = 0.50

    # 推荐数量
    RECOMMEND_TOP_N = 5

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        progress_callback: Optional[Callable[[str], None]] = None,
        match_threshold: float = 0.75,
    ):
        """初始化

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务
            embedding_service: Embedding 服务
            progress_callback: 进度回调函数
            match_threshold: 观察匹配阈值
        """
        self.db_path = db_path
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self._progress_callback = progress_callback

        # 子模块
        self.intent_classifier = IntentClassifier(llm_service)
        self.observation_matcher = ObservationMatcher(
            db_path, embedding_service, match_threshold=match_threshold
        )
        self.confidence_calculator = ConfidenceCalculator(db_path)

        # DAO
        self._phenomenon_dao = PhenomenonDAO(db_path)
        self._phenomenon_root_cause_dao = PhenomenonRootCauseDAO(db_path)
        self._root_cause_dao = RootCauseDAO(db_path)
        self._ticket_dao = TicketDAO(db_path)

        # 当前会话
        self.session: Optional[SessionStateV2] = None

    def _report_progress(self, message: str) -> None:
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(message)

    def start_conversation(self, user_input: str) -> Dict[str, Any]:
        """开始新对话

        Args:
            user_input: 用户输入

        Returns:
            响应字典
        """
        # 创建新会话
        self.session = SessionStateV2(
            session_id=str(uuid.uuid4()),
            user_problem="",  # 稍后根据意图设置
        )
        self.session.turn_count = 1

        self._report_progress("分析用户输入...")

        # 意图分类（第一轮没有推荐现象）
        intent = self.intent_classifier.classify(user_input)

        self._report_progress(
            f"[DEBUG] 第一轮意图: type={intent.intent_type.value}, "
            f"new_obs={intent.new_observations}, query={intent.query_type}"
        )

        # 1. 纯查询意图：引导用户描述问题
        if intent.intent_type == IntentType.QUERY:
            return self._guide_to_describe_problem(
                "尚未开始诊断。请描述您遇到的数据库问题，例如：查询变慢、连接超时等。"
            )

        # 2. feedback/mixed 意图：检查是否有实质内容
        has_observations = bool(intent.new_observations)

        if not has_observations:
            # 没有实质观察内容，引导用户
            return self._guide_to_describe_problem(
                "请描述您遇到的具体问题或观察到的现象。\n"
                "例如：\n"
                "- \"查询变慢，原来几秒现在要半分钟\"\n"
                "- \"数据库连接经常超时\"\n"
                "- \"CPU 使用率很高\""
            )

        # 3. 有实质观察内容，正常处理
        # 记录用户问题（取第一个观察作为主问题）
        self.session.user_problem = intent.new_observations[0]

        self._report_progress("[DEBUG] 有效输入，走 _process_new_observations 分支")
        return self._process_new_observations(intent.new_observations)

    def _guide_to_describe_problem(self, message: str) -> Dict[str, Any]:
        """返回引导用户描述问题的响应"""
        return {
            "action": "guide",
            "message": message,
            "session": self.session,
        }

    def continue_conversation(self, user_message: str) -> Dict[str, Any]:
        """继续对话

        Args:
            user_message: 用户输入

        Returns:
            响应字典
        """
        if not self.session:
            return {"action": "error", "message": "会话未初始化"}

        self.session.turn_count += 1

        # 1. 意图分类
        self._report_progress("解析用户意图...")
        self._report_progress(f"[DEBUG] 当前推荐列表: {self.session.recommended_phenomenon_ids}")

        phenomenon_descriptions = self._get_phenomenon_descriptions(
            self.session.recommended_phenomenon_ids
        )
        intent = self.intent_classifier.classify(
            user_message,
            self.session.recommended_phenomenon_ids,
            phenomenon_descriptions,
        )

        self._report_progress(
            f"[DEBUG] 意图: type={intent.intent_type.value}, "
            f"confirmations={intent.confirmations}, denials={intent.denials}, "
            f"new_obs={intent.new_observations}, query={intent.query_type}"
        )

        # 2. 根据意图类型路由
        if intent.intent_type == IntentType.QUERY:
            # 纯查询：直接返回状态总结
            return self._generate_summary_response(intent.query_type)

        # 3. 处理反馈（FEEDBACK 或 MIXED）
        for phenomenon_id in intent.confirmations:
            self._handle_confirmation(phenomenon_id)

        for phenomenon_id in intent.denials:
            self._handle_denial(phenomenon_id)

        # 4. 处理新观察
        if intent.new_observations:
            self._report_progress("[DEBUG] 走 _process_new_observations 分支")
            result = self._process_new_observations(intent.new_observations)
        else:
            # 没有新观察，重新计算置信度并决策
            self._report_progress("[DEBUG] 走 _calculate_and_decide 分支")
            result = self._calculate_and_decide()

        # 5. MIXED 意图：附加查询响应
        if intent.intent_type == IntentType.MIXED and intent.query_type:
            summary = self._generate_summary_response(intent.query_type)
            result["query_response"] = summary

        return result

    def _handle_confirmation(self, phenomenon_id: str) -> None:
        """处理现象确认

        将确认的现象作为观察添加到症状中。
        """
        phenomenon = self._get_phenomenon_by_id(phenomenon_id)
        if phenomenon:
            self.session.symptom.add_observation(
                description=phenomenon.get("description", phenomenon_id),
                source="confirmed",
                matched_phenomenon_id=phenomenon_id,
                match_score=1.0,  # 确认推荐的现象，完全匹配
            )
            self._report_progress(f"已确认: {phenomenon.get('description', phenomenon_id)[:30]}...")

    def _handle_denial(self, phenomenon_id: str) -> None:
        """处理现象否认

        将否认的现象及其关联根因加入阻塞列表。
        """
        related_root_causes = self.confidence_calculator.get_related_root_causes(
            phenomenon_id
        )
        self.session.symptom.block_phenomenon(phenomenon_id, related_root_causes)
        self._report_progress(f"已排除: {phenomenon_id} 及其关联的 {len(related_root_causes)} 个根因")

    def _process_new_observations(self, observations: List[str]) -> Dict[str, Any]:
        """处理新观察

        1. 多目标匹配（phenomena, root_causes, tickets）
        2. 添加到症状
        3. 累积 match_result 到 session（只累积 best 匹配）
        4. 计算置信度并决策
        """
        self._report_progress("匹配观察到现象、根因、工单...")

        # 聚合本轮所有观察的匹配结果（只保留 best 匹配）
        aggregated_match = MatchResult()
        has_new_observation = False

        for obs_text in observations:
            match_result = self.observation_matcher.match_all(obs_text)

            # 只聚合 best 匹配，不聚合 top-5 的所有匹配
            best_phenomenon = match_result.best_phenomenon
            if best_phenomenon:
                aggregated_match.phenomena.append(best_phenomenon)

            # root_cause 和 ticket 也只取 best（去重在 calculator 中处理）
            if match_result.root_causes:
                aggregated_match.root_causes.append(match_result.root_causes[0])
            if match_result.tickets:
                aggregated_match.tickets.append(match_result.tickets[0])

            # 基于最佳现象匹配添加到症状
            if best_phenomenon:
                added = self.session.symptom.add_observation(
                    description=obs_text,
                    source="user_input",
                    matched_phenomenon_id=best_phenomenon.phenomenon_id,
                    match_score=best_phenomenon.score,
                )
                if added:
                    has_new_observation = True
                    self._report_progress(
                        f"匹配成功: {obs_text[:20]}... → {best_phenomenon.phenomenon_id} ({best_phenomenon.score:.0%})"
                    )
                    # 报告其他匹配
                    if match_result.root_causes:
                        self._report_progress(f"  直接匹配根因: {len(match_result.root_causes)} 个")
                    if match_result.tickets:
                        self._report_progress(f"  相似工单: {len(match_result.tickets)} 个")
                else:
                    self._report_progress(f"[DEBUG] 跳过重复观察: {obs_text[:30]}...")
            else:
                # 未匹配现象，但可能有根因或工单匹配
                added = self.session.symptom.add_observation(
                    description=obs_text,
                    source="user_input",
                )
                if added:
                    has_new_observation = True
                    if match_result.root_causes or match_result.tickets:
                        self._report_progress(
                            f"未匹配现象，但匹配到 {len(match_result.root_causes)} 个根因, {len(match_result.tickets)} 个工单"
                        )
                    else:
                        self._report_progress(f"未找到匹配: {obs_text[:30]}...")
                else:
                    self._report_progress(f"[DEBUG] 跳过重复观察: {obs_text[:30]}...")

        # 累积 match_result 到 session
        if has_new_observation and aggregated_match.has_matches:
            if self.session.accumulated_match_result is None:
                self.session.accumulated_match_result = aggregated_match
            else:
                self.session.accumulated_match_result.merge(aggregated_match)
            self._report_progress(
                f"[DEBUG] 累积 match_result: phenomena={len(self.session.accumulated_match_result.phenomena)}, "
                f"root_causes={len(self.session.accumulated_match_result.root_causes)}, "
                f"tickets={len(self.session.accumulated_match_result.tickets)}"
            )

        return self._calculate_and_decide()

    def _calculate_and_decide(self) -> Dict[str, Any]:
        """计算置信度并做出决策

        使用 session.accumulated_match_result 计算置信度。
        """
        self._report_progress("计算根因置信度...")

        # 使用累积的 match_result
        match_result = self.session.accumulated_match_result

        # DEBUG: 显示 match_result 状态
        if match_result and match_result.has_matches:
            self._report_progress(
                f"[DEBUG] 使用累积的 match_result: phenomena={len(match_result.phenomena)}, "
                f"root_causes={len(match_result.root_causes)}, tickets={len(match_result.tickets)}"
            )
            self._report_progress("[DEBUG] 使用 calculate_with_match_result()")
            self.session.hypotheses = self.confidence_calculator.calculate_with_match_result(
                self.session.symptom, match_result,
                debug_callback=self._report_progress
            )
        else:
            self._report_progress("[DEBUG] 无累积 match_result，仅基于 symptom 计算")
            self._report_progress("[DEBUG] 使用 calculate() - 仅基于 symptom")
            self.session.hypotheses = self.confidence_calculator.calculate(
                self.session.symptom
            )

        # DEBUG: 显示 top 假设
        if self.session.hypotheses:
            top3 = self.session.hypotheses[:3]
            for i, h in enumerate(top3, 1):
                desc = self._root_cause_dao.get_description(h.root_cause_id)
                self._report_progress(f"[DEBUG] Top{i}: {h.confidence:.0%} {h.root_cause_id} ({desc[:20]}...)")

        top = self.session.top_hypothesis

        # 决策
        if top and top.confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            self._report_progress("置信度达标，生成诊断报告...")
            return self._generate_diagnosis(top)

        if not self.session.hypotheses:
            return self._ask_for_more_info()

        self._report_progress("推荐下一步观察...")
        return self._generate_recommendation()

    def _generate_diagnosis(self, hypothesis: HypothesisV2) -> Dict[str, Any]:
        """生成诊断结果

        包含：
        - 根因信息
        - 观察到的现象
        - 未确认的现象（需进一步确认）
        - 推导过程（LLM 生成）
        - 参考工单列表
        """
        root_cause = self._root_cause_dao.get_by_id(hypothesis.root_cause_id)
        root_cause_desc = root_cause.get("description", hypothesis.root_cause_id) if root_cause else hypothesis.root_cause_id

        # 1. 收集观察到的现象（带描述）
        observed_phenomena = []
        observed_phenomenon_ids = set()
        for obs in self.session.symptom.observations:
            if obs.matched_phenomenon_id in hypothesis.contributing_phenomena:
                observed_phenomena.append({
                    "phenomenon_id": obs.matched_phenomenon_id,
                    "description": obs.description,
                })
                observed_phenomenon_ids.add(obs.matched_phenomenon_id)

        # 2. 获取未确认的现象
        all_related_phenomena = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
            hypothesis.root_cause_id
        )
        unconfirmed_phenomena = []
        for pid in all_related_phenomena:
            if pid not in observed_phenomenon_ids:
                phenomenon = self._get_phenomenon_by_id(pid)
                if phenomenon:
                    unconfirmed_phenomena.append({
                        "phenomenon_id": pid,
                        "description": phenomenon.get("description", pid),
                        "observation_method": phenomenon.get("observation_method", ""),
                    })

        # 3. LLM 生成推导过程
        reasoning = self._generate_reasoning(
            root_cause_desc,
            [p["description"] for p in observed_phenomena],
        )

        # 4. 获取参考工单（按匹配度排序）
        supporting_tickets = self._get_supporting_tickets(
            hypothesis.root_cause_id,
            observed_phenomenon_ids,
        )

        return {
            "action": "diagnose",
            "root_cause_id": hypothesis.root_cause_id,
            "root_cause": root_cause_desc,
            "confidence": hypothesis.confidence,
            "observed_phenomena": observed_phenomena,
            "unconfirmed_phenomena": unconfirmed_phenomena,
            "reasoning": reasoning,
            "supporting_tickets": supporting_tickets,
            "solution": root_cause.get("solution", "") if root_cause else "",
            "session": self.session,
        }

    def _generate_reasoning(
        self,
        root_cause: str,
        observed_phenomena: List[str],
    ) -> str:
        """使用 LLM 生成推导过程

        Args:
            root_cause: 根因描述
            observed_phenomena: 观察到的现象描述列表

        Returns:
            推导过程文本
        """
        if not observed_phenomena:
            return "无法生成推导过程：缺少观察到的现象。"

        prompt = f"""根据以下观察到的现象，解释为什么可以推导出根因。

## 观察到的现象
{chr(10).join(f"- {p}" for p in observed_phenomena)}

## 根因
{root_cause}

## 要求
1. 简洁说明现象之间的关联
2. 解释这些现象如何指向根因
3. 使用 2-3 句话，不超过 100 字

直接输出推导过程，不要其他内容。"""

        try:
            return self.llm_service.generate(prompt)
        except Exception:
            # LLM 失败时返回默认推导
            return f"根据观察到的 {len(observed_phenomena)} 个现象，综合判断根因为：{root_cause}"

    def _get_supporting_tickets(
        self,
        root_cause_id: str,
        observed_phenomenon_ids: set,
    ) -> List[Dict[str, Any]]:
        """获取参考工单列表

        按与已确认现象的匹配度排序。

        Args:
            root_cause_id: 根因 ID
            observed_phenomenon_ids: 已确认的现象 ID 集合

        Returns:
            工单列表，包含 ticket_id, description, match_count
        """
        # 获取该根因的所有工单
        tickets = self._ticket_dao.get_by_root_cause_id(root_cause_id, limit=100)

        if not tickets or not observed_phenomenon_ids:
            return tickets[:5] if tickets else []

        # 计算每个工单与已确认现象的匹配数
        from dbdiag.dao import TicketPhenomenonDAO
        ticket_phenomenon_dao = TicketPhenomenonDAO(self.db_path)

        ticket_matches = []
        for ticket in tickets:
            ticket_id = ticket["ticket_id"]
            # 获取工单包含的现象
            ticket_phenomena = ticket_phenomenon_dao.get_ticket_phenomena_by_phenomenon
            # 简化：直接查询该工单包含多少已确认现象
            match_count = 0
            for pid in observed_phenomenon_ids:
                associations = ticket_phenomenon_dao.get_ticket_phenomena_by_phenomenon(pid)
                for assoc in associations:
                    if assoc["ticket_id"] == ticket_id:
                        match_count += 1
                        break

            ticket_matches.append({
                "ticket_id": ticket_id,
                "description": ticket.get("description", ""),
                "match_count": match_count,
            })

        # 按匹配数排序
        ticket_matches.sort(key=lambda x: x["match_count"], reverse=True)

        return ticket_matches

    def _generate_recommendation(self) -> Dict[str, Any]:
        """生成推荐现象"""
        # 获取 top 假设关联的现象
        recommended = []
        recommended_ids = []

        for hyp in self.session.hypotheses[:3]:  # Top 3 假设
            # 获取根因描述用于推荐原因
            root_cause = self._root_cause_dao.get_by_id(hyp.root_cause_id)
            root_cause_desc = root_cause.get("description", hyp.root_cause_id) if root_cause else hyp.root_cause_id

            phenomena_ids = self._phenomenon_root_cause_dao.get_phenomena_by_root_cause_id(
                hyp.root_cause_id
            )
            for pid in phenomena_ids:
                # 跳过已匹配、已阻塞的现象
                if pid in self.session.symptom.get_matched_phenomenon_ids():
                    continue
                if self.session.symptom.is_phenomenon_blocked(pid):
                    continue
                if pid in recommended_ids:
                    continue

                phenomenon = self._get_phenomenon_by_id(pid)
                if phenomenon:
                    recommended.append({
                        "phenomenon_id": pid,
                        "description": phenomenon.get("description", ""),
                        "observation_method": phenomenon.get("observation_method", ""),
                        "related_hypothesis": hyp.root_cause_id,
                        "reason": f"与假设\"{root_cause_desc}\"相关",
                    })
                    recommended_ids.append(pid)

                if len(recommended) >= self.RECOMMEND_TOP_N:
                    break

            if len(recommended) >= self.RECOMMEND_TOP_N:
                break

        # 更新会话中的推荐列表
        self.session.recommended_phenomenon_ids = recommended_ids

        return {
            "action": "recommend",
            "hypotheses": self.session.hypotheses,
            "recommendations": recommended,
            "session": self.session,
        }

    def _ask_for_more_info(self) -> Dict[str, Any]:
        """请求更多信息"""
        return {
            "action": "ask_more_info",
            "message": "请提供更多关于问题的详细信息。",
            "session": self.session,
        }

    def _generate_summary_response(self, query_type: QueryType) -> Dict[str, Any]:
        """生成状态总结响应

        根据查询类型返回不同的总结信息。

        Args:
            query_type: 查询类型

        Returns:
            响应字典
        """
        if query_type == QueryType.PROGRESS:
            # 查询诊断进展
            observations = self.session.symptom.observations
            matched_phenomena = self.session.symptom.get_matched_phenomenon_ids()
            blocked_phenomena = list(self.session.symptom.blocked_phenomenon_ids)

            # 获取匹配现象的详细信息
            matched_phenomena_details = []
            for pid in matched_phenomena:
                phenomenon = self._get_phenomenon_by_id(pid)
                if phenomenon:
                    matched_phenomena_details.append({
                        "phenomenon_id": pid,
                        "description": phenomenon.get("description", pid),
                    })

            # 获取 Top 假设的详细信息
            top_hypotheses = []
            for hyp in self.session.hypotheses[:5]:
                root_cause = self._root_cause_dao.get_by_id(hyp.root_cause_id)
                top_hypotheses.append({
                    "root_cause_id": hyp.root_cause_id,
                    "description": root_cause.get("description", hyp.root_cause_id) if root_cause else hyp.root_cause_id,
                    "confidence": hyp.confidence,
                })

            return {
                "action": "summary",
                "query_type": "progress",
                "turn_count": self.session.turn_count,
                "observations_count": len(observations),
                "observations": [obs.description for obs in observations],
                "matched_phenomena_count": len(matched_phenomena),
                "matched_phenomena": matched_phenomena_details,
                "blocked_phenomena_count": len(blocked_phenomena),
                "blocked_phenomena": blocked_phenomena,
                "hypotheses_count": len(self.session.hypotheses),
                "top_hypotheses": top_hypotheses,
                "session": self.session,
            }

        elif query_type == QueryType.CONCLUSION:
            # 查询当前结论
            top = self.session.top_hypothesis
            if top and top.confidence >= self.MEDIUM_CONFIDENCE_THRESHOLD:
                root_cause = self._root_cause_dao.get_by_id(top.root_cause_id)
                return {
                    "action": "summary",
                    "query_type": "conclusion",
                    "has_conclusion": True,
                    "root_cause_id": top.root_cause_id,
                    "root_cause": root_cause.get("description", top.root_cause_id) if root_cause else top.root_cause_id,
                    "confidence": top.confidence,
                    "confidence_level": "high" if top.confidence >= self.HIGH_CONFIDENCE_THRESHOLD else "medium",
                    "session": self.session,
                }
            else:
                return {
                    "action": "summary",
                    "query_type": "conclusion",
                    "has_conclusion": False,
                    "message": "当前信息不足，尚无明确结论。请继续提供更多观察信息。",
                    "top_hypothesis": {
                        "root_cause_id": top.root_cause_id,
                        "confidence": top.confidence,
                    } if top else None,
                    "session": self.session,
                }

        elif query_type == QueryType.HYPOTHESES:
            # 查询假设列表
            hypotheses_info = []
            for hyp in self.session.hypotheses[:5]:  # Top 5
                root_cause = self._root_cause_dao.get_by_id(hyp.root_cause_id)
                hypotheses_info.append({
                    "root_cause_id": hyp.root_cause_id,
                    "description": root_cause.get("description", hyp.root_cause_id) if root_cause else hyp.root_cause_id,
                    "confidence": hyp.confidence,
                    "contributing_phenomena": list(hyp.contributing_phenomena),
                })

            return {
                "action": "summary",
                "query_type": "hypotheses",
                "hypotheses": hypotheses_info,
                "total_count": len(self.session.hypotheses),
                "session": self.session,
            }

        # 未知查询类型
        return {
            "action": "summary",
            "query_type": "unknown",
            "message": "未知的查询类型",
            "session": self.session,
        }

    def _get_phenomenon_by_id(self, phenomenon_id: str) -> Optional[dict]:
        """根据 ID 获取现象"""
        return self._phenomenon_dao.get_by_id(phenomenon_id)

    def _get_phenomenon_descriptions(self, phenomenon_ids: List[str]) -> Dict[str, str]:
        """获取现象描述映射"""
        result = {}
        for pid in phenomenon_ids:
            phenomenon = self._get_phenomenon_by_id(pid)
            if phenomenon:
                result[pid] = phenomenon.get("description", pid)
        return result

    def get_session(self) -> Optional[SessionStateV2]:
        """获取当前会话"""
        return self.session

    def reset(self) -> None:
        """重置会话"""
        self.session = None
