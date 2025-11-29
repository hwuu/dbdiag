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


class RecommenderWeightsConfig(BaseModel):
    """推荐引擎权重配置"""
    popularity: float = 0.15
    specificity: float = 0.20
    hypothesis_priority: float = 0.40
    information_gain: float = 0.25


class RecommenderConfig(BaseModel):
    """推荐引擎配置"""
    # 权重
    weights: RecommenderWeightsConfig = RecommenderWeightsConfig()
    # 检索相关
    retrieval_top_k: int = 5  # 检索 top-m 现象
    recommend_top_n: int = 3  # 推荐 top-n 现象
    # 置信度阈值
    high_confidence_threshold: float = 0.80  # 高置信度阈值，达到后确认根因
    medium_confidence_threshold: float = 0.50  # 中等置信度阈值
    # information_gain 子权重
    confirmation_gain_weight: float = 0.6
    discrimination_power_weight: float = 0.4


class Config(BaseModel):
    """全局配置"""
    llm: LLMConfig
    embedding_model: EmbeddingModelConfig
    recommender: RecommenderConfig = RecommenderConfig()


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
