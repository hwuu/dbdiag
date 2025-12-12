"""关系查询工具

确定性工具，封装 GraphEngine.query_relations()。
"""

from dbdiag.core.agent.models import (
    SessionState,
    QueryRelationsInput,
    QueryRelationsOutput,
)
from dbdiag.core.agent.tools.base import BaseTool
from dbdiag.core.agent.graph_engine import GraphEngine


class QueryRelationsTool(BaseTool[QueryRelationsInput, QueryRelationsOutput]):
    """关系查询工具

    查询图谱中的现象-根因关系。
    纯确定性计算，不依赖 LLM。
    """

    def __init__(self, graph_engine: GraphEngine):
        """初始化关系查询工具

        Args:
            graph_engine: 图谱引擎实例
        """
        self._graph_engine = graph_engine

    @property
    def name(self) -> str:
        return "query_relations"

    @property
    def description(self) -> str:
        return (
            "查询图谱关系。支持查询现象关联的根因，"
            "或根因关联的现象。"
        )

    @property
    def input_schema(self) -> type[QueryRelationsInput]:
        return QueryRelationsInput

    @property
    def output_schema(self) -> type[QueryRelationsOutput]:
        return QueryRelationsOutput

    def execute(
        self,
        session: SessionState,
        input: QueryRelationsInput,
    ) -> tuple[QueryRelationsOutput, SessionState]:
        """查询图谱关系

        Args:
            session: 当前会话状态
            input: 查询参数（查询方向、实体 ID）

        Returns:
            (关系列表, 原 session 不变)
        """
        output = self._graph_engine.query_relations(input)
        return output, session
