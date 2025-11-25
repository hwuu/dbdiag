"""配置加载模块"""
import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class LLMConfig(BaseModel):
    """LLM 配置"""
    api_base: str
    api_key: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 16384
    system_prompt: str = ""


class EmbeddingModelConfig(BaseModel):
    """Embedding 模型配置"""
    api_base: str
    api_key: str
    model: str
    dimension: int = 1024


class Config(BaseModel):
    """全局配置"""
    llm: LLMConfig
    embedding_model: EmbeddingModelConfig


def load_config(config_path: Optional[str] = None) -> Config:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径，默认为项目根目录的 config.yaml

    Returns:
        Config: 配置对象
    """
    if config_path is None:
        # 默认使用项目根目录的 config.yaml
        project_root = Path(__file__).parent.parent.parent
        config_path = project_root / "config.yaml"

    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {config_path}\n"
            f"请复制 config.yaml.example 并修改为 config.yaml"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    return Config(**config_dict)
