"""Config 模块单元测试"""
import pytest
from pathlib import Path
import sys
import tempfile
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.utils.config import Config, LLMConfig, EmbeddingModelConfig, load_config


class TestConfigModels:
    """配置模型测试"""

    def test_llm_config(self):
        """测试:LLM 配置"""
        config = LLMConfig(
            api_base="https://api.test.com",
            api_key="test-key",
            model="gpt-4",
        )

        assert config.api_base == "https://api.test.com"
        assert config.api_key == "test-key"
        assert config.model == "gpt-4"
        assert config.temperature == 0.2  # 默认值
        assert config.max_tokens == 16384  # 默认值

    def test_llm_config_with_custom_values(self):
        """测试:自定义 LLM 配置"""
        config = LLMConfig(
            api_base="https://api.test.com",
            api_key="test-key",
            model="gpt-3.5-turbo",
            temperature=0.5,
            max_tokens=4096,
            system_prompt="You are a helpful assistant",
        )

        assert config.temperature == 0.5
        assert config.max_tokens == 4096
        assert config.system_prompt == "You are a helpful assistant"

    def test_embedding_model_config(self):
        """测试:Embedding 配置"""
        config = EmbeddingModelConfig(
            api_base="https://api.test.com",
            api_key="test-key",
            model="text-embedding-3-large",
        )

        assert config.api_base == "https://api.test.com"
        assert config.model == "text-embedding-3-large"
        assert config.dimension == 1024  # 默认值

    def test_full_config(self):
        """测试:完整配置"""
        config = Config(
            llm=LLMConfig(
                api_base="https://api.test.com",
                api_key="llm-key",
                model="gpt-4",
            ),
            embedding_model=EmbeddingModelConfig(
                api_base="https://api.test.com",
                api_key="emb-key",
                model="text-embedding-3-large",
                dimension=2048,
            ),
        )

        assert config.llm.model == "gpt-4"
        assert config.embedding_model.dimension == 2048


class TestLoadConfig:
    """配置加载测试"""

    @pytest.fixture
    def temp_config_file(self):
        """创建临时配置文件"""
        config_data = {
            "llm": {
                "api_base": "https://api.openai.com/v1",
                "api_key": "test-llm-key",
                "model": "gpt-4",
                "temperature": 0.3,
                "max_tokens": 8192,
            },
            "embedding_model": {
                "api_base": "https://api.openai.com/v1",
                "api_key": "test-emb-key",
                "model": "text-embedding-3-large",
                "dimension": 1024,
            },
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(config_data, f)
            temp_path = f.name

        yield temp_path

        # 清理
        Path(temp_path).unlink(missing_ok=True)

    def test_load_config_from_file(self, temp_config_file):
        """测试:从文件加载配置"""
        config = load_config(temp_config_file)

        assert config.llm.api_key == "test-llm-key"
        assert config.llm.model == "gpt-4"
        assert config.llm.temperature == 0.3
        assert config.embedding_model.model == "text-embedding-3-large"
        assert config.embedding_model.dimension == 1024

    def test_load_nonexistent_config(self):
        """测试:加载不存在的配置文件"""
        with pytest.raises(FileNotFoundError, match="配置文件不存在"):
            load_config("/path/to/nonexistent/config.yaml")

    def test_config_serialization(self, temp_config_file):
        """测试:配置序列化和反序列化"""
        config1 = load_config(temp_config_file)

        # 转为字典
        config_dict = config1.model_dump()
        assert "llm" in config_dict
        assert "embedding_model" in config_dict

        # 从字典重建
        config2 = Config(**config_dict)
        assert config2.llm.model == config1.llm.model
        assert config2.embedding_model.dimension == config1.embedding_model.dimension


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
