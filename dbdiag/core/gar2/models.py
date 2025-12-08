"""GAR2 数据模型

核心概念：
- Observation: 用户观察到的现象描述，可与标准现象(Phenomenon)匹配
- Symptom: 症状，管理观察列表和阻塞列表
- HypothesisV2: 根因假设，由图传播计算置信度
- SessionStateV2: 会话状态
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Set, Literal

from pydantic import BaseModel, Field, ConfigDict


class Observation(BaseModel):
    """用户观察

    记录用户确认的观察，可以是：
    - user_input: 用户主动描述的观察
    - confirmed: 用户确认了推荐的现象

    Attributes:
        id: 观察 ID，格式 obs-{序号}
        description: 用户原话或现象描述
        source: 来源类型
        matched_phenomenon_id: 匹配的标准现象 ID
        match_score: 匹配度 0-1，1.0 表示完全匹配
        created_at: 创建时间
    """

    id: str
    description: str
    source: Literal["user_input", "confirmed"]
    matched_phenomenon_id: Optional[str] = None
    match_score: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)


class Symptom(BaseModel):
    """症状管理

    维护用户观察列表和阻塞列表。

    Attributes:
        observations: 已确认的观察列表
        blocked_phenomenon_ids: 被否定的现象 ID 集合
        blocked_root_cause_ids: 被否定的根因 ID 集合（否定现象时关联的根因）
    """

    observations: List[Observation] = Field(default_factory=list)
    blocked_phenomenon_ids: Set[str] = Field(default_factory=set)
    blocked_root_cause_ids: Set[str] = Field(default_factory=set)
    _next_obs_id: int = 1

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def add_observation(
        self,
        description: str,
        source: Literal["user_input", "confirmed"],
        matched_phenomenon_id: Optional[str] = None,
        match_score: float = 0.0,
    ) -> Optional[Observation]:
        """添加观察

        Args:
            description: 观察描述
            source: 来源类型
            matched_phenomenon_id: 匹配的现象 ID
            match_score: 匹配度

        Returns:
            创建的 Observation 对象，如果重复则返回 None
        """
        # 去重：检查是否已存在相同描述的观察
        for obs in self.observations:
            if obs.description == description:
                return None  # 已存在，跳过

        obs = Observation(
            id=f"obs-{self._next_obs_id:03d}",
            description=description,
            source=source,
            matched_phenomenon_id=matched_phenomenon_id,
            match_score=match_score,
        )
        self._next_obs_id += 1
        self.observations.append(obs)
        return obs

    def block_phenomenon(
        self, phenomenon_id: str, related_root_cause_ids: List[str]
    ) -> None:
        """阻塞现象及其关联的根因

        当用户否定一个现象时：
        1. 将该现象加入阻塞列表
        2. 将该现象关联的根因加入阻塞列表
        3. 以后不再推荐这些根因下的其他现象

        Args:
            phenomenon_id: 被否定的现象 ID
            related_root_cause_ids: 该现象关联的根因 ID 列表
        """
        self.blocked_phenomenon_ids.add(phenomenon_id)
        for rc_id in related_root_cause_ids:
            self.blocked_root_cause_ids.add(rc_id)

    def is_phenomenon_blocked(self, phenomenon_id: str) -> bool:
        """检查现象是否被阻塞"""
        return phenomenon_id in self.blocked_phenomenon_ids

    def is_root_cause_blocked(self, root_cause_id: str) -> bool:
        """检查根因是否被阻塞"""
        return root_cause_id in self.blocked_root_cause_ids

    def get_matched_phenomenon_ids(self) -> Set[str]:
        """获取所有已匹配的现象 ID"""
        return {
            obs.matched_phenomenon_id
            for obs in self.observations
            if obs.matched_phenomenon_id
        }

    def get_observation_by_phenomenon(
        self, phenomenon_id: str
    ) -> Optional[Observation]:
        """根据现象 ID 查找观察"""
        for obs in self.observations:
            if obs.matched_phenomenon_id == phenomenon_id:
                return obs
        return None

    def update_observation(self, obs_id: str, **kwargs) -> bool:
        """更新观察

        Args:
            obs_id: 观察 ID
            **kwargs: 要更新的字段

        Returns:
            是否更新成功
        """
        for i, obs in enumerate(self.observations):
            if obs.id == obs_id:
                updated_data = obs.model_dump()
                updated_data.update(kwargs)
                self.observations[i] = Observation(**updated_data)
                return True
        return False

    def remove_observation(self, obs_id: str) -> bool:
        """移除观察

        Args:
            obs_id: 观察 ID

        Returns:
            是否移除成功
        """
        for i, obs in enumerate(self.observations):
            if obs.id == obs_id:
                self.observations.pop(i)
                return True
        return False


class HypothesisV2(BaseModel):
    """根因假设

    由图传播计算得到的根因假设。

    Attributes:
        root_cause_id: 根因 ID
        confidence: 置信度 0-1
        contributing_observations: 贡献该假设的观察 ID 列表
        contributing_phenomena: 贡献该假设的现象 ID 列表
    """

    root_cause_id: str
    confidence: float = 0.0
    contributing_observations: List[str] = Field(default_factory=list)
    contributing_phenomena: List[str] = Field(default_factory=list)


class SessionStateV2(BaseModel):
    """GAR2 会话状态

    Attributes:
        session_id: 会话 ID
        user_problem: 用户问题描述
        symptom: 症状（观察列表 + 阻塞列表）
        hypotheses: 根因假设列表（按置信度排序）
        recommended_phenomenon_ids: 当前推荐的现象 ID 列表
        turn_count: 轮次计数
        accumulated_match_result: 累积的多目标匹配结果
    """

    session_id: str
    user_problem: str = ""
    symptom: Symptom = Field(default_factory=Symptom)
    hypotheses: List[HypothesisV2] = Field(default_factory=list)
    recommended_phenomenon_ids: List[str] = Field(default_factory=list)
    turn_count: int = 0
    accumulated_match_result: Optional["MatchResult"] = None

    @property
    def top_hypothesis(self) -> Optional[HypothesisV2]:
        """获取置信度最高的假设"""
        if self.hypotheses:
            return self.hypotheses[0]
        return None

    @property
    def observation_count(self) -> int:
        """观察数量"""
        return len(self.symptom.observations)

    @property
    def blocked_count(self) -> int:
        """阻塞的根因数量"""
        return len(self.symptom.blocked_root_cause_ids)


class PhenomenonMatch(BaseModel):
    """现象匹配结果"""
    phenomenon_id: str
    score: float


class RootCauseMatch(BaseModel):
    """根因匹配结果"""
    root_cause_id: str
    score: float


class TicketMatch(BaseModel):
    """工单匹配结果"""
    ticket_id: str
    root_cause_id: str
    score: float


class MatchResult(BaseModel):
    """观察匹配综合结果

    用户输入同时匹配三类目标，然后传播到根因计算置信度。

    Attributes:
        phenomena: 现象匹配列表
        root_causes: 根因匹配列表
        tickets: 工单匹配列表
    """
    phenomena: List[PhenomenonMatch] = Field(default_factory=list)
    root_causes: List[RootCauseMatch] = Field(default_factory=list)
    tickets: List[TicketMatch] = Field(default_factory=list)

    @property
    def best_phenomenon(self) -> Optional[PhenomenonMatch]:
        """获取最佳现象匹配"""
        if self.phenomena:
            return max(self.phenomena, key=lambda x: x.score)
        return None

    @property
    def has_matches(self) -> bool:
        """是否有任何匹配结果"""
        return bool(self.phenomena or self.root_causes or self.tickets)

    def merge(self, other: "MatchResult") -> None:
        """合并另一个 MatchResult（去重，保留更高分数）

        Args:
            other: 要合并的 MatchResult
        """
        # 合并 phenomena（按 phenomenon_id 去重，保留更高分数）
        existing_phenomena = {p.phenomenon_id: p for p in self.phenomena}
        for p in other.phenomena:
            if p.phenomenon_id not in existing_phenomena or p.score > existing_phenomena[p.phenomenon_id].score:
                existing_phenomena[p.phenomenon_id] = p
        self.phenomena = list(existing_phenomena.values())

        # 合并 root_causes（按 root_cause_id 去重，保留更高分数）
        existing_rc = {r.root_cause_id: r for r in self.root_causes}
        for r in other.root_causes:
            if r.root_cause_id not in existing_rc or r.score > existing_rc[r.root_cause_id].score:
                existing_rc[r.root_cause_id] = r
        self.root_causes = list(existing_rc.values())

        # 合并 tickets（按 ticket_id 去重，保留更高分数）
        existing_tickets = {t.ticket_id: t for t in self.tickets}
        for t in other.tickets:
            if t.ticket_id not in existing_tickets or t.score > existing_tickets[t.ticket_id].score:
                existing_tickets[t.ticket_id] = t
        self.tickets = list(existing_tickets.values())
