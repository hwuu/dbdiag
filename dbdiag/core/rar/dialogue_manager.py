"""RAR 对话管理器

检索增强推理方法的对话管理器，使用 RAG + LLM 端到端推理。
"""
import json
import uuid
from typing import Dict, Any, Optional, List

from dbdiag.models.rar import RARSessionState
from dbdiag.core.rar.retriever import RARRetriever, RARTicket
from dbdiag.services.llm_service import LLMService
from dbdiag.services.embedding_service import EmbeddingService


# LLM 系统 Prompt
SYSTEM_PROMPT = """你是一个数据库运维问题诊断助手。你的任务是根据用户描述的问题和历史工单数据，
帮助用户定位问题的根本原因。

## 工作模式

你有两种输出模式：
1. **推荐模式 (recommend)**：当证据不足时，推荐用户检查 1-3 个可能相关的现象
2. **诊断模式 (diagnose)**：当证据充足时，给出根因分析报告

## 判断标准

选择"诊断模式"的条件（满足任一）：
- 用户确认的现象与某个根因高度匹配（≥3 个关键现象）
- 检索到的工单中有明确匹配用户场景的案例
- 已经进行了 3 轮以上的现象确认，且有明显倾向

选择"推荐模式"的条件：
- 信息不足以确定根因
- 存在多个可能的根因需要区分

## 输出格式

必须输出有效的 JSON，格式如下：

推荐模式：
{
  "action": "recommend",
  "confidence": 0.45,
  "reasoning": "用户描述了查询变慢，但缺少 IO、锁、索引等关键观察...",
  "recommendations": [
    {
      "observation": "wait_io 事件占比",
      "method": "SELECT wait_event_type, count(*) FROM pg_stat_activity...",
      "why": "高 IO 等待通常与索引膨胀或磁盘瓶颈相关",
      "related_root_causes": ["索引膨胀", "磁盘 IO 瓶颈"]
    }
  ]
}

诊断模式：
{
  "action": "diagnose",
  "confidence": 0.85,
  "root_cause": "索引膨胀导致 IO 瓶颈",
  "reasoning": "用户确认了 wait_io 高、索引增长异常、REINDEX 后恢复...",
  "observed_phenomena": ["wait_io 占比 65%", "索引从 2GB 增长到 12GB"],
  "solution": "1. REINDEX INDEX CONCURRENTLY...\\n2. 配置 autovacuum...",
  "cited_tickets": ["T-0001", "T-0018"]
}
"""


class RARDialogueManager:
    """检索增强推理对话管理器

    使用 RAG 检索 + LLM 推理进行诊断对话。
    """

    def __init__(
        self,
        db_path: str,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        max_turns: int = 5,
        top_k: int = 10,
    ):
        """初始化

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务
            embedding_service: Embedding 服务
            max_turns: 最大对话轮次（超过后强制诊断）
            top_k: 检索的最大工单数
        """
        self.db_path = db_path
        self.llm_service = llm_service
        self.embedding_service = embedding_service
        self.max_turns = max_turns
        self.top_k = top_k

        # 检索器
        self.retriever = RARRetriever(db_path, embedding_service)

        # 会话状态
        self.state: Optional[RARSessionState] = None

    def start_session(self, user_problem: str) -> str:
        """启动新会话

        Args:
            user_problem: 用户问题描述

        Returns:
            会话 ID
        """
        session_id = str(uuid.uuid4())
        self.state = RARSessionState(
            session_id=session_id,
            user_problem=user_problem,
        )
        return session_id

    def process_message(self, user_message: str) -> Dict[str, Any]:
        """处理用户消息

        Args:
            user_message: 用户输入

        Returns:
            LLM 响应（推荐或诊断）
        """
        if self.state is None:
            raise RuntimeError("会话未启动，请先调用 start_session")

        # 1. 检索相关工单
        tickets = self.retriever.retrieve(self.state, user_message, top_k=self.top_k)

        # 2. 记录相关工单 ID
        self.state.add_relevant_ticket_ids([t.ticket_id for t in tickets])

        # 3. 构建 LLM prompt
        prompt = self._build_prompt(user_message, tickets)

        # 4. 调用 LLM (debug=True 打印 curl 命令)
        llm_response = self.llm_service.generate_simple(prompt, system_prompt=SYSTEM_PROMPT, debug=True)

        # 5. 解析响应
        try:
            response = json.loads(llm_response)
        except json.JSONDecodeError:
            # 如果解析失败，尝试提取 JSON
            response = self._extract_json(llm_response)

        # 6. 应用 Guardrails
        response = self._apply_guardrails(response, tickets)

        # 7. 增加轮次
        self.state.increment_turn()

        # 8. 检查是否需要强制诊断
        if self.state.dialogue_turns >= self.max_turns and response.get("action") == "recommend":
            response = self._force_diagnose(response, tickets)

        return response

    def confirm_observation(self, observation: str) -> None:
        """确认观察

        Args:
            observation: 观察描述
        """
        if self.state:
            self.state.confirm_observation(observation)

    def deny_observation(self, observation: str) -> None:
        """否定观察

        Args:
            observation: 观察描述
        """
        if self.state:
            self.state.deny_observation(observation)

    def _build_prompt(self, user_message: str, tickets: List[RARTicket]) -> str:
        """构建 LLM prompt

        Args:
            user_message: 用户输入
            tickets: 检索到的工单

        Returns:
            prompt 文本
        """
        # 格式化工单
        formatted_tickets = self._format_tickets(tickets)

        # 构建 prompt
        prompt = f"""## 用户问题
{self.state.user_problem}

## 当前状态
{self.state.get_status_summary()}

## 用户本轮输入
{user_message}

## 相关历史工单
{formatted_tickets}

请根据以上信息，决定是推荐用户检查更多现象，还是给出诊断结论。"""

        return prompt

    def _format_tickets(self, tickets: List[RARTicket]) -> str:
        """格式化工单列表

        Args:
            tickets: 工单列表

        Returns:
            格式化后的文本
        """
        if not tickets:
            return "（无相关工单）"

        parts = []

        # Top 3: 完整内容
        for i, t in enumerate(tickets[:3]):
            parts.append(f"""### 工单 {t.ticket_id}（相似度: {t.similarity:.2f}）
**问题描述**: {t.description}
**根因**: {t.root_cause}
**解决方案**: {t.solution}
""")

        # Top 4-10: 精简内容
        for t in tickets[3:10]:
            parts.append(f"- **{t.ticket_id}**: {t.description[:50]}... (根因: {t.root_cause})")

        # 其余: 仅列表
        if len(tickets) > 10:
            remaining = [t.ticket_id for t in tickets[10:]]
            parts.append(f"\n其他相关工单: {', '.join(remaining)}")

        return "\n".join(parts)

    def _apply_guardrails(
        self,
        response: Dict[str, Any],
        tickets: List[RARTicket],
    ) -> Dict[str, Any]:
        """应用 Guardrails

        Args:
            response: LLM 响应
            tickets: 检索到的工单

        Returns:
            处理后的响应
        """
        if response.get("action") == "recommend":
            # 过滤已问过的观察
            recommendations = response.get("recommendations", [])
            filtered = [
                r for r in recommendations
                if not self.state.is_observation_asked(r.get("observation", ""))
            ]

            # 记录已问过
            for r in filtered:
                self.state.add_asked_observation(r.get("observation", ""))

            response["recommendations"] = filtered[:3]

        elif response.get("action") == "diagnose":
            # 验证引用的工单确实存在
            valid_ticket_ids = {t.ticket_id for t in tickets}
            cited = response.get("cited_tickets", [])
            response["cited_tickets"] = [
                tid for tid in cited if tid in valid_ticket_ids
            ]

        return response

    def _force_diagnose(
        self,
        response: Dict[str, Any],
        tickets: List[RARTicket],
    ) -> Dict[str, Any]:
        """强制诊断（超过最大轮次）

        Args:
            response: 原始响应
            tickets: 检索到的工单

        Returns:
            诊断响应
        """
        # 使用当前最相关的工单作为参考
        if tickets:
            top_ticket = tickets[0]
            return {
                "action": "diagnose",
                "confidence": 0.5,
                "root_cause": top_ticket.root_cause,
                "reasoning": f"已进行 {self.state.dialogue_turns} 轮对话，根据相关工单 {top_ticket.ticket_id} 给出最可能的根因",
                "observed_phenomena": self.state.confirmed_observations,
                "solution": top_ticket.solution,
                "cited_tickets": [top_ticket.ticket_id],
                "forced": True,
            }
        else:
            return {
                "action": "diagnose",
                "confidence": 0.3,
                "root_cause": "无法确定",
                "reasoning": f"已进行 {self.state.dialogue_turns} 轮对话，但没有足够信息定位根因",
                "observed_phenomena": self.state.confirmed_observations,
                "solution": "建议联系 DBA 进一步排查",
                "cited_tickets": [],
                "forced": True,
            }

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """从文本中提取 JSON

        Args:
            text: 可能包含 JSON 的文本

        Returns:
            解析后的字典
        """
        # 尝试找到 JSON 块
        import re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 返回默认响应
        return {
            "action": "recommend",
            "confidence": 0.3,
            "reasoning": "无法解析 LLM 响应",
            "recommendations": [],
        }
