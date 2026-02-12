#!/usr/bin/env python3
"""Agent Framework - AI Agent 框架"""

__version__ = "1.0.0"

from .config import get_config, create_config, FrameworkConfig, ModelConfig, WorkspaceConfig, AgentConfig
from .logger import setup_logging, get_logger
from .model_client import ModelClient, ModelResponse, create_client, OpenAIClient, MindieClient, StopReason
from .tools import ToolRegistry, get_tool_registry, execute_tool, get_tool_definitions, BaseTool
from .skill_loader import SkillLoader, get_skills_loader, scan_skills, Skill, SkillStatus
from .sub_agent import SubAgent, SubAgentManager, SubAgentConfig
from .events import EventEmitter, EventType, Event, ConsoleEventHandler
from .agent import Agent, create_agent, run_chat

__all__ = [
    "__version__", "get_config", "create_config", "FrameworkConfig", "ModelConfig", "WorkspaceConfig", "AgentConfig",
    "setup_logging", "get_logger",
    "ModelClient", "ModelResponse", "create_client", "OpenAIClient", "MindieClient", "StopReason",
    "ToolRegistry", "get_tool_registry", "execute_tool", "get_tool_definitions", "BaseTool",
    "SkillLoader", "get_skills_loader", "scan_skills", "Skill", "SkillStatus",
    "SubAgent", "SubAgentManager", "SubAgentConfig",
    "EventEmitter", "EventType", "Event", "ConsoleEventHandler",
    "Agent", "create_agent", "run_chat",
]
