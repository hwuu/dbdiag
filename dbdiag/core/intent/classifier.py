"""意图分类器

基于 LLM 的用户意图分类器。
"""

import json
import re
from typing import List, Dict, Optional

from dbdiag.core.intent.models import UserIntent, IntentType, QueryType
from dbdiag.services.llm_service import LLMService


class IntentClassifier:
    """意图分类器

    基于 LLM 分析用户输入，识别意图类型：
    - feedback: 诊断反馈（确认/否认现象、描述新观察）
    - query: 系统查询（询问进展、结论、假设）
    - mixed: 混合意图

    完全基于 LLM，不使用关键字匹配。
    """

    SYSTEM_PROMPT = """你是用户意图分析助手。分析数据库诊断对话中的用户输入。

## 意图类型

1. **feedback**（诊断反馈）
   - 用户报告观察结果、确认/否认推荐的现象
   - 示例："IO 正常"、"1确认 2否定"、"CPU 95%，内存也快满了"

2. **query**（系统查询）
   - 用户询问诊断进展、系统状态，不包含观察结果
   - 示例："检查了什么？"、"有什么结论？"、"还有哪些可能？"

3. **mixed**（混合）
   - 同时包含 feedback 和 query
   - 示例："IO 正常，现在有什么结论？"

## 查询子类型（query_type）

- **progress**: 询问诊断进展（"检查了什么"、"做了哪些"）
- **conclusion**: 询问当前结论（"有什么结论"、"能确定吗"）
- **hypotheses**: 询问假设列表（"还有哪些可能"、"其他原因"）

## 输出格式（JSON）

{
  "intent_type": "feedback" | "query" | "mixed",
  "confirmations": ["P-0001"],           // 确认的现象 ID（仅当用户明确确认时）
  "denials": ["P-0002"],                 // 否认的现象 ID（仅当用户明确否认时）
  "new_observations": ["观察1", "观察2"], // 新观察（可多个，提取具体技术观察）
  "query_type": "progress" | "conclusion" | "hypotheses" | null,
  "confidence": 0.95                     // 分类置信度 0-1
}

## 判断规则

1. confirmations: 用户明确说"确认"、"是"、"看到了"，或数字+确认（如"1确认"）
2. denials: 用户明确说"否定"、"没有"、"不是"，或数字+否定（如"2否定"）
3. new_observations: 用户描述的具体技术观察，每个独立观察单独提取
4. 如果用户只是提问而没有任何观察结果，intent_type 为 "query"
5. 如果用户既有观察又有提问，intent_type 为 "mixed"

只输出 JSON，不要其他内容。"""

    def __init__(self, llm_service: LLMService):
        """初始化

        Args:
            llm_service: LLM 服务
        """
        self.llm_service = llm_service

    def classify(
        self,
        user_input: str,
        recommended_phenomenon_ids: Optional[List[str]] = None,
        phenomenon_descriptions: Optional[Dict[str, str]] = None,
    ) -> UserIntent:
        """分类用户意图

        Args:
            user_input: 用户输入文本
            recommended_phenomenon_ids: 当前推荐的现象 ID 列表
            phenomenon_descriptions: 现象描述映射 {phenomenon_id: description}

        Returns:
            用户意图对象
        """
        user_input = user_input.strip()
        if not user_input:
            return UserIntent()

        # 构建用户 prompt
        user_prompt = self._build_user_prompt(
            user_input,
            recommended_phenomenon_ids or [],
            phenomenon_descriptions or {},
        )

        try:
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=self.SYSTEM_PROMPT,
            )
            return self._parse_response(response, recommended_phenomenon_ids or [])

        except Exception:
            # LLM 失败，兜底：作为新观察的 feedback
            return UserIntent(
                intent_type=IntentType.FEEDBACK,
                new_observations=[user_input],
                confidence=0.5,
            )

    def _build_user_prompt(
        self,
        user_input: str,
        recommended_ids: List[str],
        phenomenon_descriptions: Dict[str, str],
    ) -> str:
        """构建用户 prompt"""
        parts = []

        # 当前推荐的现象
        if recommended_ids:
            parts.append("## 当前推荐的现象\n")
            for i, pid in enumerate(recommended_ids, 1):
                desc = phenomenon_descriptions.get(pid, pid)
                parts.append(f"{i}. [{pid}] {desc}")
            parts.append("")
        else:
            parts.append("## 当前推荐的现象\n（无推荐现象）\n")

        # 用户输入
        parts.append(f"## 用户输入\n{user_input}")

        return "\n".join(parts)

    def _parse_response(
        self,
        response: str,
        recommended_ids: List[str],
    ) -> UserIntent:
        """解析 LLM 响应

        Args:
            response: LLM 响应文本
            recommended_ids: 推荐的现象 ID 列表（用于验证）

        Returns:
            用户意图对象
        """
        # 清理 markdown 代码块
        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r'^```\w*\n?', '', response)
            response = re.sub(r'\n?```$', '', response)

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # JSON 解析失败，兜底
            return UserIntent(
                intent_type=IntentType.FEEDBACK,
                new_observations=[response],
                confidence=0.3,
            )

        # 解析意图类型
        intent_type_str = data.get("intent_type", "feedback")
        try:
            intent_type = IntentType(intent_type_str)
        except ValueError:
            intent_type = IntentType.FEEDBACK

        # 解析确认/否认（验证 ID 有效性）
        confirmations = []
        denials = []

        for pid in data.get("confirmations", []):
            if self._validate_phenomenon_id(pid, recommended_ids):
                confirmations.append(pid)

        for pid in data.get("denials", []):
            if self._validate_phenomenon_id(pid, recommended_ids):
                denials.append(pid)

        # 解析新观察
        new_observations = data.get("new_observations", [])
        if isinstance(new_observations, str):
            new_observations = [new_observations] if new_observations else []

        # 解析查询类型
        query_type = None
        query_type_str = data.get("query_type")
        if query_type_str:
            try:
                query_type = QueryType(query_type_str)
            except ValueError:
                pass

        # 解析置信度
        confidence = data.get("confidence", 1.0)
        if not isinstance(confidence, (int, float)):
            confidence = 1.0
        confidence = max(0.0, min(1.0, float(confidence)))

        return UserIntent(
            intent_type=intent_type,
            confirmations=confirmations,
            denials=denials,
            new_observations=new_observations,
            query_type=query_type,
            confidence=confidence,
        )

    def _validate_phenomenon_id(
        self,
        pid: str,
        recommended_ids: List[str],
    ) -> bool:
        """验证现象 ID 有效性

        支持两种格式：
        1. 完整 ID: "P-0001"
        2. 数字索引: "1" -> recommended_ids[0]
        """
        if not pid:
            return False

        # 完整 ID
        if pid in recommended_ids:
            return True

        # 数字索引转换
        if pid.isdigit():
            idx = int(pid) - 1  # 1-based to 0-based
            if 0 <= idx < len(recommended_ids):
                return True

        return False

    def _convert_index_to_id(
        self,
        pid: str,
        recommended_ids: List[str],
    ) -> Optional[str]:
        """将数字索引转换为现象 ID"""
        if pid in recommended_ids:
            return pid

        if pid.isdigit():
            idx = int(pid) - 1
            if 0 <= idx < len(recommended_ids):
                return recommended_ids[idx]

        return None
