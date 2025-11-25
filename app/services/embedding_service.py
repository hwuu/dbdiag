"""Embedding API 调用服务

使用 OpenAI SDK 调用兼容 OpenAI API 的 Embedding 服务
"""
from typing import List
import openai
from app.utils.config import Config


class EmbeddingService:
    """Embedding 服务封装"""

    def __init__(self, config: Config):
        """
        初始化 Embedding 服务

        Args:
            config: 全局配置对象
        """
        self.config = config
        self.client = openai.OpenAI(
            api_key=config.embedding_model.api_key,
            base_url=config.embedding_model.api_base,
        )
        self.model = config.embedding_model.model
        self.dimension = config.embedding_model.dimension

    def encode(self, text: str) -> List[float]:
        """
        将单个文本编码为向量

        Args:
            text: 待编码的文本

        Returns:
            向量（浮点数列表）
        """
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=self.dimension,  # 指定输出维度
        )
        embedding = response.data[0].embedding

        # 验证维度
        if len(embedding) != self.dimension:
            raise ValueError(
                f"Embedding 维度不匹配：期望 {self.dimension}，实际 {len(embedding)}"
            )

        return embedding

    def encode_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        批量编码文本为向量

        Args:
            texts: 待编码的文本列表
            batch_size: 批次大小

        Returns:
            向量列表
        """
        all_embeddings = []

        # 分批处理
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self.dimension,  # 指定输出维度
            )

            # 提取 embeddings
            batch_embeddings = [item.embedding for item in response.data]

            # 验证维度
            for embedding in batch_embeddings:
                if len(embedding) != self.dimension:
                    raise ValueError(
                        f"Embedding 维度不匹配：期望 {self.dimension}，实际 {len(embedding)}"
                    )

            all_embeddings.extend(batch_embeddings)

        return all_embeddings
