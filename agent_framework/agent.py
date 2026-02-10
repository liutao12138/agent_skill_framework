#!/usr/bin/env python3
"""Agent Framework - 主 Agent 类 (异步版)"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from .config import get_config, create_config, FrameworkConfig
from .logger import get_logger
from .model_client import ModelClient, create_client, StopReason
from .events import EventType
from .tools import get_tool_registry, execute_tool, get_tool_definitions
from .skill_loader import SkillLoader, get_skills_loader, scan_skills
from .sub_agent import SubAgentManager, SubAgent
from .events import EventEmitter, get_event_emitter

logger = get_logger()


def _resolve_path(path: str) -> str:
    """解析为绝对路径"""
    p = Path(path)
    return str(p.absolute() if not p.is_absolute() else p)


class Agent:
    """主 Agent 类 (异步)"""

    def __init__(self, config: FrameworkConfig = None, model_client: ModelClient = None,
                 tool_registry=None, skills_loader: SkillLoader = None, events: EventEmitter = None,
                 allowed_tools: List[str] = None):
        self.config = config or get_config()
        self.model_client = model_client or create_client()
        self.tool_registry = tool_registry or get_tool_registry()
        self.events = events or get_event_emitter()
        self.allowed_tools = allowed_tools
        self.workspace_path = _resolve_path(self.config.workspace.root_path)
        self.skills_loader = skills_loader or get_skills_loader(_resolve_path(self.config.skills_dir))
        self.subagent_manager = SubAgentManager(
            model_client=self.model_client, tool_registry=self.tool_registry,
            events=self.events, workspace_path=self.workspace_path)
        self.logger = get_logger()
        self._message_history: List[Dict[str, Any]] = []
        self._last_request_time = 0  # 用于请求限流
        self._init_skills()

    def _init_skills(self):
        try:
            # 使用 self.skills_loader 进行扫描，结果会保存在 loader 中
            skills = self.skills_loader.scan()
            if skills:
                self.logger.info(f"[SKILLS] Loaded {len(skills)} skills: {', '.join(skills)}")
                for skill in skills:
                    self.events.emit(EventType.SKILL_LOADED, {"skill_name": skill})
            else:
                self.logger.debug(f"[SKILLS] No skills found in {self.skills_loader.skills_dir}")
        except Exception as e:
            self.logger.warning(f"[SKILLS] Failed to load skills: {e}")

    def _build_system_prompt(self) -> str:
        parts = [f"You are {self.config.agent.name}, {self.config.agent.description}",
                 f"Working directory: {self.workspace_path}"]
        skills_desc = self.skills_loader.get_descriptions()
        if skills_desc:
            parts.append(f"\n**Skills:**\n{skills_desc}")
        parts.extend([
            "\n**Core Capabilities:**",
            "- **Search & Research**: Use search tools (grep, list_dir) to find information before answering",
            "- **Summarize & Synthesize**: Combine multiple search results into a comprehensive answer",
            "- **File Operations**: Read, write, and edit files as needed to complete tasks",
            "- **Shell Commands**: Execute bash commands for system operations when required",
            "",
            "**Response Guidelines:**",
            "- Always search for relevant information first before providing answers",
            "- When multiple sources are available, synthesize them into a coherent response",
            "- If search yields no results, clearly state what was searched and what couldn't be found",
            "- Use tools immediately when a task matches - don't just describe what you would do",
            "- Prefer concrete actions and results over lengthy explanations"
        ])
        return "\n".join(parts)

    def _prune_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """滑动窗口：保留system消息和最近N条消息"""
        max_msgs = self.config.model.max_messages
        if len(messages) <= max_msgs:
            return messages
        
        # 保留system消息（第一条）
        system_msg = messages[0] if messages[0].get("role") == "system" else None
        recent = messages[-max_msgs:]
        
        if system_msg:
            result = [system_msg] + recent
        else:
            result = recent
        
        pruned_count = len(messages) - len(result)
        if pruned_count > 0:
            logger.debug(f"[AGENT] Pruned {pruned_count} old messages, keeping {len(result)}")
        return result

    async def chat(self, message: str, system_prompt: str = None, stream: bool = None,
                   context: List[Dict[str, Any]] = None, session_id: str = None) -> Dict[str, Any]:
        """异步聊天接口

        Args:
            message: 用户消息
            system_prompt: 系统提示（可选）
            stream: 是否使用流式输出
            context: 上下文消息
            session_id: 会话ID，用于追踪和日志标识
        """
        stream = stream if stream is not None else self.config.agent.enable_streaming
        prompt = system_prompt or self._build_system_prompt()
        self._message_history = [{"role": "system", "content": prompt}]
        self._message_history.append({"role": "user", "content": message})
        messages = self._message_history.copy()
        if context:
            messages = context + messages

        # 设置 session_id 用于事件追踪
        if not session_id:
            session_id = str(uuid.uuid4())
        self.events.set_session_id(session_id)

        logger.info(f"[AGENT] Chat started, stream={stream}, session_id={session_id}")
        self.events.emit(EventType.USER_MESSAGE, {"message": message, "session_id": session_id})

        # 获取工具和子Agent定义
        tools = get_tool_definitions(allowed_tools=self.allowed_tools)
        if self.config.enable_sub_agents:
            subagent_defs = self.subagent_manager.get_subagent_definitions()
            tools = tools + subagent_defs

        result = await self._run_agent_loop(messages=messages, tools=tools, stream=stream, session_id=session_id)
        self._message_history = messages
        return result

    async def _run_agent_loop(self, messages: List[Dict], tools: List[Dict], stream: bool = False, session_id: str = None) -> Dict[str, Any]:
        """Agent 主循环

        Args:
            messages: 消息历史
            tools: 可用工具列表
            stream: 是否流式输出
            session_id: 会话ID
        """
        result = {"success": False, "content": "", "tool_calls": [], "duration": 0, "session_id": session_id}
        start_time, iterations = time.time(), 0

        while iterations < self.config.agent.max_iterations:
            iterations += 1
            
            # 请求限流：避免过于频繁的请求
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.config.model.rate_limit_delay:
                time.sleep(self.config.model.rate_limit_delay - elapsed)
            self._last_request_time = time.time()
            
            self.events.emit(EventType.MODEL_START, {"iteration": iterations, "session_id": session_id})

            # 滑动窗口：裁剪消息历史
            messages = self._prune_messages(messages)

            response = await self.model_client.chat(messages=messages, tools=tools if tools else None, stream=stream)

            # 收集响应内容
            if stream:
                content = ""
                async for chunk in response:
                    content += chunk
                    # 发射流式 token 事件
                    self.events.emit_model_stream(chunk)
                # 流结束后获取完整的 tool_calls
                tool_calls = response.tool_calls or []
                # 流结束后才发射 MODEL_STOP
                self.events.emit(EventType.MODEL_STOP, {"iteration": iterations, "session_id": session_id})
            else:
                content = response.content
                tool_calls = response.tool_calls or []
                # 非流式响应在 chat() 返回后发射 MODEL_STOP
                self.events.emit(EventType.MODEL_STOP, {"iteration": iterations, "session_id": session_id})

            messages.append({"role": "assistant", "content": content})
            if tool_calls:
                # 转换 tool_calls 为 dict 格式以便 JSON 序列化
                messages[-1]["tool_calls"] = [
                    {
                        "id": tc.id if hasattr(tc, 'id') else tc.get("id", ""),
                        "type": tc.type if hasattr(tc, 'type') else tc.get("type", ""),
                        "function": {
                            "name": tc.function.get("name", "") if hasattr(tc.function, 'get') else (tc.function.name if hasattr(tc.function, 'name') else ""),
                            "arguments": tc.function.get("arguments", "") if hasattr(tc.function, 'get') else (tc.function.arguments if hasattr(tc.function, 'arguments') else "")
                        }
                    }
                    for tc in tool_calls
                ]
            result["content"] = content

            # 处理工具调用（包括子Agent调用）
            if tool_calls:
                # 分离子Agent调用和普通工具调用
                subagent_calls = [tc for tc in tool_calls if self._is_subagent_call(tc)]
                tool_only_calls = [tc for tc in tool_calls if not self._is_subagent_call(tc)]

                # 处理子Agent调用
                if subagent_calls:
                    for tc in subagent_calls:
                        subagent_result = await self._execute_subagent(tc, session_id=session_id)
                        result["subagent_results"] = result.get("subagent_results", [])
                        result["subagent_results"].append(subagent_result)
                        # 将子Agent结果添加到消息历史
                        summary = subagent_result.get("result", {}).get("summary", "")
                        messages.append({
                            "role": "tool",
                            "content": f"[{subagent_result['subagent_name']}] {summary}",
                            "tool_call_id": subagent_result["tool_use_id"]
                        })

                # 处理普通工具调用
                if tool_only_calls:
                    tool_results = await self._execute_tools(tool_only_calls, session_id=session_id)
                    result["tool_calls"].extend(r["tool_name"] for r in tool_results)
                    messages.extend([{"role": "tool", "content": r["output"], "tool_call_id": r["tool_use_id"]} for r in tool_results])

                if time.time() - start_time > self.config.agent.max_iterations * 10:
                    break
                continue

            # 无工具调用，检查是否停止
            # 流式响应没有stop_reason，stream完成即视为停止
            if not stream and response.stop_reason == StopReason.STOP:
                result["success"] = True
                break
            elif stream and not tool_calls:
                # 流式模式且无工具调用，流完成即成功
                result["success"] = True
                break

            if time.time() - start_time > self.config.agent.max_iterations * 10:
                break

        result["duration"] = time.time() - start_time
        result["iterations"] = iterations
        logger.info(f"[AGENT] Chat completed, success={result['success']}, duration={result['duration']:.2f}s")
        return result

    def _is_subagent_call(self, tool_call) -> bool:
        """检查是否是子Agent调用"""
        if hasattr(tool_call, 'function'):
            func = tool_call.function
            tool_name = func.get("name", "") if isinstance(func, dict) else func.name
        else:
            tool_name = tool_call.get("function", {}).get("name", "")
        return tool_name.startswith("subagent_")

    async def _execute_subagent(self, tool_call, session_id: str = None) -> Dict[str, Any]:
        """执行子Agent调用

        Args:
            tool_call: 工具调用对象
            session_id: 会话ID
        """
        if hasattr(tool_call, 'function'):
            func = tool_call.function
            tool_name = func.get("name", "") if isinstance(func, dict) else func.name
            args_str = func.get("arguments", "") if isinstance(func, dict) else func.arguments
            tool_id = tool_id = tool_call.id
        else:
            func = tool_call.get("function", {})
            tool_name = func.get("name", "")
            args_str = func.get("arguments", "")
            tool_id = tool_call.get("id", "")

        # 解析参数
        try:
            args = json.loads(args_str) if args_str else {}
        except:
            args = {"raw": args_str}

        # 提取子Agent名称和任务
        subagent_name = tool_name.replace("subagent_", "")
        task = args.get("task", "")
        context = args.get("context", [])

        logger.info(f"[SUBAGENT] Executing: {subagent_name}, task={task[:50]}..., session_id={session_id}")
        self.events.emit(EventType.SUBAGENT_START, {"name": subagent_name, "task": task, "session_id": session_id})

        # 查找对应的子Agent配置
        config = self.subagent_manager.get_config(subagent_name)

        if config:
            result = await self.subagent_manager.execute_task_async(task=task, agent_name=subagent_name, context=context, session_id=session_id)
        else:
            result = {"success": False, "error": f"Unknown subagent: {subagent_name}"}

        self.events.emit(EventType.SUBAGENT_STOP, {"name": subagent_name, "duration": result.get("duration", 0), "session_id": session_id})
        return {"tool_use_id": tool_id, "subagent_name": subagent_name, "result": result}

    async def _execute_tools(self, tool_calls: List, session_id: str = None) -> List[Dict[str, Any]]:
        """执行工具调用

        Args:
            tool_calls: 工具调用列表
            session_id: 会话ID
        """
        results = []
        for tc in tool_calls:
            if hasattr(tc, 'function'):
                func = tc.function
                tool_name = func.get("name", "") if isinstance(func, dict) else func.name
                args_str = func.get("arguments", "") if isinstance(func, dict) else func.arguments
                tool_id = tc.id
            else:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                args_str = func.get("arguments", "")
                tool_id = tc.get("id", "")

            args = json.loads(args_str) if args_str else {}
            logger.info(f"[TOOL] Calling: {tool_name}, session_id={session_id}")
            self.events.emit(EventType.TOOL_CALL_START, {"tool_name": tool_name, "input": args, "session_id": session_id})

            start_time = time.time()
            try:
                output = execute_tool(tool_name, **args)
                success = not output.startswith("Error:")
            except Exception as e:
                output, success = f"Error: {e}", False

            duration = time.time() - start_time
            logger.info(f"[TOOL] Done: {tool_name}, success={success}, duration={duration:.2f}s, session_id={session_id}")
            self.events.emit(EventType.TOOL_RESULT, {"tool_name": tool_name, "output": output, "success": success, "duration": duration, "session_id": session_id})
            results.append({"tool_use_id": tool_id, "tool_name": tool_name, "output": output, "success": success, "duration": duration, "session_id": session_id})
        return results

    def run_skill(self, skill_name: str) -> str:
        content = self.skills_loader.get_skill_content(skill_name)
        if content:
            self.events.emit(EventType.SKILL_LOAD, {"skill_name": skill_name})
        return content

    async def run_subagent(self, task: str, agent_name: str = None, context: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.subagent_manager.execute_task_async(task=task, agent_name=agent_name, context=context)

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


def create_agent(config: FrameworkConfig = None, config_path: str = None,
                 allow_tools: List[str] = None) -> Agent:
    """创建 Agent 实例

    Args:
        config: 框架配置对象
        config_path: 配置文件路径
        allow_tools: 允许使用的工具名称列表，None 表示使用所有工具
    """
    config = config or create_config(config_path)
    return Agent(config=config, allowed_tools=allow_tools)


async def run_chat(message: str, config_path: str = None) -> Dict[str, Any]:
    return await create_agent(config_path=config_path).chat(message)
