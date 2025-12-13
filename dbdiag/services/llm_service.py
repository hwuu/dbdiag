"""LLM API 调用服务

使用 OpenAI SDK 调用兼容 OpenAI API 的 LLM 服务
"""
import asyncio
import re
import time
from typing import List, Dict, Optional, Callable, AsyncGenerator
import openai
from openai import APITimeoutError, APIConnectionError, RateLimitError, AsyncOpenAI
from dbdiag.utils.config import Config


# 匹配 <think>...</think> 标签（支持多行）
THINK_TAG_PATTERN = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# 进度回调类型
ProgressCallback = Callable[[str], None]


class ThinkTagFilter:
    """实时 <think> 标签过滤器

    状态机设计，支持流式增量过滤。
    """

    STATE_NORMAL = "NORMAL"
    STATE_IN_OPEN_TAG = "IN_OPEN_TAG"
    STATE_IN_THINK = "IN_THINK"
    STATE_IN_CLOSE_TAG = "IN_CLOSE_TAG"

    OPEN_TAG = "<think>"
    CLOSE_TAG = "</think>"

    def __init__(self):
        self._state = self.STATE_NORMAL
        self._buffer = ""

    def process(self, chunk: str) -> str:
        """处理增量文本，返回应输出的部分"""
        output = []
        for char in chunk:
            result = self._process_char(char)
            if result:
                output.append(result)
        return "".join(output)

    def _process_char(self, char: str) -> str:
        if self._state == self.STATE_NORMAL:
            if char == "<":
                self._state = self.STATE_IN_OPEN_TAG
                self._buffer = char
                return ""
            return char

        elif self._state == self.STATE_IN_OPEN_TAG:
            self._buffer += char
            if self._buffer == self.OPEN_TAG:
                self._state = self.STATE_IN_THINK
                self._buffer = ""
                return ""
            elif not self.OPEN_TAG.startswith(self._buffer):
                result = self._buffer
                self._buffer = ""
                self._state = self.STATE_NORMAL
                return result
            return ""

        elif self._state == self.STATE_IN_THINK:
            if char == "<":
                self._state = self.STATE_IN_CLOSE_TAG
                self._buffer = char
            return ""

        elif self._state == self.STATE_IN_CLOSE_TAG:
            self._buffer += char
            if self._buffer == self.CLOSE_TAG:
                self._state = self.STATE_NORMAL
                self._buffer = ""
                return ""
            elif not self.CLOSE_TAG.startswith(self._buffer):
                self._buffer = ""
                self._state = self.STATE_IN_THINK
                return ""
            return ""

        return ""

    def flush(self) -> str:
        """流结束时刷新 buffer"""
        if self._state == self.STATE_IN_OPEN_TAG:
            result = self._buffer
            self._buffer = ""
            self._state = self.STATE_NORMAL
            return result
        return ""

    def reset(self):
        """重置过滤器状态"""
        self._state = self.STATE_NORMAL
        self._buffer = ""


class LLMService:
    """LLM 服务封装"""

    # 默认超时和重试参数
    DEFAULT_TIMEOUT = 30  # 秒
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY = 1  # 秒，重试间隔

    def __init__(
        self,
        config: Config,
        progress_callback: Optional[ProgressCallback] = None,
    ):
        """
        初始化 LLM 服务

        Args:
            config: 全局配置对象
            progress_callback: 进度回调函数（用于报告重试等状态）
        """
        self.config = config
        self._progress_callback = progress_callback
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

        # 异步客户端（延迟初始化）
        self._async_client: Optional[AsyncOpenAI] = None

    @property
    def async_client(self) -> AsyncOpenAI:
        """获取异步客户端（延迟初始化）"""
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.api_base,
            )
        return self._async_client

    def _report_progress(self, message: str):
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(message)

    def _generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """内部方法：生成回复

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
                error_type = type(e).__name__
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (attempt + 1)
                    self._report_progress(
                        f"LLM 调用失败 ({error_type})，{wait_time}s 后重试 ({attempt + 1}/{self.max_retries})..."
                    )
                    # 等待后重试
                    time.sleep(wait_time)  # 指数退避
                    continue
                else:
                    self._report_progress(
                        f"LLM 调用失败 ({error_type})，重试次数已用尽"
                    )
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

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """生成回复（单轮对话）

        Args:
            prompt: 用户输入
            system_prompt: 系统提示（可选）

        Returns:
            生成的回复文本
        """
        messages = [{"role": "user", "content": prompt}]
        return self._generate(messages, system_prompt=system_prompt)

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """流式生成回复（单轮对话）

        Args:
            prompt: 用户输入
            system_prompt: 系统提示（可选）

        Yields:
            生成的文本增量（已过滤 <think> 标签）
        """
        messages = [{"role": "user", "content": prompt}]
        async for chunk in self._generate_stream(messages, system_prompt=system_prompt):
            yield chunk

    async def _generate_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        """内部方法：流式生成回复

        带重试机制和实时 <think> 标签过滤。

        Args:
            messages: 对话消息列表
            system_prompt: 系统提示（可选）
            temperature: 温度参数（可选）

        Yields:
            生成的文本增量

        Raises:
            Exception: 重试耗尽后仍失败
        """
        # 构建完整的消息列表
        full_messages = []

        if system_prompt is None:
            system_prompt = self.system_prompt

        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})

        full_messages.extend(messages)

        # 创建 think 标签过滤器
        think_filter = ThinkTagFilter()

        # 带重试的流式 API 调用
        last_error = None
        for attempt in range(self.max_retries):
            try:
                stream = await self.async_client.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    temperature=temperature if temperature is not None else self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout,
                    stream=True,
                )

                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        # 实时过滤 <think> 标签
                        filtered = think_filter.process(content)
                        if filtered:
                            yield filtered

                # 流结束，刷新 filter
                remaining = think_filter.flush()
                if remaining:
                    yield remaining

                return  # 成功完成

            except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                last_error = e
                error_type = type(e).__name__
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (attempt + 1)
                    self._report_progress(
                        f"LLM 流式调用失败 ({error_type})，{wait_time}s 后重试 ({attempt + 1}/{self.max_retries})..."
                    )
                    await asyncio.sleep(wait_time)
                    # 重置过滤器状态
                    think_filter.reset()
                    continue
                else:
                    self._report_progress(
                        f"LLM 流式调用失败 ({error_type})，重试次数已用尽"
                    )
                    raise

            except Exception:
                # 其他错误不重试
                raise

        # 理论上不会到达这里
        if last_error:
            raise last_error

