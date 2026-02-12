#!/usr/bin/env python3
"""Agent Framework SubAgent - 子Agent系统 (异步版)"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from .base import BaseAgent
from .model_client import ModelClient, StopReason
from .tools import ToolRegistry, get_tool_registry, execute_tool
from .events import EventEmitter, EventType, get_event_emitter


@dataclass
class SubAgentConfig:
    """子Agent配置"""
    name: str
    description: str
    system_prompt: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    max_iterations: int = 50
    timeout: int = 300
    # 自定义系统提示词能力章节: List[Tuple[str, List[str]]]
    # 例: [("Custom Section", ["- item1", "- item2"])]
    capability_sections: List[tuple] = field(default_factory=list)


class SubAgent(BaseAgent):
    """子Agent (异步)，继承自BaseAgent复用通用功能"""

    def __init__(self, config: SubAgentConfig, model_client: ModelClient, tool_registry: ToolRegistry = None,
                 parent_events: EventEmitter = None, workspace_path: str = "./workspace"):
        super().__init__(workspace_path)
        self.config = config
        self.model_client = model_client
        self.tool_registry = tool_registry or get_tool_registry()
        self.events = parent_events or get_event_emitter()
        self.workspace_path = Path(workspace_path)
        self.messages: List[Dict[str, Any]] = []
        self.stats = {"iterations": 0, "tool_calls": 0, "start_time": None, "end_time": None}

    def get_tool_definition(self) -> Dict[str, Any]:
        """获取子Agent的工具定义"""
        return {
            "type": "function",
            "function": {
                "name": f"subagent_{self.config.name}",
                "description": self.config.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The task to delegate to this sub-agent"
                        },
                        "context": {
                            "type": "array",
                            "description": "Optional context messages",
                            "items": {"type": "object"}
                        }
                    },
                    "required": ["task"]
                }
            }
        }

    def _build_system_prompt(self) -> str:
        """构建子Agent系统提示"""
        # 支持通过 config 自定义能力章节
        custom_sections = getattr(self.config, 'capability_sections', None)
        tools_desc = self._get_tools_description()
        return self._build_system_prompt_base(
            name=self.config.name,
            description=self.config.description,
            tools_desc=tools_desc,
            custom_sections=custom_sections
        )

    def _get_tools_description(self) -> str:
        """获取工具描述"""
        tools = self._get_allowed_tools()
        if not tools:
            return ""
        return "\n".join(
            f"- {t.name}: {t.description}"
            for t in self.tool_registry.get_all()
            if t.name in tools
        )

    def _get_allowed_tools(self) -> List[str]:
        """获取允许的工具列表"""
        return list(self.tool_registry._tools.keys()) if "*" in self.config.allowed_tools else self.config.allowed_tools

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取工具定义列表"""
        allowed = self._get_allowed_tools()
        return [self.tool_registry._to_format(tool.get_definition()) for tool in self.tool_registry.get_all() if tool.name in allowed]

    async def _call_model(self, stream: bool = False) -> any:
        """调用模型"""
        messages = [msg if isinstance(msg, dict) else {"role": "user", "content": str(msg)} for msg in self.messages]
        tools = self._get_tool_definitions()
        self.events.emit(EventType.MODEL_START, {"agent": self.config.name})
        response = await self.model_client.chat(messages=messages, tools=tools if tools else None, stream=stream)
        self.events.emit(EventType.MODEL_STOP, {"agent": self.config.name})
        return response

    async def execute(self, task: str, context: List[Dict[str, Any]] = None, stream: bool = False, session_id: str = None) -> Dict[str, Any]:
        """异步执行"""
        start_time = time.time()
        self.stats = {"iterations": 0, "tool_calls": 0, "start_time": start_time, "end_time": None}

        if session_id:
            self.events.set_session_id(session_id)

        # SUBAGENT_START/STOP 事件由调用方触发
        self.messages = [{"role": "system", "content": self._build_system_prompt()}]
        if context:
            self.messages.extend(context)
        self.messages.append({"role": "user", "content": task})

        result = {"success": False, "summary": "", "tool_calls": 0, "duration": 0, "error": None}

        try:
            rate_limit_delay = 0.5

            for iteration in range(self.config.max_iterations):
                self.stats["iterations"] = iteration + 1

                self._apply_rate_limit(rate_limit_delay)
                self.messages = self._prune_messages(self.messages, 50)

                response = await self._call_model(stream)

                if stream:
                    content = ""
                    async for chunk in response:
                        content += chunk
                    tool_calls = response.tool_calls or []
                else:
                    content = response.content
                    tool_calls = response.tool_calls or []

                messages_to_append = [{"role": "assistant", "content": content}]
                if tool_calls:
                    messages_to_append[0]["tool_calls"] = self._format_tool_calls(tool_calls)

                if tool_calls:
                    tool_results = await self._execute_subagent_tools(tool_calls)
                    self.messages.extend(messages_to_append)
                    self.messages.extend([
                        {"role": "tool", "content": r["output"], "tool_call_id": r["tool_use_id"]}
                        for r in tool_results
                    ])
                    result["tool_calls"] += len(tool_results)

                if self._should_stop(response, stream, tool_calls):
                    result["summary"] = content
                    result["success"] = True
                    break

                if time.time() - start_time > self.config.timeout:
                    result["error"] = "Timeout"
                    break

            if not result["success"] and not result["error"]:
                result["error"] = "Max iterations reached"

        except Exception as e:
            result["error"] = str(e)

        finally:
            self.stats["end_time"] = time.time()
            result["duration"] = self.stats["end_time"] - start_time
            result["tool_calls"] = self.stats["tool_calls"]

        return result

    async def _execute_subagent_tools(self, tool_calls: List) -> List[Dict[str, Any]]:
        """执行子Agent的工具调用（不处理子Agent调用）"""
        results = []
        for tool_call in tool_calls:
            parsed = self._parse_tool_call(tool_call)
            tool_name = parsed["name"]
            args = self._parse_tool_args(parsed["arguments"])

            start_time = time.time()
            self.events.emit(EventType.TOOL_CALL_START, {"tool_name": tool_name, "input": args})
            try:
                output = execute_tool(tool_name, **args)
                success = not output.startswith("Error:")
            except Exception as e:
                output, success = f"Error: {e}", False

            duration = time.time() - start_time
            self.stats["tool_calls"] += 1
            self.events.emit(EventType.TOOL_RESULT, {"tool_name": tool_name, "output": output, "success": success, "duration": duration})

            result = {
                "tool_use_id": parsed["id"],
                "tool_name": tool_name,
                "output": output,
                "success": success,
                "duration": duration
            }
            self._tool_results.append(result)
            results.append(result)

        return results


class SubAgentManager:
    """子Agent管理器"""

    def __init__(self, model_client: ModelClient, tool_registry: ToolRegistry = None, events: EventEmitter = None, workspace_path: str = "./workspace"):
        self.model_client = model_client
        self.tool_registry = tool_registry or get_tool_registry()
        self.events = events or get_event_emitter()
        self.workspace_path = workspace_path
        self._configs: Dict[str, SubAgentConfig] = {}

    def register(self, config: SubAgentConfig):
        """注册子Agent配置"""
        self._configs[config.name] = config

    def get_subagent_definitions(self) -> List[Dict[str, Any]]:
        """获取所有子Agent的工具定义"""
        return [
            SubAgent(
                config=config, model_client=self.model_client,
                tool_registry=self.tool_registry, parent_events=self.events,
                workspace_path=self.workspace_path
            ).get_tool_definition()
            for config in self._configs.values()
        ]

    def create_subagent(self, name: str, description: str = None, system_prompt: str = "",
                       allowed_tools: List[str] = None, max_iterations: int = None, timeout: int = None,
                       capability_sections: List[tuple] = None) -> SubAgent:
        """创建子Agent

        Args:
            name: Agent名称
            description: Agent描述
            system_prompt: 系统提示词
            allowed_tools: 允许的工具列表
            max_iterations: 最大迭代次数
            timeout: 超时时间（秒）
            capability_sections: 自定义能力章节，格式: [(标题, [行列表]), ...]
                例: [("Custom Section", ["- item1", "- item2"])]
        """
        config = SubAgentConfig(
            name=name,
            description=description or f"{name} agent",
            system_prompt=system_prompt,
            allowed_tools=allowed_tools or [],
            max_iterations=max_iterations or 50,
            timeout=timeout or 300,
            capability_sections=capability_sections or [],
        )
        return SubAgent(config=config, model_client=self.model_client, tool_registry=self.tool_registry,
                       parent_events=self.events, workspace_path=self.workspace_path)

    async def execute_task_async(self, task: str, agent_name: str = None, context: List[Dict[str, Any]] = None,
                                stream: bool = False, session_id: str = None):
        """异步执行"""
        if agent_name and agent_name in self._configs:
            config = self._configs[agent_name]
            subagent = SubAgent(config=config, model_client=self.model_client,
                              tool_registry=self.tool_registry, parent_events=self.events,
                              workspace_path=self.workspace_path)
        else:
            subagent = self.create_subagent(name="default", description="Default subagent")
        return await subagent.execute(task, context, stream, session_id=session_id)

    def get_config(self, name: str) -> Optional[SubAgentConfig]:
        return self._configs.get(name)
