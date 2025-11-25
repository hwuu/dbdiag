"""LLM API 调用服务

使用 OpenAI SDK 调用兼容 OpenAI API 的 LLM 服务
"""
from typing import List, Dict, Optional
import openai
from app.utils.config import Config


class LLMService:
    """LLM 服务封装"""

    def __init__(self, config: Config):
        """
        初始化 LLM 服务

        Args:
            config: 全局配置对象
        """
        self.config = config
        self.client = openai.OpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.api_base,
        )
        self.model = config.llm.model
        self.temperature = config.llm.temperature
        self.max_tokens = config.llm.max_tokens
        self.system_prompt = config.llm.system_prompt

    def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        生成回复

        Args:
            messages: 对话消息列表 [{"role": "user", "content": "..."}, ...]
            system_prompt: 系统提示（可选，覆盖默认）
            temperature: 温度参数（可选，覆盖默认）

        Returns:
            生成的回复文本
        """
        # 构建完整的消息列表
        full_messages = []

        # 添加系统提示
        if system_prompt is None:
            system_prompt = self.system_prompt

        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})

        # 添加对话历史
        full_messages.extend(messages)

        # 调用 API
        response = self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=self.max_tokens,
        )

        return response.choices[0].message.content

    def generate_simple(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        简单生成（单轮对话）

        Args:
            prompt: 用户输入
            system_prompt: 系统提示（可选）

        Returns:
            生成的回复文本
        """
        messages = [{"role": "user", "content": prompt}]
        return self.generate(messages, system_prompt=system_prompt)
