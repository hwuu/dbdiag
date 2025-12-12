"""工具抽象基类"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic

from pydantic import BaseModel

from dbdiag.core.agent.models import SessionState


# 泛型类型：工具输入和输出
TInput = TypeVar("TInput", bound=BaseModel)
TOutput = TypeVar("TOutput", bound=BaseModel)


class BaseTool(ABC, Generic[TInput, TOutput]):
    """工具抽象基类

    所有工具都必须实现此接口，确保统一的调用方式。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称，用于 Planner 调用"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述，用于 Planner prompt"""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> type[TInput]:
        """输入参数的 Pydantic 模型类"""
        pass

    @property
    @abstractmethod
    def output_schema(self) -> type[TOutput]:
        """输出结果的 Pydantic 模型类"""
        pass

    @abstractmethod
    def execute(
        self,
        session: SessionState,
        input: TInput,
    ) -> tuple[TOutput, SessionState]:
        """执行工具

        Args:
            session: 当前会话状态
            input: 工具输入参数

        Returns:
            (工具执行结果, 更新后的 session)

        Note:
            即使工具不修改 session，也返回原 session 以保持接口一致性。
        """
        pass
