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
    sub_agents_dir: str = "./agents"
    enable_sub_agents: bool = True
    event_queue_size: int = 1000


class ConfigManager:
    _instance: Optional['ConfigManager'] = None
    _config: Optional[FrameworkConfig] = None
    _config_dir: Optional[Path] = None  # 配置文件所在目录

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

    @classmethod
    def get_config_dir(cls) -> Optional[Path]:
        """获取配置文件所在目录"""
        return cls._config_dir

    def load_from_file(self, config_path: str) -> bool:
        path = Path(config_path)
        if not path.exists():
            return False
        try:
            # 保存配置文件所在目录
            ConfigManager._config_dir = path.parent.resolve()
            content = path.read_text(encoding="utf-8")
            config_dict = yaml.safe_load(content) or {} if path.suffix in [".yaml", ".yml"] else json.loads(content)
            self._apply_dict(config_dict)
            # 转换相对路径为绝对路径（相对于配置文件目录）
            self._resolve_relative_paths()
            return True
        except Exception as e:
            print(f"[ConfigManager] Failed to load config: {e}")
            return False

    def _resolve_relative_paths(self):
        """将相对路径转换为相对于配置文件目录的绝对路径"""
        config_dir = ConfigManager._config_dir
        if config_dir is None:
            return

        # 顶层路径字段（直接位于 _config 下）
        top_level_paths = ["skills_dir", "sub_agents_dir"]
        for field_name in top_level_paths:
            value = getattr(self._config, field_name, None)
            if value:
                setattr(self._config, field_name, self._resolve_path(value, config_dir))

        # 嵌套路径字段（位于嵌套配置对象下）
        nested_paths = [
            (self._config.workspace, "root_path"),
            (self._config.logging, "file_path"),
        ]
        for section_obj, key in nested_paths:
            value = getattr(section_obj, key, None)
            if value:
                setattr(section_obj, key, self._resolve_path(value, config_dir))

    def _resolve_path(self, path: str, base_dir: Path) -> str:
        """解析路径，如果是相对路径则相对于 base_dir"""
        if not path:
            return path
        p = Path(path)
        return str((base_dir / p).resolve()) if not p.is_absolute() else str(p.resolve())

    def load_from_env(self, prefix: str = "AGENT_") -> int:
        mappings = {
            f"{prefix}MODEL_BASE_URL": ("model", "base_url"),
            f"{prefix}MODEL_API_KEY": ("model", "api_key"),
            f"{prefix}MODEL_MODEL": ("model", "model"),
            f"{prefix}WORKSPACE_ROOT_PATH": ("workspace", "root_path"),
            f"{prefix}AGENT_NAME": ("agent", "name"),
            f"{prefix}LOGGING_LEVEL": ("logging", "level"),
            f"{prefix}SKILLS_DIR": ("skills_dir", None),
            f"{prefix}SUB_AGENTS_DIR": ("sub_agents_dir", None),
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
        elif section == "sub_agents_dir" and key is None:
            self._config.sub_agents_dir = value


def get_config() -> FrameworkConfig:
    """获取配置，如果未初始化则自动创建"""
    manager = ConfigManager.get_instance()
    # 检查是否已经加载过配置（通过 _config_dir 判断）
    if manager._config is None or manager._config_dir is None:
        create_config()
    return manager.get_config()


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
    # 环境变量加载后也需要重新解析相对路径
    manager._resolve_relative_paths()
    return manager.get_config()
