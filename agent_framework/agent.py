#!/usr/bin/env python3
"""Agent Framework - 主 Agent 类"""

import json
import time
from typing import Any, Dict, List, Optional

from .config import get_config, create_config, FrameworkConfig
from .logger import get_logger
from .model_client import ModelClient, create_client
from .events import EventType
from .tools import get_tool_registry, execute_tool, get_tool_definitions
from .skill_loader import SkillLoader, get_skills_loader, scan_skills
from .sub_agent import SubAgentManager, SubAgent, AgentType
from .events import EventEmitter, get_event_emitter


class Agent:
    """主 Agent 类"""

    def __init__(self, config: FrameworkConfig = None, model_client: ModelClient = None,
                 tool_registry=None, skills_loader: SkillLoader = None, events: EventEmitter = None):
        self.config = config or get_config()
        self.model_client = model_client or create_client()
        self.tool_registry = tool_registry or get_tool_registry()
        self.skills_loader = skills_loader or get_skills_loader()
        self.events = events or get_event_emitter()
        self.subagent_manager = SubAgentManager(
            model_client=self.model_client, tool_registry=self.tool_registry,
            events=self.events, workspace_path=self.config.workspace.root_path)
        self.logger = get_logger()
        self._message_history: List[Dict[str, Any]] = []
        self._init_skills()

    def _init_skills(self):
        try:
            skills = scan_skills()
            if skills:
                self.logger.info(f"Loaded {len(skills)} skills: {', '.join(skills)}")
        except Exception as e:
            self.logger.warning(f"Failed to load skills: {e}")

    def _build_system_prompt(self) -> str:
        parts = [f"You are {self.config.agent.name}, {self.config.agent.description}",
                 f"Working directory: {self.config.workspace.root_path}"]
        skills_desc = self.skills_loader.get_descriptions()
        if skills_desc:
            parts.append(f"\n**Skills:**\n{skills_desc}")
        if self.config.enable_sub_agents:
            agents_desc = "\n".join(f"- {c.name}: {c.description}" for c in SubAgent.DEFAULT_CONFIGS.values())
            if agents_desc:
                parts.append(f"\n**Subagents:**\n{agents_desc}")
        parts.extend(["\nRules:", "- Use tools immediately when task matches", "- Prefer tools over prose"])
        return "\n".join(parts)

    def chat(self, message: str, system_prompt: str = None, stream: bool = None,
             context: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        stream = stream if stream is not None else self.config.agent.enable_streaming
        prompt = system_prompt or self._build_system_prompt()
        self._message_history = [{"role": "system", "content": prompt}]
        self._message_history.append({"role": "user", "content": message})
        messages = self._message_history.copy()
        if context:
            messages = context + messages
        tools = get_tool_definitions()
        result = self._run_agent_loop(messages=messages, tools=tools, stream=stream)
        self._message_history = messages
        return result

    def _run_agent_loop(self, messages: List[Dict], tools: List[Dict], stream: bool = False) -> Dict[str, Any]:
        result = {"success": False, "content": "", "tool_calls": [], "duration": 0}
        start_time, iterations = time.time(), 0

        while iterations < self.config.agent.max_iterations:
            iterations += 1
            response = self.model_client.chat(messages=messages, tools=tools if tools else None, stream=stream)

            # 收集响应内容
            if stream:
                for _ in response:
                    pass
            content = response.content
            tool_calls = response.tool_calls or []

            messages.append({"role": "assistant", "content": content})
            result["content"] = content

            # 处理工具调用
            if tool_calls:
                tool_results = self._execute_tools(tool_calls)
                result["tool_calls"].extend(r["tool_name"] for r in tool_results)
                messages.extend([{"role": "tool", "content": r["output"], "tool_call_id": r["tool_use_id"]} for r in tool_results])
                if time.time() - start_time > self.config.agent.max_iterations * 10:
                    break
                continue

            # 无工具调用，检查是否停止
            if not stream and response.stop_reason.value == "stop":
                result["success"] = True
                break

            if stream or response.stop_reason.value == "stop":
                result["success"] = True
                break

            if time.time() - start_time > self.config.agent.max_iterations * 10:
                break

        result["duration"] = time.time() - start_time
        result["iterations"] = iterations
        return result

    def _execute_tools(self, tool_calls: List) -> List[Dict[str, Any]]:
        """执行工具调用，统一处理 ToolCall 对象和字典格式"""
        results = []
        for tc in tool_calls:
            # 统一获取函数名和参数
            if hasattr(tc, 'function'):  # ToolCall 对象
                func = tc.function
                tool_name = func.get("name", "") if isinstance(func, dict) else func.name
                args_str = func.get("arguments", "") if isinstance(func, dict) else func.arguments
                tool_id = tc.id
            else:  # 字典格式
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                args_str = func.get("arguments", "")
                tool_id = tc.get("id", "")

            args = json.loads(args_str) if args_str else {}
            self.events.emit(EventType.TOOL_CALL_START, {"tool_name": tool_name, "input": args})

            start_time = time.time()
            try:
                output = execute_tool(tool_name, **args)
                success = not output.startswith("Error:")
            except Exception as e:
                output, success = f"Error: {e}", False

            duration = time.time() - start_time
            self.events.emit(EventType.TOOL_RESULT, {"tool_name": tool_name, "output": output, "success": success, "duration": duration})
            results.append({"tool_use_id": tool_id, "tool_name": tool_name, "output": output, "success": success, "duration": duration})
        return results

    def run_skill(self, skill_name: str) -> str:
        content = self.skills_loader.get_skill_content(skill_name)
        if content:
            self.events.emit(EventType.SKILL_LOADED, {"skill_name": skill_name})
        return content

    def run_subagent(self, task: str, agent_type: AgentType = AgentType.CODE, context: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.subagent_manager.execute_task(task=task, agent_type=agent_type, context=context)

    def execute_tool(self, name: str, **kwargs) -> str:
        return execute_tool(name, **kwargs)

    def list_skills(self) -> List[str]:
        return self.skills_loader.list_skills()

    def list_tools(self) -> List[Dict[str, Any]]:
        return self.tool_registry.list_tools()

    def get_message_history(self) -> List[Dict[str, Any]]:
        return self._message_history.copy()

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "skills": self.skills_loader.get_statistics(),
            "tools": {"count": len(self.tool_registry.get_all()), "tools": self.tool_registry.list_tools()},
            "message_count": len(self._message_history),
        }


def create_agent(config: FrameworkConfig = None, config_path: str = None) -> Agent:
    config = config or create_config(config_path)
    return Agent(config=config)


def run_chat(message: str, config_path: str = None) -> Dict[str, Any]:
    return create_agent(config_path=config_path).chat(message)
