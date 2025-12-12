"""进展查询工具

确定性工具，封装 GraphEngine.query_progress()。
"""

from pydantic import BaseModel

from dbdiag.core.agent.models import (
    SessionState,
    QueryProgressOutput,
)
from dbdiag.core.agent.tools.base import BaseTool
from dbdiag.core.agent.graph_engine import GraphEngine


class QueryProgressInput(BaseModel):
    """查询进展的输入 - 无需参数"""
    pass


class QueryProgressTool(BaseTool[QueryProgressInput, QueryProgressOutput]):
    """进展查询工具

    查询当前诊断进展，包括轮次、确认现象数、最高置信度等。
    纯确定性计算，不依赖 LLM。
    """

    def __init__(self, graph_engine: GraphEngine):
        """初始化进展查询工具

        Args:
            graph_engine: 图谱引擎实例
        """
        self._graph_engine = graph_engine

    @property
    def name(self) -> str:
        return "query_progress"

    @property
    def description(self) -> str:
        return (
            "查询当前诊断进展。返回已进行轮次、确认现象数、"
            "当前最高置信度假设等信息。"
        )

    @property
    def input_schema(self) -> type[QueryProgressInput]:
        return QueryProgressInput

    @property
    def output_schema(self) -> type[QueryProgressOutput]:
        return QueryProgressOutput

    def execute(
        self,
        session: SessionState,
        input: QueryProgressInput,
    ) -> tuple[QueryProgressOutput, SessionState]:
        """查询诊断进展

        Args:
            session: 当前会话状态
            input: 无参数输入

        Returns:
            (进展信息, 原 session 不变)
        """
        output = self._graph_engine.query_progress(session)
        return output, session
