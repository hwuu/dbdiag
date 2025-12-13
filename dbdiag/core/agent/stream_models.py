"""流式消息模型

定义 Agent 模块流式输出的消息类型和数据结构。
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class StreamMessageType(str, Enum):
    """流式消息类型"""

    PROGRESS = "progress"  # 进度信息
    CHUNK = "chunk"        # 响应文本增量
    FINAL = "final"        # 最终消息（含结构化数据）
    ERROR = "error"        # 错误


class StreamMessage(BaseModel):
    """流式消息

    统一的消息格式，用于 Agent 模块的流式输出。

    Attributes:
        type: 消息类型
        content: 文本内容（用于 PROGRESS, CHUNK, ERROR）
        data: 结构化数据（用于 FINAL）
    """

    type: StreamMessageType
    content: Optional[str] = None
    data: Optional[dict] = None
