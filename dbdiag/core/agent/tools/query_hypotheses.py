"""假设查询工具

确定性工具，封装 GraphEngine.query_hypotheses()。
"""

from dbdiag.core.agent.models import (
    SessionState,
    QueryHypothesesInput,
    QueryHypothesesOutput,
)
from dbdiag.core.agent.tools.base import BaseTool
from dbdiag.core.agent.graph_engine import GraphEngine


class QueryHypothesesTool(BaseTool[QueryHypothesesInput, QueryHypothesesOutput]):
    """假设查询工具

    查询当前假设详情，包括置信度、贡献现象、缺失现象等。
    纯确定性计算，不依赖 LLM。
    """

    def __init__(self, graph_engine: GraphEngine):
        """初始化假设查询工具

        Args:
            graph_engine: 图谱引擎实例
        """
        self._graph_engine = graph_engine

    @property
    def name(self) -> str:
        return "query_hypotheses"

    @property
    def description(self) -> str:
        return (
            "查询当前假设详情。返回前 K 个假设的置信度、"
            "贡献现象、尚未确认的相关现象等。"
        )

    @property
    def input_schema(self) -> type[QueryHypothesesInput]:
        return QueryHypothesesInput

    @property
    def output_schema(self) -> type[QueryHypothesesOutput]:
        return QueryHypothesesOutput

    def execute(
        self,
        session: SessionState,
        input: QueryHypothesesInput,
    ) -> tuple[QueryHypothesesOutput, SessionState]:
        """查询假设详情

        Args:
            session: 当前会话状态
            input: 查询参数（top_k）

        Returns:
            (假设详情, 原 session 不变)
        """
        output = self._graph_engine.query_hypotheses(session, input.top_k)
        return output, session
