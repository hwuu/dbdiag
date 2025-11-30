"""RAR 会话状态

检索增强推理方法的会话状态管理。
"""
from dataclasses import dataclass, field
from typing import List, Set, Dict, Any


@dataclass
class RARSessionState:
    """检索增强推理会话状态

    跟踪诊断过程中的累积信息，用于构建检索 query 和 LLM prompt。
    """

    session_id: str
    user_problem: str

    # 观察状态
    confirmed_observations: List[str] = field(default_factory=list)
    denied_observations: List[str] = field(default_factory=list)
    asked_observations: List[str] = field(default_factory=list)

    # 相关工单
    relevant_ticket_ids: Set[str] = field(default_factory=set)

    # 对话轮次
    dialogue_turns: int = 0

    def confirm_observation(self, observation: str) -> None:
        """确认观察

        Args:
            observation: 观察描述
        """
        if observation not in self.confirmed_observations:
            self.confirmed_observations.append(observation)
        if observation not in self.asked_observations:
            self.asked_observations.append(observation)

    def deny_observation(self, observation: str) -> None:
        """否定观察

        Args:
            observation: 观察描述
        """
        if observation not in self.denied_observations:
            self.denied_observations.append(observation)
        if observation not in self.asked_observations:
            self.asked_observations.append(observation)

    def add_asked_observation(self, observation: str) -> None:
        """添加已问过的观察

        Args:
            observation: 观察描述
        """
        if observation not in self.asked_observations:
            self.asked_observations.append(observation)

    def add_relevant_ticket_ids(self, ticket_ids: List[str]) -> None:
        """添加相关工单ID

        Args:
            ticket_ids: 工单 ID 列表
        """
        self.relevant_ticket_ids.update(ticket_ids)

    def increment_turn(self) -> None:
        """增加对话轮次"""
        self.dialogue_turns += 1

    def is_observation_asked(self, observation: str) -> bool:
        """判断观察是否已问过

        Args:
            observation: 观察描述

        Returns:
            是否已问过
        """
        return observation in self.asked_observations

    def get_status_summary(self) -> str:
        """获取状态摘要（用于 LLM prompt）

        Returns:
            状态摘要文本
        """
        parts = []

        if self.confirmed_observations:
            parts.append(f"已确认的观察: {', '.join(self.confirmed_observations)}")

        if self.denied_observations:
            parts.append(f"已否定的观察: {', '.join(self.denied_observations)}")

        parts.append(f"对话轮次: {self.dialogue_turns}")

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典

        Returns:
            字典表示
        """
        return {
            "session_id": self.session_id,
            "user_problem": self.user_problem,
            "confirmed_observations": self.confirmed_observations,
            "denied_observations": self.denied_observations,
            "asked_observations": self.asked_observations,
            "relevant_ticket_ids": list(self.relevant_ticket_ids),
            "dialogue_turns": self.dialogue_turns,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RARSessionState":
        """从字典反序列化

        Args:
            data: 字典数据

        Returns:
            RARSessionState 实例
        """
        return cls(
            session_id=data["session_id"],
            user_problem=data["user_problem"],
            confirmed_observations=data.get("confirmed_observations", []),
            denied_observations=data.get("denied_observations", []),
            asked_observations=data.get("asked_observations", []),
            relevant_ticket_ids=set(data.get("relevant_ticket_ids", [])),
            dialogue_turns=data.get("dialogue_turns", 0),
        )
