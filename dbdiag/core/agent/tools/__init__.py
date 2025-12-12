"""Agent 工具集

包含 Agent 可调用的工具：
- match_phenomena: 现象匹配工具 (LLM + Embedding)
- diagnose: 诊断工具 (确定性)
- query_progress: 进展查询工具 (确定性)
- query_hypotheses: 假设查询工具 (确定性)
- query_relations: 关系查询工具 (确定性)
"""

from dbdiag.core.agent.tools.base import BaseTool
from dbdiag.core.agent.tools.diagnose import DiagnoseTool
from dbdiag.core.agent.tools.query_progress import QueryProgressTool
from dbdiag.core.agent.tools.query_hypotheses import QueryHypothesesTool
from dbdiag.core.agent.tools.query_relations import QueryRelationsTool
from dbdiag.core.agent.tools.match_phenomena import MatchPhenomenaTool

__all__ = [
    "BaseTool",
    "DiagnoseTool",
    "QueryProgressTool",
    "QueryHypothesesTool",
    "QueryRelationsTool",
    "MatchPhenomenaTool",
]
