"""输入分析器

解析用户输入，提取症状增量（确认、否认、新观察）。
"""

import re
import json
from typing import List, Optional
from dataclasses import dataclass, field

from dbdiag.services.llm_service import LLMService


@dataclass
class SymptomDelta:
    """症状增量

    记录用户输入带来的症状变化。

    Attributes:
        confirmations: 确认的推荐现象 ID 列表
        denials: 否认的推荐现象 ID 列表
        new_observations: 用户主动描述的新观察文本列表
    """

    confirmations: List[str] = field(default_factory=list)
    denials: List[str] = field(default_factory=list)
    new_observations: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.confirmations and not self.denials and not self.new_observations


class InputAnalyzer:
    """输入分析器

    解析用户输入，识别：
    1. 对推荐现象的确认/否认
    2. 用户主动描述的新观察

    支持的输入格式：
    - "1确认 2否定 3确认" - 批量确认/否定
    - "确认" / "是" - 确认所有推荐
    - "全否定" / "都不是" - 否定所有推荐
    - 自然语言描述 - LLM 结构化提取
    """

    # 简单否定关键词
    DENY_ALL_KEYWORDS = ["全否定", "都否定", "都不是", "全部否定", "都没有", "都没看到"]

    # 简单确认关键词
    CONFIRM_ALL_KEYWORDS = ["确认", "是", "是的", "看到了", "观察到", "都确认", "全部确认"]

    # 批量确认格式正则
    BATCH_PATTERN = re.compile(r'(\d+)\s*(确认|否定|是|否|正常|异常|没有|不是)')

    def __init__(self, llm_service: Optional[LLMService] = None):
        """初始化输入分析器

        Args:
            llm_service: LLM 服务（用于自然语言解析）
        """
        self.llm_service = llm_service

    def analyze(
        self,
        user_input: str,
        recommended_phenomenon_ids: List[str],
        phenomenon_descriptions: Optional[dict] = None,
    ) -> SymptomDelta:
        """分析用户输入

        Args:
            user_input: 用户输入文本
            recommended_phenomenon_ids: 当前推荐的现象 ID 列表
            phenomenon_descriptions: 现象描述映射 {phenomenon_id: description}

        Returns:
            症状增量
        """
        user_input = user_input.strip()
        if not user_input:
            return SymptomDelta()

        # 没有推荐的现象，直接作为新观察
        if not recommended_phenomenon_ids:
            return SymptomDelta(new_observations=[user_input])

        # 1. 尝试全局否定
        if any(kw in user_input for kw in self.DENY_ALL_KEYWORDS):
            return SymptomDelta(denials=list(recommended_phenomenon_ids))

        # 2. 尝试批量格式解析
        batch_matches = self.BATCH_PATTERN.findall(user_input)
        if batch_matches:
            return self._parse_batch_format(batch_matches, recommended_phenomenon_ids, user_input)

        # 3. 尝试全局确认
        if any(kw in user_input for kw in self.CONFIRM_ALL_KEYWORDS):
            return SymptomDelta(confirmations=list(recommended_phenomenon_ids))

        # 4. 自然语言解析（需要 LLM）
        if self.llm_service:
            return self._parse_with_llm(
                user_input, recommended_phenomenon_ids, phenomenon_descriptions or {}
            )

        # 5. 兜底：作为新观察
        return SymptomDelta(new_observations=[user_input])

    def _parse_batch_format(
        self,
        matches: List[tuple],
        recommended_ids: List[str],
        full_input: str,
    ) -> SymptomDelta:
        """解析批量格式

        如 "1确认 2否定 3确认，另外发现慢查询很多"
        """
        confirmations = []
        denials = []

        for idx_str, action in matches:
            idx = int(idx_str) - 1  # 转为 0-based
            if 0 <= idx < len(recommended_ids):
                phenomenon_id = recommended_ids[idx]
                if action in ("确认", "是", "正常"):
                    confirmations.append(phenomenon_id)
                elif action in ("否定", "否", "异常", "没有", "不是"):
                    denials.append(phenomenon_id)

        # 检查是否有额外的新观察
        # 移除已解析的部分，看剩余内容
        remaining = self.BATCH_PATTERN.sub('', full_input).strip()
        # 移除常见连接词
        remaining = re.sub(r'^[,，、。；;]+', '', remaining).strip()
        remaining = re.sub(r'^(另外|并且|同时|还有|而且)\s*', '', remaining).strip()

        new_observations = [remaining] if remaining and len(remaining) > 3 else []

        return SymptomDelta(
            confirmations=confirmations,
            denials=denials,
            new_observations=new_observations,
        )

    def _parse_with_llm(
        self,
        user_input: str,
        recommended_ids: List[str],
        phenomenon_descriptions: dict,
    ) -> SymptomDelta:
        """使用 LLM 解析自然语言输入"""
        # 构建待确认现象列表
        pending_list = []
        for i, pid in enumerate(recommended_ids, 1):
            desc = phenomenon_descriptions.get(pid, pid)
            pending_list.append(f"{i}. [{pid}] {desc}")

        system_prompt = """你是一个对话分析助手。分析用户消息，判断用户对每个待确认现象的反馈。

输出 JSON 格式：
{
  "feedback": {
    "<phenomenon_id>": "confirmed" | "denied" | "unknown"
  },
  "new_observations": ["用户提到的新观察1", "用户提到的新观察2"]
}

判断规则：
- confirmed: 用户明确确认看到了该现象，或描述符合该现象
- denied: 用户明确否认，或描述与该现象相反
- unknown: 用户未提及该现象

new_observations: 用户描述的、不在待确认列表中的新观察。只提取具体的技术观察，忽略闲聊。

只输出 JSON，不要其他内容。"""

        user_prompt = f"""待确认现象：
{chr(10).join(pending_list)}

用户消息: {user_input}"""

        try:
            response = self.llm_service.generate_simple(
                user_prompt,
                system_prompt=system_prompt,
            )

            # 解析 JSON
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)

            result = json.loads(response)

            # 处理反馈
            confirmations = []
            denials = []
            feedback = result.get("feedback", {})

            for pid in recommended_ids:
                status = feedback.get(pid, "unknown")
                if status == "confirmed":
                    confirmations.append(pid)
                elif status == "denied":
                    denials.append(pid)

            new_observations = result.get("new_observations", [])

            return SymptomDelta(
                confirmations=confirmations,
                denials=denials,
                new_observations=new_observations,
            )

        except Exception:
            # LLM 失败，作为新观察
            return SymptomDelta(new_observations=[user_input])
