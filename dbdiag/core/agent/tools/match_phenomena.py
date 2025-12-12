"""现象匹配工具

LLM + Embedding 工具，将用户观察描述匹配到标准现象。
"""

import json
from typing import List, Optional

from dbdiag.dao import PhenomenonDAO
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.services.llm_service import LLMService
from dbdiag.utils.vector_utils import cosine_similarity, deserialize_f32
from dbdiag.core.agent.models import (
    SessionState,
    MatchPhenomenaInput,
    MatchPhenomenaOutput,
    RawObservation,
    CandidatePhenomenon,
    MatchedPhenomenon,
    InterpretedObservation,
    ClarificationOption,
)
from dbdiag.core.agent.tools.base import BaseTool

from typing import Callable

# 进度回调类型
ProgressCallback = Callable[[str], None]


# LLM Prompt
MATCH_PHENOMENA_SYSTEM_PROMPT = """你是数据库诊断系统的观察解释器。你的任务是将用户的观察描述匹配到标准现象库。

## 任务

对每个用户描述，判断：

1. **能否匹配**：是否能确定对应哪个标准现象
2. **匹配置信度**：0-1 之间，表示匹配的确定程度
3. **指代消解**：如果是指代表达（如"上一轮那个"、"1确认"），解析指代对象
4. **数值提取**：如果描述中包含具体数值（如"65%"），提取出来

## 输出格式

必须输出 JSON 数组，每个元素对应一个用户描述：

```json
[
  {
    "raw_description": "用户原始描述",
    "matched": {
      "phenomenon_id": "P-xxxx",
      "match_score": 0.85,
      "extracted_value": "65%"
    }
  },
  {
    "raw_description": "用户原始描述2",
    "needs_clarification": true,
    "clarification_question": "澄清问题",
    "options": ["P-0001", "P-0002"]
  }
]
```

注意：
- 如果匹配成功，设置 matched 字段
- 如果需要澄清，设置 needs_clarification=true 并提供 clarification_question 和 options
- extracted_value 是可选的，只有当用户描述中有具体数值时才设置
- match_score 应该基于语义相似度和上下文判断
"""


class MatchPhenomenaTool(BaseTool[MatchPhenomenaInput, MatchPhenomenaOutput]):
    """现象匹配工具

    将用户原始观察描述匹配到标准现象库。
    使用 Embedding 召回候选 + LLM 精排决策。
    """

    # 召回参数
    RECALL_TOP_K = 5  # 每个描述召回的候选数
    SIMILARITY_THRESHOLD = 0.5  # 召回阈值
    CLARIFICATION_THRESHOLD = 0.7  # 低于此值可能需要澄清

    def __init__(
        self,
        db_path: str,
        embedding_service: EmbeddingService,
        llm_service: LLMService,
        progress_callback: ProgressCallback = None,
    ):
        """初始化现象匹配工具

        Args:
            db_path: 数据库路径
            embedding_service: 向量服务
            llm_service: LLM 服务
            progress_callback: 进度回调函数
        """
        self._db_path = db_path
        self._embedding_service = embedding_service
        self._llm_service = llm_service
        self._phenomenon_dao = PhenomenonDAO(db_path)
        self._progress_callback = progress_callback

    def _report_progress(self, message: str):
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(message)

    @property
    def name(self) -> str:
        return "match_phenomena"

    @property
    def description(self) -> str:
        return (
            "将用户观察描述匹配到标准现象。支持指代消解、数值提取、"
            "模糊描述澄清。返回匹配结果或澄清问题。"
        )

    @property
    def input_schema(self) -> type[MatchPhenomenaInput]:
        return MatchPhenomenaInput

    @property
    def output_schema(self) -> type[MatchPhenomenaOutput]:
        return MatchPhenomenaOutput

    def execute(
        self,
        session: SessionState,
        input: MatchPhenomenaInput,
    ) -> tuple[MatchPhenomenaOutput, SessionState]:
        """执行现象匹配

        Args:
            session: 当前会话状态
            input: 匹配输入（原始观察、确认/否认列表等）

        Returns:
            (匹配结果, 原 session 不变)
        """
        interpreted_results: List[InterpretedObservation] = []

        # 1. 处理直接确认的现象（通过 ID）
        self._report_progress(f"[match_phenomena] 处理确认列表: {len(input.confirmations)} 个")
        for confirm_id in input.confirmations:
            phenomenon = self._phenomenon_dao.get_by_id(confirm_id)
            if phenomenon:
                interpreted_results.append(InterpretedObservation(
                    raw_description=f"确认 {confirm_id}",
                    matched_phenomenon=MatchedPhenomenon(
                        phenomenon_id=confirm_id,
                        phenomenon_description=phenomenon.get("description", ""),
                        user_observation=f"用户直接确认",
                        match_score=1.0,
                    ),
                    needs_clarification=False,
                ))

        # 2. 处理原始观察描述
        if input.raw_observations:
            self._report_progress(f"[match_phenomena] 处理原始观察: {len(input.raw_observations)} 个")

            # 2.1 Embedding 召回
            self._report_progress("[match_phenomena] 开始 Embedding 召回...")
            all_candidates = self._recall_candidates(input.raw_observations)
            self._report_progress(f"[match_phenomena] Embedding 召回完成, 候选数: {[len(c) for c in all_candidates]}")

            # 2.2 LLM 精排
            self._report_progress("[match_phenomena] 开始 LLM 精排...")
            llm_results = self._llm_interpret(
                input.raw_observations,
                all_candidates,
                input.dialogue_history,
                input.pending_recommendations,
            )
            self._report_progress(f"[match_phenomena] LLM 精排完成")

            # 2.3 构建解释结果
            for raw_obs, llm_result, candidates in zip(
                input.raw_observations, llm_results, all_candidates
            ):
                interpreted = self._build_interpreted_observation(
                    raw_obs, llm_result, candidates
                )
                interpreted_results.append(interpreted)

        # 3. 检查是否全部匹配成功
        all_matched = all(
            not interp.needs_clarification and interp.matched_phenomenon is not None
            for interp in interpreted_results
        )

        self._report_progress(f"[match_phenomena] 完成, all_matched={all_matched}, 结果数={len(interpreted_results)}")

        output = MatchPhenomenaOutput(
            interpreted=interpreted_results,
            all_matched=all_matched,
        )

        # match_phenomena 不修改 session
        return output, session

    def _recall_candidates(
        self,
        raw_observations: List[RawObservation],
    ) -> List[List[CandidatePhenomenon]]:
        """Embedding 召回候选现象

        Args:
            raw_observations: 原始观察列表

        Returns:
            每个观察对应的候选现象列表
        """
        all_candidates: List[List[CandidatePhenomenon]] = []

        # 获取所有现象的 Embedding
        all_phenomena = self._phenomenon_dao.get_all_with_embedding()
        if not all_phenomena:
            return [[] for _ in raw_observations]

        for raw_obs in raw_observations:
            # 生成查询向量
            query_embedding = self._embedding_service.encode(raw_obs.description)
            if not query_embedding:
                all_candidates.append([])
                continue

            # 计算相似度
            candidates = []
            for phenomenon in all_phenomena:
                if not phenomenon.get("embedding"):
                    continue

                phen_embedding = deserialize_f32(phenomenon["embedding"])
                similarity = cosine_similarity(query_embedding, phen_embedding)

                if similarity >= self.SIMILARITY_THRESHOLD:
                    candidates.append(CandidatePhenomenon(
                        phenomenon_id=phenomenon["phenomenon_id"],
                        description=phenomenon.get("description", ""),
                        observation_method=phenomenon.get("observation_method", ""),
                        similarity_score=similarity,
                    ))

            # 按相似度排序，取 top-k
            candidates.sort(key=lambda c: c.similarity_score, reverse=True)
            all_candidates.append(candidates[:self.RECALL_TOP_K])

        return all_candidates

    def _llm_interpret(
        self,
        raw_observations: List[RawObservation],
        all_candidates: List[List[CandidatePhenomenon]],
        dialogue_history: str,
        pending_recommendations: List[dict],
    ) -> List[dict]:
        """LLM 精排和解释

        Args:
            raw_observations: 原始观察列表
            all_candidates: 候选现象列表
            dialogue_history: 对话历史
            pending_recommendations: 待确认现象列表

        Returns:
            LLM 解释结果列表
        """
        # 构建 prompt
        user_prompt = self._build_llm_prompt(
            raw_observations,
            all_candidates,
            dialogue_history,
            pending_recommendations,
        )

        # 调用 LLM
        response = self._llm_service.generate_simple(
            user_prompt,
            system_prompt=MATCH_PHENOMENA_SYSTEM_PROMPT,
        )

        # 解析 JSON 响应
        return self._parse_llm_response(response, len(raw_observations))

    def _build_llm_prompt(
        self,
        raw_observations: List[RawObservation],
        all_candidates: List[List[CandidatePhenomenon]],
        dialogue_history: str,
        pending_recommendations: List[dict],
    ) -> str:
        """构建 LLM prompt"""
        sections = []

        # 用户原始描述
        sections.append("## 用户原始描述")
        for i, obs in enumerate(raw_observations, 1):
            sections.append(f"{i}. \"{obs.description}\"")
            if obs.context:
                sections.append(f"   上下文: {obs.context}")

        # 候选现象
        sections.append("\n## 候选现象（Embedding 召回）")
        for i, (obs, candidates) in enumerate(zip(raw_observations, all_candidates), 1):
            sections.append(f"\n### 描述 {i}: \"{obs.description}\"")
            if not candidates:
                sections.append("无匹配候选")
            else:
                for c in candidates:
                    sections.append(
                        f"- {c.phenomenon_id}: {c.description} "
                        f"(相似度: {c.similarity_score:.2f})"
                    )

        # 对话历史
        if dialogue_history:
            sections.append("\n## 对话历史")
            sections.append(dialogue_history)

        # 待确认现象
        if pending_recommendations:
            sections.append("\n## 当前待确认的现象")
            for i, rec in enumerate(pending_recommendations, 1):
                pid = rec.get("phenomenon_id", "")
                desc = rec.get("description", "")
                sections.append(f"{i}. {pid}: {desc}")

        sections.append("\n请对每个用户描述进行解释，输出 JSON 数组。")

        return "\n".join(sections)

    def _parse_llm_response(
        self,
        response: str,
        expected_count: int,
    ) -> List[dict]:
        """解析 LLM 响应

        Args:
            response: LLM 响应文本
            expected_count: 期望的结果数量

        Returns:
            解析后的结果列表
        """
        # 尝试提取 JSON
        try:
            # 尝试直接解析
            results = json.loads(response)
            if isinstance(results, list):
                return results
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        import re
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if json_match:
            try:
                results = json.loads(json_match.group(1))
                if isinstance(results, list):
                    return results
            except json.JSONDecodeError:
                pass

        # 解析失败，返回空结果
        return [{"error": "解析失败"} for _ in range(expected_count)]

    def _build_interpreted_observation(
        self,
        raw_obs: RawObservation,
        llm_result: dict,
        candidates: List[CandidatePhenomenon],
    ) -> InterpretedObservation:
        """构建解释结果

        Args:
            raw_obs: 原始观察
            llm_result: LLM 解释结果
            candidates: 候选现象

        Returns:
            InterpretedObservation
        """
        # 检查是否有匹配
        matched_data = llm_result.get("matched")
        needs_clarification = llm_result.get("needs_clarification", False)

        if matched_data and not needs_clarification:
            phenomenon_id = matched_data.get("phenomenon_id", "")
            match_score = matched_data.get("match_score", 0.8)
            extracted_value = matched_data.get("extracted_value")

            # 获取现象描述
            phenomenon = self._phenomenon_dao.get_by_id(phenomenon_id)
            phenomenon_desc = phenomenon.get("description", "") if phenomenon else ""

            return InterpretedObservation(
                raw_description=raw_obs.description,
                matched_phenomenon=MatchedPhenomenon(
                    phenomenon_id=phenomenon_id,
                    phenomenon_description=phenomenon_desc,
                    user_observation=raw_obs.description,
                    match_score=match_score,
                    extracted_value=extracted_value,
                ),
                needs_clarification=False,
            )

        elif needs_clarification:
            # 需要澄清
            clarification_question = llm_result.get(
                "clarification_question",
                "请更具体地描述你观察到的现象"
            )
            option_ids = llm_result.get("options", [])

            # 构建澄清选项
            clarification_options = []
            for opt_id in option_ids:
                phenomenon = self._phenomenon_dao.get_by_id(opt_id)
                if phenomenon:
                    clarification_options.append(ClarificationOption(
                        phenomenon_id=opt_id,
                        description=phenomenon.get("description", ""),
                        observation_method=phenomenon.get("observation_method", ""),
                    ))

            # 如果 LLM 没返回选项，使用候选
            if not clarification_options and candidates:
                for c in candidates[:3]:
                    clarification_options.append(ClarificationOption(
                        phenomenon_id=c.phenomenon_id,
                        description=c.description,
                        observation_method=c.observation_method,
                    ))

            return InterpretedObservation(
                raw_description=raw_obs.description,
                needs_clarification=True,
                clarification_question=clarification_question,
                clarification_options=clarification_options,
            )

        else:
            # 无法匹配也无法澄清（候选为空）
            return InterpretedObservation(
                raw_description=raw_obs.description,
                needs_clarification=True,
                clarification_question="未找到匹配的现象，请更详细地描述你观察到的问题",
                clarification_options=[],
            )
