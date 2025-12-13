"""LLM API 调用服务

使用 OpenAI SDK 调用兼容 OpenAI API 的 LLM 服务
"""
import re
import time
from typing import List, Dict, Optional
import openai
from openai import APITimeoutError, APIConnectionError, RateLimitError
from dbdiag.utils.config import Config


# 匹配 <think>...</think> 标签（支持多行）
THINK_TAG_PATTERN = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class LLMService:
    """LLM 服务封装"""

    # 默认超时和重试参数
    DEFAULT_TIMEOUT = 30  # 秒
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY = 1  # 秒，重试间隔

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

        # 超时和重试参数（从配置读取或使用默认值）
        self.timeout = getattr(config.llm, 'timeout', self.DEFAULT_TIMEOUT)
        self.max_retries = getattr(config.llm, 'max_retries', self.DEFAULT_MAX_RETRIES)
        self.retry_delay = getattr(config.llm, 'retry_delay', self.DEFAULT_RETRY_DELAY)

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

        Raises:
            Exception: 重试耗尽后仍失败
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

        # 带重试的 API 调用
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    temperature=temperature if temperature is not None else self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout,
                )
                return self._clean_response(response.choices[0].message.content)

            except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # 等待后重试
                    time.sleep(self.retry_delay * (attempt + 1))  # 指数退避
                    continue
                else:
                    raise

            except Exception as e:
                # 其他错误不重试
                raise

        # 理论上不会到达这里，但为了安全
        if last_error:
            raise last_error

    def _clean_response(self, content: str) -> str:
        """清理 LLM 响应

        - 去除 <think>...</think> 标签（模型的思考过程）
        - 去除首尾空白

        Args:
            content: 原始响应内容

        Returns:
            清理后的响应内容
        """
        if not content:
            return ""
        # 去除 <think>...</think> 标签
        content = THINK_TAG_PATTERN.sub("", content)
        return content.strip()

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
