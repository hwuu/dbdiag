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
- confirmations: 直接确认的现象序号或 ID 列表（如用户说"1确认"则传 ["1"]）
- denials: 否认的现象序号或 ID 列表
- dialogue_history: 最近对话历史（用于指代消解）
- pending_recommendations: 当前待确认的现象列表

**重要**：
- 如果用户输入包含多个观察（用"并且"、"而且"、"同时"、"，"等连接），必须拆分成多个 raw_observations
- 例如：用户说"xxx，并且 yyy"，应拆分为两个 raw_observations：[{description: "xxx"}, {description: "yyy"}]
- 如果用户描述明显对应待确认现象列表中的某项，应放入 confirmations（使用序号如 "1", "2"）

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
2. **match_phenomena 返回 all_matched: true** → **必须调 diagnose**（不能直接 respond）
3. **match_phenomena 返回 needs_clarification** → 直接回复（请求澄清）
4. **diagnose 返回结果** → **必须直接回复**（展示诊断结果和推荐现象，让用户确认）
5. **用户纯查询（无新观察）** → 调对应查询工具

**重要**：
- **match_phenomena 执行成功（all_matched: true）后，必须调 diagnose，禁止直接 respond**
- diagnose 执行后，必须选择 respond，向用户展示结果并等待反馈
- 同一轮循环中不要重复调用同一工具
- 如果 loop_context 包含 "工具 diagnose 执行结果"，必须选择 respond
- 如果 loop_context 包含 "工具 match_phenomena 执行结果" 且 all_matched 为 true，必须选择 call diagnose

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

## 示例

### 示例 1：用户确认多个现象
待确认现象：
[1] P-0001: EXPLAIN 显示 Nested Loop 导致笛卡尔积
[2] P-0002: 在 Join 列上创建索引后查询时间降低

用户输入："EXPLAIN 显示 Nested Loop，并且创建索引后速度提升了"

应输出：
```json
{
  "decision": "call",
  "tool": "match_phenomena",
  "tool_input": {
    "raw_observations": [
      {"description": "EXPLAIN 显示 Nested Loop"},
      {"description": "创建索引后速度提升了"}
    ],
    "confirmations": [],
    "denials": []
  },
  "reasoning": "用户描述了两个观察，需要拆分后匹配"
}
```

### 示例 2：用户用序号确认
用户输入："1 和 2 都确认"

应输出：
```json
{
  "decision": "call",
  "tool": "match_phenomena",
  "tool_input": {
    "raw_observations": [],
    "confirmations": ["1", "2"],
    "denials": []
  },
  "reasoning": "用户直接确认了序号 1 和 2"
}
```

### 示例 3：match_phenomena 成功后调 diagnose
当前循环上下文：
工具 match_phenomena 执行结果:
```json
{
  "all_matched": true,
  "interpreted": [
    {"matched_phenomenon": {"phenomenon_id": "P-0012", "match_score": 0.88}}
  ]
}
```

应输出（**必须调 diagnose，禁止 respond**）：
```json
{
  "decision": "call",
  "tool": "diagnose",
  "tool_input": {
    "confirmed_phenomena": [
      {"phenomenon_id": "P-0012", "match_score": 0.88}
    ],
    "denied_phenomena": []
  },
  "reasoning": "match_phenomena 返回 all_matched=true，必须调用 diagnose 更新假设"
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
        response = self._llm_service.generate(
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
