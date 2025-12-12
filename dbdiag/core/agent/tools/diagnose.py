"""诊断工具

确定性工具，封装 GraphEngine.diagnose()。
"""

from dbdiag.core.agent.models import (
    SessionState,
    DiagnoseInput,
    DiagnoseOutput,
)
from dbdiag.core.agent.tools.base import BaseTool
from dbdiag.core.agent.graph_engine import GraphEngine


class DiagnoseTool(BaseTool[DiagnoseInput, DiagnoseOutput]):
    """诊断工具

    根据已确认/否认的现象，计算假设置信度，生成推荐现象。
    纯确定性计算，不依赖 LLM。
    """

    def __init__(self, graph_engine: GraphEngine):
        """初始化诊断工具

        Args:
            graph_engine: 图谱引擎实例
        """
        self._graph_engine = graph_engine

    @property
    def name(self) -> str:
        return "diagnose"

    @property
    def description(self) -> str:
        return (
            "执行诊断推理。根据已确认的现象计算各根因的置信度，"
            "生成假设列表和推荐的下一步确认现象。"
        )

    @property
    def input_schema(self) -> type[DiagnoseInput]:
        return DiagnoseInput

    @property
    def output_schema(self) -> type[DiagnoseOutput]:
        return DiagnoseOutput

    def execute(
        self,
        session: SessionState,
        input: DiagnoseInput,
    ) -> tuple[DiagnoseOutput, SessionState]:
        """执行诊断

        Args:
            session: 当前会话状态
            input: 诊断输入（确认/否认的现象）

        Returns:
            (诊断结果, 更新后的 session)
        """
        return self._graph_engine.diagnose(session, input)
