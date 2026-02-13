#!/usr/bin/env python3
"""Agent Framework - 主 Agent 类 (异步版)"""

import time
import uuid
from typing import Any, Dict, List

from .base import BaseAgent
from .config import get_config, create_config, FrameworkConfig
from .events import EventEmitter, EventType
from .logger import get_logger
from .model_client import ModelClient, create_client
from .skill_loader import SkillLoader, get_skills_loader
from .sub_agent import SubAgentManager
from .tools import execute_tool, get_tool_definitions, get_tool_registry, MemoryStore, FinalAnswerException

logger = get_logger()

# 常量定义
DEFAULT_TIMEOUT_MULTIPLIER = 10


class Agent(BaseAgent):
    """主 Agent 类 (异步版)"""

    def __init__(self, config: FrameworkConfig = None, model_client: ModelClient = None,
                 tool_registry=None, skills_loader: SkillLoader = None, events: EventEmitter = None,
                 allowed_tools: List[str] = None):
        self.config = config or get_config()
        # 先调用BaseAgent初始化（设置workspace_path等）
        super().__init__(self.config.workspace.root_path)
        self.model_client = model_client or create_client()
        self.tool_registry = tool_registry or get_tool_registry()
        self.events = events or EventEmitter()
        self.allowed_tools = allowed_tools
        self.skills_loader = skills_loader or get_skills_loader(self.workspace_path)
        self.subagent_manager = SubAgentManager(
            model_client=self.model_client, tool_registry=self.tool_registry,
            events=self.events, workspace_path=self.workspace_path)
        self.logger = get_logger()
        self._memory_store = MemoryStore()
        self._init_skills()

    def _init_skills(self):
        try:
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
        """构建主Agent系统提示词"""
        skills_desc = self.skills_loader.get_descriptions()
        tools_desc = "\n".join(f"- {t.name}: {t.description}" for t in self.tool_registry.get_all())
        return self._build_system_prompt_base(
            name=self.config.agent.name,
            description=self.config.agent.description,
            skills_desc=skills_desc,
            tools_desc=tools_desc
        )

    async def chat(self, message: str, system_prompt: str = None, stream: bool = None,
                   context: List[Dict[str, Any]] = None, session_id: str = None) -> Dict[str, Any]:
        """异步聊天接口"""
        stream = stream if stream is not None else self.config.agent.enable_streaming
        prompt = system_prompt or self._build_system_prompt()
        self._message_history = [{"role": "system", "content": prompt}, {"role": "user", "content": message}]
        messages = context + self._message_history if context else self._message_history.copy()

        session_id = session_id or str(uuid.uuid4())
        self.events.set_session_id(session_id)

        logger.info(f"[AGENT] Chat started, stream={stream}, session_id={session_id}")
        self.events.emit(EventType.USER_MESSAGE, {"message": message, "session_id": session_id})

        tools = get_tool_definitions(allowed_tools=self.allowed_tools)
        if self.config.enable_sub_agents:
            tools = tools + self.subagent_manager.get_subagent_definitions()

        result = await self._run_agent_loop(messages=messages, tools=tools, stream=stream, session_id=session_id)
        self._message_history = messages
        return result

    async def _run_agent_loop(self, messages: List[Dict], tools: List[Dict], stream: bool, session_id: str) -> Dict[str, Any]:
        """Agent 主循环"""
        result = {"success": False, "content": "", "tool_calls": [], "duration": 0, "session_id": session_id}
        start_time, iterations = time.time(), 0
        max_timeout = self.config.agent.max_iterations * DEFAULT_TIMEOUT_MULTIPLIER

        while iterations < self.config.agent.max_iterations:
            iterations += 1
            self._apply_rate_limit(self.config.model.rate_limit_delay)
            self.events.emit(EventType.MODEL_START, {"iteration": iterations, "session_id": session_id})
            messages = self._prune_messages(messages, self.config.model.max_messages)

            response = await self.model_client.chat(messages=messages, tools=tools or None, stream=stream)
            content, tool_calls = await self._collect_response(response, stream)
            # 将 ToolCall 对象转换为字典格式，以便 JSON 序列化
            tool_calls_dict = []
            for tc in tool_calls:
                if hasattr(tc, '__dict__'):
                    tool_calls_dict.append(tc.__dict__)
                elif isinstance(tc, dict):
                    tool_calls_dict.append(tc)
                else:
                    tool_calls_dict.append({"id": str(tc.id) if hasattr(tc, 'id') else "", "type": "function", "function": {}})
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls_dict})
            result["content"] = content

            if tool_calls:
                has_final_answer = await self._process_tool_calls(tool_calls, messages, result, start_time, session_id, max_timeout)
                if has_final_answer:
                    # 工具返回了最终答案，终止 agent
                    break
                continue

            if self._should_stop(response, stream, tool_calls):
                result["success"] = True
                break

            if time.time() - start_time > max_timeout:
                break

        result["duration"] = time.time() - start_time
        result["iterations"] = iterations
        logger.info(f"[AGENT] Chat completed, success={result['success']}, duration={result['duration']:.2f}s")
        return result

    async def _process_tool_calls(self, tool_calls: List, messages: List[Dict], result: Dict,
                                   start_time: float, session_id: str, max_timeout: float) -> bool:
        """处理工具调用（包括子Agent和普通工具）

        Returns:
            bool: 如果有最终答案（FinalAnswerException），返回 True；否则返回 False
        """
        parsed_calls = [self._parse_tool_call(tc) for tc in tool_calls]

        subagent_calls = [tc for tc in parsed_calls if self._is_subagent_call(tc)]
        tool_calls_only = [tc for tc in parsed_calls if not self._is_subagent_call(tc)]

        # 处理子Agent调用
        if subagent_calls:
            for tc in subagent_calls:
                subagent_result = await self._execute_subagent(tc, session_id)
                result.setdefault("subagent_results", []).append(subagent_result)
                summary = subagent_result.get("result", {}).get("summary", "")
                messages.append({
                    "role": "tool",
                    "content": f"[{subagent_result['subagent_name']}] {summary}",
                    "tool_call_id": subagent_result["tool_use_id"]
                })

        # 处理普通工具调用
        if tool_calls_only:
            tool_results = await self._execute_tools(tool_calls_only, session_id)
            result["tool_calls"].extend(r["tool_name"] for r in tool_results)
            messages.extend([
                {"role": "tool", "content": r["output"], "tool_call_id": r["tool_use_id"]}
                for r in tool_results
            ])
            # 检查是否有最终答案
            for r in tool_results:
                if "final_answer" in r:
                    result["success"] = True
                    result["content"] = r["final_answer"]
                    result["final_answer"] = True
                    return True

        if time.time() - start_time > max_timeout:
            return False

        return False

    async def _execute_subagent(self, tool_call: Dict, session_id: str) -> Dict[str, Any]:
        """执行子Agent调用"""
        args = self._parse_tool_args(tool_call["arguments"])
        subagent_name = tool_call["name"].replace("subagent_", "")
        task = args.get("task", "")
        context = args.get("context", [])

        logger.info(f"[SUBAGENT] Executing: {subagent_name}, task={task[:50]}..., session_id={session_id}")
        self.events.emit(EventType.SUBAGENT_START, {"name": subagent_name, "task": task, "session_id": session_id})

        config = self.subagent_manager.get_config(subagent_name)
        if config:
            result = await self.subagent_manager.execute_task_async(
                task=task, agent_name=subagent_name, context=context, session_id=session_id)
        else:
            result = {"success": False, "error": f"Unknown subagent: {subagent_name}"}

        self.events.emit(EventType.SUBAGENT_STOP, {
            "name": subagent_name,
            "duration": result.get("duration", 0),
            "session_id": session_id
        })
        return {"tool_use_id": tool_call["id"], "subagent_name": subagent_name, "result": result}

    async def _execute_tools(self, tool_calls: List[Dict], session_id: str) -> List[Dict[str, Any]]:
        """执行工具调用

        Returns:
            List[Dict[str, Any]]: 工具执行结果列表，如果某个工具抛出 FinalAnswerException，
            会在该结果的 'final_answer' 字段中携带答案
        """
        results = []
        final_answer = None  # 存储最终答案

        for tool_call in tool_calls:
            args = self._parse_tool_args(tool_call["arguments"])
            resolved_args = self._resolve_placeholders(args, self._memory_store)
            resolved_args["_memory_store"] = self._memory_store

            tool_name = tool_call["name"]
            logger.info(f"[TOOL] Calling: {tool_name}, session_id={session_id}")
            self.events.emit(EventType.TOOL_CALL_START, {"tool_name": tool_name, "input": resolved_args, "session_id": session_id, "call_id": tool_call.get("id")})

            start_time = time.time()
            try:
                output = execute_tool(tool_name, **resolved_args)
                success = not output.startswith("Error:")
            except FinalAnswerException as e:
                # 捕获 FinalAnswerException，记录最终答案并继续执行
                final_answer = e.message
                output = str(e.message)
                success = True
                logger.info(f"[TOOL] FinalAnswerException caught from {tool_name}: {output}")
            except Exception as e:
                output, success = f"Error: {e}", False

            duration = time.time() - start_time
            logger.info(f"[TOOL] Done: {tool_name}, success={success}, duration={duration:.2f}s, session_id={session_id}")
            self.events.emit(EventType.TOOL_RESULT, {
                "tool_name": tool_name, "output": output, "success": success,
                "duration": duration, "session_id": session_id, "call_id": tool_call.get("id")
            })

            result_record = {
                "tool_use_id": tool_call["id"],
                "tool_name": tool_name,
                "output": output,
                "success": success,
                "duration": duration,
                "session_id": session_id
            }
            # 如果有最终答案，添加到结果中
            if final_answer is not None:
                result_record["final_answer"] = final_answer

            self._tool_results.append(result_record)
            results.append(result_record)

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
    """创建 Agent 实例"""
    config = config or create_config(config_path)
    return Agent(config=config, allowed_tools=allow_tools)


async def run_chat(message: str, config_path: str = None) -> Dict[str, Any]:
    return await create_agent(config_path=config_path).chat(message)
