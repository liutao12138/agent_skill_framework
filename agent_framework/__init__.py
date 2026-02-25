#!/usr/bin/env python3
"""Agent Framework - 基于 LangChain Agent

直接使用 LangChain 的 Agent 能力，简化框架实现
"""

__version__ = "2.0.0"

from .config import get_config, create_config, FrameworkConfig, ModelConfig, WorkspaceConfig, AgentConfig
from .tools import get_all_tools
from .skill_loader import SkillLoader, get_skills_loader, scan_skills, Skill, SkillStatus
from .events import EventEmitter, EventType, Event
from .agent import Agent, create_agent, SubAgent, AgentInterruptedError, get_current_session_id
from .result_cache import ToolResultCache, create_result_cache

# 导出默认能力章节，供用户自定义使用
DEFAULT_CAPABILITIES = Agent.DEFAULT_CAPABILITIES

__all__ = [
    "__version__",
    # Config
    "get_config", "create_config", "FrameworkConfig", "ModelConfig", "WorkspaceConfig", "AgentConfig",
    # Tools
    "get_all_tools",
    # Skills
    "SkillLoader", "get_skills_loader", "scan_skills", "Skill", "SkillStatus",
    # Events
    "EventEmitter", "EventType", "Event",
    # Agent
    "Agent", "create_agent", "SubAgent", "AgentInterruptedError", "get_current_session_id",
    # Result Cache
    "ToolResultCache", "create_result_cache",
    # Default capabilities
    "DEFAULT_CAPABILITIES",
]
