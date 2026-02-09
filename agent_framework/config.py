#!/usr/bin/env python3
"""Agent Framework Configuration"""

import os
import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class ModelConfig:
    """模型配置"""
    provider: str = "openai"
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "sk-no-key-required"
    model: str = "gpt-4"
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 60
    retry_times: int = 3
    retry_delay: float = 1.0
    # 会话管理
    max_messages: int = 50  # 最大消息数量，超过则滑动窗口
    rate_limit_delay: float = 0.5  # 请求间最小延迟(秒)


@dataclass
class WorkspaceConfig:
    """工作空间配置"""
    root_path: str = "./workspace"
    allow_outside: bool = False


@dataclass
class AgentConfig:
    """Agent配置"""
    name: str = "Agent"
    description: str = "A powerful AI agent"
    max_iterations: int = 100
    enable_streaming: bool = True


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "INFO"
    file_path: Optional[str] = None


@dataclass
class FrameworkConfig:
    """框架主配置"""
    version: str = "1.0.0"
    model: ModelConfig = field(default_factory=ModelConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    skills_dir: str = "./skills"
    enable_sub_agents: bool = True
    event_queue_size: int = 1000


class ConfigManager:
    _instance: Optional['ConfigManager'] = None
    _config: Optional[FrameworkConfig] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self._config = FrameworkConfig()

    @classmethod
    def get_instance(cls) -> 'ConfigManager':
        return cls() if cls._instance is None else cls._instance

    @classmethod
    def get_config(cls) -> FrameworkConfig:
        return cls.get_instance()._config

    def load_from_file(self, config_path: str) -> bool:
        path = Path(config_path)
        if not path.exists():
            return False
        try:
            content = path.read_text(encoding="utf-8")
            config_dict = yaml.safe_load(content) or {} if path.suffix in [".yaml", ".yml"] else json.loads(content)
            self._apply_dict(config_dict)
            return True
        except Exception as e:
            print(f"[ConfigManager] Failed to load config: {e}")
            return False

    def load_from_env(self, prefix: str = "AGENT_") -> int:
        mappings = {
            f"{prefix}MODEL_BASE_URL": ("model", "base_url"),
            f"{prefix}MODEL_API_KEY": ("model", "api_key"),
            f"{prefix}MODEL_MODEL": ("model", "model"),
            f"{prefix}WORKSPACE_ROOT_PATH": ("workspace", "root_path"),
            f"{prefix}AGENT_NAME": ("agent", "name"),
            f"{prefix}LOGGING_LEVEL": ("logging", "level"),
            f"{prefix}SKILLS_DIR": ("skills_dir", None),
        }
        count = 0
        for env_key, (section, key) in mappings.items():
            value = os.environ.get(env_key)
            if value is not None:
                self._set_nested_value(section, key, value)
                count += 1
        return count

    def _apply_dict(self, config_dict: Dict[str, Any]) -> int:
        count = 0
        for key, value in config_dict.items():
            if hasattr(self._config, key):
                if isinstance(value, dict) and hasattr(getattr(self._config, key), '__dataclass_fields__'):
                    nested = getattr(self._config, key)
                    for k, v in value.items():
                        if hasattr(nested, k):
                            setattr(nested, k, v)
                            count += 1
                else:
                    setattr(self._config, key, value)
                    count += 1
        return count

    def _set_nested_value(self, section: str, key: str, value: str):
        section_obj = getattr(self._config, section, None)
        if section_obj and key and hasattr(section_obj, key):
            setattr(section_obj, key, value)
        elif section == "skills_dir" and key is None:
            self._config.skills_dir = value


def get_config() -> FrameworkConfig:
    return ConfigManager.get_config()


def create_config(config_path: str = None) -> FrameworkConfig:
    manager = ConfigManager.get_instance()
    if config_path is None:
        for default_path in ["config.yaml", "config.yml", "config.json"]:
            if Path(default_path).exists():
                config_path = default_path
                break
    if config_path:
        manager.load_from_file(config_path)
    manager.load_from_env()
    return manager.get_config()
