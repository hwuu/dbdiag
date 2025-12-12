"""Planner - Agent Loop 决策层

根据当前上下文决定下一步行动：调用工具或直接回复用户。
"""

import json
import re
from typing import Optional, List, Dict, Any

from dbdiag.services.llm_service import LLMService
from dbdiag.core.agent.models import (
    SessionState,
    AgentDecision,
    Recommendation,
)


PLANNER_SYSTEM_PROMPT = """你是一个数据库诊断助手的决策模块，运行在 Agent Loop 中。

每次循环，你需要根据当前上下文决定下一步行动：
1. 调用工具（call）
2. 直接回复用户（respond）

## 可用工具

### match_phenomena
将用户的原始观察描述匹配到标准现象库。

使用场景：
- 用户描述了新的观察（如"IO 很高"、"慢查询很多"）
- 需要将模糊描述转换为标准 phenomenon

输入参数：
- raw_observations: 原始观察描述列表，每项包含 description 和可选的 context
- confirmations: 直接确认的现象 ID 列表（如用户说"1确认"）
- denials: 否认的现象 ID 列表
- dialogue_history: 最近对话历史（用于指代消解）
- pending_recommendations: 当前待确认的现象列表

输出：
- 匹配成功：返回 matched phenomena 列表（含匹配度）
- 匹配失败：返回 needs_clarification + 澄清问题

### diagnose
执行核心诊断算法（贝叶斯推理）。

使用场景：
- match_phenomena 返回了 matched phenomena
- 需要更新假设置信度和获取推荐现象

输入参数：
- confirmed_phenomena: 已匹配的现象列表（含 phenomenon_id, phenomenon_description, user_observation, match_score）
- denied_phenomena: 否认的现象 ID 列表

输出：
- hypotheses: 假设列表（按置信度排序）
- recommendations: 推荐确认的现象列表

### query_progress
查询当前诊断进展。

使用场景：用户询问"现在怎么样了"、"进展如何"

### query_hypotheses
查询假设详情。

使用场景：用户想了解"还有什么可能"、"其他原因"

输入参数：
- top_k: 返回前 K 个假设（默认 5）

### query_relations
查询现象和根因的关联关系。

使用场景：用户想了解某个现象/根因的关联

输入参数：
- query_type: "phenomenon_to_root_causes" 或 "root_cause_to_phenomena"
- phenomenon_id: 现象 ID（当 query_type 为 phenomenon_to_root_causes 时）
- root_cause_id: 根因 ID（当 query_type 为 root_cause_to_phenomena 时）

## 决策规则

1. **用户有新观察描述** → 先调 match_phenomena
2. **match_phenomena 返回 all_matched: true** → 调 diagnose
3. **match_phenomena 返回 needs_clarification** → 直接回复（请求澄清）
4. **diagnose 返回结果** → **必须直接回复**（展示诊断结果和推荐现象，让用户确认）
5. **用户纯查询（无新观察）** → 调对应查询工具

**重要**：
- diagnose 执行后，必须选择 respond，向用户展示结果并等待反馈
- 同一轮循环中不要重复调用同一工具
- 如果 loop_context 包含 "工具 diagnose 执行结果"，必须选择 respond

## 输出格式

必须输出 JSON，格式如下：

### 调用工具
```json
{
  "decision": "call",
  "tool": "工具名",
  "tool_input": { ... },
  "reasoning": "决策理由"
}
```

### 直接回复
```json
{
  "decision": "respond",
  "response_context": {
    "type": "diagnosis_result" | "clarification_needed" | "progress_summary" | "greeting" | "error",
    "data": { ... }
  },
  "reasoning": "决策理由"
}
```
"""


class Planner:
    """Planner 决策层

    根据当前上下文决定下一步行动：调用工具或直接回复用户。
    使用 LLM 进行决策。
    """

    def __init__(self, llm_service: LLMService):
        """初始化 Planner

        Args:
            llm_service: LLM 服务
        """
        self._llm_service = llm_service

    def decide(
        self,
        session: SessionState,
        loop_context: str,
        dialogue_history: str = "",
    ) -> AgentDecision:
        """决定下一步行动

        Args:
            session: 当前会话状态
            loop_context: 当前循环上下文（用户输入或工具执行结果）
            dialogue_history: 最近对话历史

        Returns:
            AgentDecision 决策结果
        """
        # 构建 prompt
        user_prompt = self._build_prompt(session, loop_context, dialogue_history)

        # 调用 LLM
        response = self._llm_service.generate_simple(
            user_prompt,
            system_prompt=PLANNER_SYSTEM_PROMPT,
        )

        # 解析响应
        return self._parse_response(response)

    def _build_prompt(
        self,
        session: SessionState,
        loop_context: str,
        dialogue_history: str,
    ) -> str:
        """构建 user prompt"""
        sections = []

        # 会话状态
        sections.append("## 会话状态")
        sections.append(f"- 会话轮次: {session.rounds}")
        sections.append(f"- 已确认现象: {session.confirmed_count} 个")
        sections.append(f"- 已否认现象: {session.denied_count} 个")
        sections.append(f"- 当前假设数: {len(session.hypotheses)} 个")

        if session.top_hypothesis:
            sections.append(f"- 最可能根因: {session.top_hypothesis.root_cause_description}")
            sections.append(f"- 最高置信度: {session.top_hypothesis.confidence:.0%}")
        else:
            sections.append("- 最可能根因: 无")
            sections.append("- 最高置信度: 0%")

        # 当前待确认的现象
        sections.append("\n## 当前待确认的现象")
        if session.recommendations:
            for i, rec in enumerate(session.recommendations, 1):
                sections.append(f"[{i}] {rec.phenomenon_id}: {rec.description}")
        else:
            sections.append("无")

        # 最近对话历史
        sections.append("\n## 最近对话历史")
        sections.append(dialogue_history if dialogue_history else "无")

        # 当前循环上下文
        sections.append("\n## 当前循环上下文")
        sections.append(loop_context)

        sections.append("\n请决定下一步行动，输出 JSON。")

        return "\n".join(sections)

    def _parse_response(self, response: str) -> AgentDecision:
        """解析 LLM 响应

        Args:
            response: LLM 响应文本

        Returns:
            AgentDecision 决策结果
        """
        # 尝试提取 JSON
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取
            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        # 构建 AgentDecision
        decision_type = data.get("decision", "respond")
        tool = data.get("tool")
        tool_input = data.get("tool_input") or data.get("params")  # 兼容两种格式
        response_context = data.get("response_context")
        reasoning = data.get("reasoning", "")

        return AgentDecision(
            decision=decision_type,
            tool=tool,
            tool_input=tool_input,
            response_context=response_context,
            reasoning=reasoning,
        )

    def build_pending_recommendations_for_input(
        self,
        recommendations: List[Recommendation],
    ) -> List[dict]:
        """将推荐列表转换为 match_phenomena 需要的格式

        Args:
            recommendations: 推荐列表

        Returns:
            字典列表，用于 match_phenomena 的 pending_recommendations 参数
        """
        return [
            {
                "phenomenon_id": rec.phenomenon_id,
                "description": rec.description,
                "observation_method": rec.observation_method,
            }
            for rec in recommendations
        ]
