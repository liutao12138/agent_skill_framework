#!/usr/bin/env python3
"""Agent Framework SubAgent - 子Agent系统 (异步版)"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

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


class SubAgent:
    """子Agent (异步)"""

    def __init__(self, config: SubAgentConfig, model_client: ModelClient, tool_registry: ToolRegistry = None, 
                 parent_events: EventEmitter = None, workspace_path: str = "./workspace"):
        self.config = config
        self.model_client = model_client
        self.tool_registry = tool_registry or get_tool_registry()
        self.events = parent_events or get_event_emitter()
        self.workspace_path = Path(workspace_path)
        self.messages: List[Dict[str, Any]] = []
        self.stats = {"iterations": 0, "tool_calls": 0, "start_time": None, "end_time": None}
        self._last_request_time = 0  # 用于请求限流

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

    async def execute(self, task: str, context: List[Dict[str, Any]] = None, stream: bool = False, session_id: str = None) -> Dict[str, Any]:
        """异步执行

        Args:
            task: 任务描述
            context: 上下文消息
            stream: 是否流式输出
            session_id: 会话ID
        """
        start_time = time.time()
        self.stats = {"iterations": 0, "tool_calls": 0, "start_time": start_time, "end_time": None}

        # 设置 session_id
        if session_id:
            self.events.set_session_id(session_id)

        # 注意：SUBAGENT_START/STOP 事件由调用方（如主Agent）触发，避免重复
        self.messages = [{"role": "system", "content": self._build_system_prompt()}]
        if context:
            self.messages.extend(context)
        self.messages.append({"role": "user", "content": task})

        result = {"success": False, "summary": "", "tool_calls": 0, "duration": 0, "error": None}

        try:
            from .config import get_config
            config = get_config()
            max_messages = getattr(config.model, 'max_messages', 50)
            rate_limit_delay = getattr(config.model, 'rate_limit_delay', 0.5)
            
            for iteration in range(self.config.max_iterations):
                self.stats["iterations"] = iteration + 1
                
                # 请求限流
                now = time.time()
                elapsed = now - self._last_request_time
                if elapsed < rate_limit_delay:
                    time.sleep(rate_limit_delay - elapsed)
                self._last_request_time = time.time()
                
                # 滑动窗口：裁剪消息历史
                if len(self.messages) > max_messages:
                    system_msg = self.messages[0] if self.messages[0].get("role") == "system" else None
                    recent = self.messages[-max_messages:]
                    self.messages = [system_msg] + recent if system_msg else recent
                
                response = await self._call_model(stream)

                if stream:
                    content = ""
                    async for chunk in response:
                        content += chunk
                elif response:
                    if response.stop_reason == StopReason.STOP:
                        result["summary"] = content or response.content
                        result["success"] = True
                        break
                    elif response.stop_reason == StopReason.TOOL_USE:
                        content = response.content
                        tool_results = await self._execute_tools(response.tool_calls)
                        self.messages.append({"role": "assistant", "content": content})
                        for r in tool_results:
                            self.messages.append({
                                "role": "tool",
                                "content": r["output"],
                                "tool_call_id": r["tool_use_id"]
                            })

                if time.time() - start_time > self.config.timeout:
                    result["error"] = "Timeout"
                    break

            if not result["success"] and not result["error"]:
                result["error"] = "Max iterations reached"

        except Exception as e:
            result["error"] = str(e)
            # SUBAGENT_ERROR 事件由调用方触发，避免重复

        finally:
            self.stats["end_time"] = time.time()
            result["duration"] = self.stats["end_time"] - start_time
            result["tool_calls"] = self.stats["tool_calls"]
            # SUBAGENT_STOP 事件由调用方（如主Agent）触发，避免重复

        return result

    def _build_system_prompt(self) -> str:
        parts = [self.config.system_prompt or f"You are {self.config.name} agent.", f"Working directory: {self.workspace_path}"]
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
        return [self.tool_registry._to_format(tool.get_definition()) for tool in self.tool_registry.get_all() if tool.name in allowed]

    async def _call_model(self, stream: bool = False) -> any:
        messages = [msg if isinstance(msg, dict) else {"role": "user", "content": str(msg)} for msg in self.messages]
        tools = self._get_tool_definitions()
        self.events.emit(EventType.MODEL_START, {"agent": self.config.name})
        response = await self.model_client.chat(messages=messages, tools=tools if tools else None, stream=stream)
        self.events.emit(EventType.MODEL_STOP, {"agent": self.config.name})
        return response

    async def _execute_tools(self, tool_calls: List) -> List[Dict[str, Any]]:
        results = []
        for tool_call in tool_calls:
            func = tool_call.function if hasattr(tool_call, 'function') else tool_call
            tool_name = func.get("name", "") if isinstance(func, dict) else func.name
            args_str = func.get("arguments", "") if isinstance(func, dict) else func.arguments
            try:
                args = json.loads(args_str) if args_str else {}
            except:
                args = {"raw": str(args_str)}

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
            tool_id = tool_call.id if hasattr(tool_call, 'id') else tool_call.get("id", "")
            results.append({"tool_use_id": tool_id, "tool_name": tool_name, "output": output, "success": success})

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
        definitions = []
        for config in self._configs.values():
            subagent = SubAgent(config=config, model_client=self.model_client, 
                              tool_registry=self.tool_registry, parent_events=self.events,
                              workspace_path=self.workspace_path)
            definitions.append(subagent.get_tool_definition())
        return definitions

    def create_subagent(self, name: str, description: str = None, system_prompt: str = "", 
                       allowed_tools: List[str] = None, max_iterations: int = None, timeout: int = None) -> SubAgent:
        """创建子Agent"""
        config = SubAgentConfig(
            name=name,
            description=description or f"{name} agent",
            system_prompt=system_prompt,
            allowed_tools=allowed_tools or [],
            max_iterations=max_iterations or 50,
            timeout=timeout or 300,
        )
        return SubAgent(config=config, model_client=self.model_client, tool_registry=self.tool_registry, 
                       parent_events=self.events, workspace_path=self.workspace_path)

    async def execute_task_async(self, task: str, agent_name: str = None, context: List[Dict[str, Any]] = None, stream: bool = False, session_id: str = None):
        """异步执行

        Args:
            task: 任务描述
            agent_name: Agent名称
            context: 上下文消息
            stream: 是否流式输出
            session_id: 会话ID
        """
        if agent_name and agent_name in self._configs:
            subagent = self.create_subagent(**self._configs[agent_name].__dict__)
        else:
            subagent = self.create_subagent(name="default", description="Default subagent")
        return await subagent.execute(task, context, stream, session_id=session_id)

    def get_config(self, name: str) -> Optional[SubAgentConfig]:
        return self._configs.get(name)
