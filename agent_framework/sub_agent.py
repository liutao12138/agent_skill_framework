#!/usr/bin/env python3
"""Agent Framework SubAgent - 子Agent系统"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from .model_client import ModelClient, ModelResponse, StopReason
from .tools import ToolRegistry, get_tool_registry, execute_tool
from .events import EventEmitter, EventType, get_event_emitter


class AgentType(Enum):
    """Agent类型"""
    EXPLORE = "explore"
    CODE = "code"
    PLAN = "plan"
    CUSTOM = "custom"


@dataclass
class SubAgentConfig:
    """子Agent配置"""
    name: str
    description: str
    agent_type: AgentType
    system_prompt: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    max_iterations: int = 50
    timeout: int = 300


class SubAgent:
    """子Agent"""

    DEFAULT_CONFIGS = {
        AgentType.EXPLORE: SubAgentConfig(
            name="explore", description="Read-only agent for exploring code", agent_type=AgentType.EXPLORE,
            system_prompt="You are an exploration agent. Search and analyze, but never modify files.",
            allowed_tools=["bash", "read_file", "list_dir", "grep"], max_iterations=30,
        ),
        AgentType.CODE: SubAgentConfig(
            name="code", description="Full agent for implementing features", agent_type=AgentType.CODE,
            system_prompt="You are a coding agent. Implement the requested changes efficiently.",
            allowed_tools=["*"], max_iterations=100,
        ),
        AgentType.PLAN: SubAgentConfig(
            name="plan", description="Planning agent for designing strategies", agent_type=AgentType.PLAN,
            system_prompt="You are a planning agent. Analyze and output a numbered implementation plan.",
            allowed_tools=["bash", "read_file", "list_dir", "grep"], max_iterations=20,
        ),
    }

    def __init__(self, config: SubAgentConfig, model_client: ModelClient, tool_registry: ToolRegistry = None, parent_events: EventEmitter = None, workspace_path: str = "./workspace"):
        self.config = config
        self.model_client = model_client
        self.tool_registry = tool_registry or get_tool_registry()
        self.events = parent_events or get_event_emitter()
        self.workspace_path = Path(workspace_path)
        self.messages: List[Dict[str, Any]] = []
        self.stats = {"iterations": 0, "tool_calls": 0, "start_time": None, "end_time": None}

    def execute(self, task: str, context: List[Dict[str, Any]] = None, stream: bool = False) -> Dict[str, Any]:
        start_time = time.time()
        self.stats = {"iterations": 0, "tool_calls": 0, "start_time": start_time, "end_time": None}

        self.events.emit_subagent_start(self.config.name, task)
        self.messages = [{"role": "system", "content": self._build_system_prompt()}]
        if context:
            self.messages.extend(context)
        self.messages.append({"role": "user", "content": task})

        result = {"success": False, "summary": "", "tool_calls": 0, "duration": 0, "error": None}

        try:
            for iteration in range(self.config.max_iterations):
                self.stats["iterations"] = iteration + 1
                response = self._call_model(stream)

                if stream:
                    for _ in response:
                        pass
                elif response:
                    if response.stop_reason == StopReason.STOP:
                        result["summary"] = response.content
                        result["success"] = True
                        break
                    elif response.stop_reason == StopReason.TOOL_USE:
                        tool_results = self._execute_tools(response.tool_calls)
                        self.messages.append({"role": "assistant", "content": response.content})
                        self.messages.append({"role": "user", "content": [{"type": "tool_result", "content": tool_results}]})

                if time.time() - start_time > self.config.timeout:
                    result["error"] = "Timeout"
                    break

            if not result["success"] and not result["error"]:
                result["error"] = "Max iterations reached"

        except Exception as e:
            result["error"] = str(e)
            self.events.emit(EventType.SUBAGENT_ERROR, {"name": self.config.name, "error": str(e)})

        finally:
            self.stats["end_time"] = time.time()
            result["duration"] = self.stats["end_time"] - start_time
            result["tool_calls"] = self.stats["tool_calls"]
            self.events.emit_subagent_stop(self.config.name, result["duration"])

        return result

    def _build_system_prompt(self) -> str:
        parts = [self.config.system_prompt or f"You are a {self.config.name} agent.", f"Working directory: {self.workspace_path}"]
        tools = self._get_allowed_tools()
        if tools:
            tool_descriptions = [f"- {t.name}: {t.description}" for t in self.tool_registry.get_all() if t.name in tools]
            if tool_descriptions:
                parts.append("\nAvailable tools:\n" + "\n".join(tool_descriptions))
        return "\n".join(parts)

    def _get_allowed_tools(self) -> List[str]:
        return list(self.tool_registry._tools.keys()) if "*" in self.config.allowed_tools else self.config.allowed_tools

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        allowed = self._get_allowed_tools()
        return [tool.get_definition().to_openai_format() for tool in self.tool_registry.get_all() if tool.name in allowed]

    def _call_model(self, stream: bool = False) -> any:
        messages = [msg if isinstance(msg, dict) else {"role": "user", "content": str(msg)} for msg in self.messages]
        tools = self._get_tool_definitions()
        return self.model_client.chat(messages=messages, tools=tools if tools else None, stream=stream)

    def _execute_tools(self, tool_calls: List) -> List[Dict[str, Any]]:
        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
            except:
                args = {"raw": str(tool_call.function.arguments)}

            start_time = time.time()
            self.events.emit_tool_call(tool_name, args)
            try:
                output = execute_tool(tool_name, **args)
                success = not output.startswith("Error:")
            except Exception as e:
                output = f"Error: {e}"
                success = False

            duration = time.time() - start_time
            self.stats["tool_calls"] += 1
            self.events.emit_tool_result(tool_name, output, success, duration)
            results.append({"tool_use_id": tool_call.id, "tool_name": tool_name, "output": output, "success": success})

        return results


class SubAgentManager:
    """子Agent管理器"""

    def __init__(self, model_client: ModelClient, tool_registry: ToolRegistry = None, events: EventEmitter = None, workspace_path: str = "./workspace"):
        self.model_client = model_client
        self.tool_registry = tool_registry or get_tool_registry()
        self.events = events or get_event_emitter()
        self.workspace_path = workspace_path
        self._custom_configs: Dict[str, SubAgentConfig] = {}

    def create_subagent(self, name: str, description: str = None, agent_type: AgentType = AgentType.CODE, system_prompt: str = "", allowed_tools: List[str] = None, max_iterations: int = None, timeout: int = None) -> SubAgent:
        default = SubAgent.DEFAULT_CONFIGS.get(agent_type)
        config = SubAgentConfig(
            name=name or (default.name if default else "custom"),
            description=description or (default.description if default else ""),
            agent_type=agent_type,
            system_prompt=system_prompt or (default.system_prompt if default else ""),
            allowed_tools=allowed_tools or (default.allowed_tools if default else []),
            max_iterations=max_iterations or (default.max_iterations if default else 50),
            timeout=timeout or (default.timeout if default else 300),
        )
        return SubAgent(config=config, model_client=self.model_client, tool_registry=self.tool_registry, parent_events=self.events, workspace_path=self.workspace_path)

    def execute_task(self, task: str, agent_type: AgentType = AgentType.CODE, context: List[Dict[str, Any]] = None, stream: bool = False, **config_overrides) -> Dict[str, Any]:
        subagent = self.create_subagent(agent_type=agent_type, **config_overrides)
        return subagent.execute(task, context, stream)

    def register_config(self, config: SubAgentConfig):
        self._custom_configs[config.name] = config

    def get_config(self, name: str) -> Optional[SubAgentConfig]:
        return self._custom_configs.get(name)
