#!/usr/bin/env python3
"""Agent Framework - 基于 LangChain Agent

直接使用 LangChain 的 Agent 能力，简化框架实现
"""

import asyncio
import logging
from contextvars import ContextVar, copy_context
from typing import Any, Callable, Dict, List, Optional

# 全局 session_id 上下文变量
_current_session_id: ContextVar[Optional[str]] = ContextVar('session_id', default=None)

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import Tool
from langchain.agents.factory import create_agent as langchain_create_agent

from .config import get_config, create_config, FrameworkConfig
from .skill_loader import get_skills_loader
from .tools import get_all_tools
from .events import EventEmitter, EventType
from .result_cache import create_result_cache
from .callbacks import StreamCallbackHandler
from .sub_agent import SubAgent, create_sub_agent_tool
from .llm import CustomChatOpenAI

logger = logging.getLogger("agent_framework")


class AgentInterruptedError(Exception):
    """Agent 中断异常"""
    pass


def _wrap_tool_with_cache(tool: Tool, result_cache) -> Tool:
    """包装工具以支持结果缓存引用
    
    Args:
        tool: 原始工具
        result_cache: 结果缓存实例
        
    Returns:
        包装后的工具
    """
    if result_cache is None:
        return tool
        
    # 获取原始工具的 invoke 方法
    original_invoke = tool.invoke
    
    def wrapped_func(input_str: str = None, **kwargs):
        """包装的工具函数，支持引用解析和结果缓存
        
        处理两种调用方式:
        - 单参数: tool("string") -> {"input": "string"}
        - 关键字参数: tool(key1=value1, key2=value2)
        """
        # 构建输入字典
        if input_str is not None:
            # 单参数调用方式，尝试解析为字典
            try:
                input_dict = eval(input_str) if isinstance(input_str, str) else input_str
                if not isinstance(input_dict, dict):
                    input_dict = {"input": input_str}
            except:
                input_dict = {"input": input_str}
        else:
            # 关键字参数调用方式
            input_dict = kwargs
        
        # 解析参数中的引用
        if input_dict:
            for key, value in input_dict.items():
                if isinstance(value, str):
                    resolved = result_cache.resolve_reference(value)
                    if resolved is not None:
                        input_dict[key] = resolved
        
        # 执行原始工具
        raw_result = original_invoke(input_dict)
        
        # 如果有缓存，存储结果并返回引用格式
        if raw_result:
            ref_id = result_cache.put(raw_result, {"tool": tool.name, "args": input_dict})
            result_str = str(raw_result)
            return f"[RESULT:{ref_id}]{result_str}[/RESULT]"
        
        return raw_result
    
    # 返回包装后的工具
    return Tool(
        name=tool.name,
        description=tool.description,
        func=wrapped_func
    )


def get_current_session_id() -> Optional[str]:
    """获取当前会话的 session_id
    
    工具函数可以调用此函数获取当前会话的 session_id
    
    Returns:
        当前 session_id，如果未设置则返回 None
    """
    return _current_session_id.get()


class Agent:
    """基于 LangChain Agent 的框架 Agent"""

    # 默认能力章节
    DEFAULT_CAPABILITIES = [
        ("Core Capabilities", [
            "- Search & Research: Use search tools to find information",
            "- Summarize & Synthesize: Combine multiple results",
            "- File Operations: Read, write, and edit files as needed",
            "- Shell Commands: Execute bash commands when required"
        ]),
        ("Response Guidelines", [
            "- Search first before answering",
            "- Synthesize multiple sources",
            "- Use tools immediately when task matches",
            "- Prefer concrete actions over lengthy explanations"
        ])
    ]

    # 默认引用缓存说明
    DEFAULT_REF_INSTRUCTION = """
**Tool Result Reference (Important!):**
When passing tool results to another tool, use reference format instead of copying full content:
- `$ref_N` - Reference tool result by ID (e.g., `$ref_0`, `$ref_1`)
- `$latest` - Reference the most recent tool result
- Example: `summarize(content=$ref_0)` instead of `summarize(content="<long result here>")`
This saves tokens and avoids truncation when results are long.
"""

    def __init__(
        self,
        config: FrameworkConfig = None,
        workspace_path: str = None,
        allow_tools: List[str] = None,
        system_prompt: str = None,
        custom_capabilities: List[tuple] = None,
        enable_ref_cache: bool = True,
        ref_cache_instruction: str = None,
        events: EventEmitter = None,
        request_transformer: Callable = None,
        response_transformer: Callable = None,
        tools: List = None,
        sub_agents: List["Agent"] = None
    ):
        self.config = config or get_config()
        self.workspace_path = workspace_path or self.config.workspace.root_path
        self.events = events if events is not None else EventEmitter()
        self.skills_loader = get_skills_loader(self.workspace_path)
        self.allow_tools = allow_tools
        self._custom_tools = tools or []  # 自定义工具

        # 子 Agents（将其他 Agent 作为工具调用）
        self._sub_agents = sub_agents or []

        # 自定义请求/响应转换器（用于本地部署模型）
        self._request_transformer = request_transformer
        self._response_transformer = response_transformer

        # 引用缓存 - 用于工具结果传递（每个 Agent 独立实例）
        self.enable_ref_cache = enable_ref_cache
        self.result_cache = create_result_cache() if enable_ref_cache else None
        
        # 自定义引用缓存说明（None 时使用默认说明）
        self._ref_cache_instruction = ref_cache_instruction

        # 自定义系统提示词和能力章节
        self._system_prompt = system_prompt
        self._custom_capabilities = custom_capabilities or []

        # 中断标志
        self._interrupted = False

        # 初始化 LangChain 组件
        self._init_langchain()

        # 加载 Skills
        self._load_skills()

    def interrupt(self):
        """中断 Agent 执行"""
        self._interrupted = True
        logger.info("[AGENT] Agent interrupted")

    def reset_interrupt(self):
        """重置中断状态"""
        self._interrupted = False

    @property
    def is_interrupted(self) -> bool:
        """检查是否被中断"""
        return self._interrupted

    def _check_interrupt(self):
        """检查中断状态，如果被中断则抛出异常"""
        if self._interrupted:
            self._interrupted = False  # 重置状态
            raise AgentInterruptedError("Agent execution was interrupted")

    def _init_langchain(self):
        """初始化 LangChain 组件"""
        mc = self.config.model

        # base_url 直接使用，LangChain 会自动处理路径
        base_url = mc.base_url

        # 构建 LLM 初始化参数
        llm_params = {
            "model": mc.model,
            "api_key": mc.api_key,
            "base_url": base_url,
            "timeout": mc.timeout,
            "max_tokens": mc.max_tokens or 4096,
            "temperature": mc.temperature or 0.7,
            "streaming": self.config.agent.enable_streaming
        }

        # 处理深度思考模型配置
        if mc.enable_thinking:
            # 根据思考级别调整 max_tokens
            if mc.thinking_max_tokens:
                llm_params["max_tokens"] = mc.thinking_max_tokens

            # 深度思考模型通常需要特殊参数
            # 根据不同模型提供商设置对应参数
            thinking_config = self._build_thinking_config(mc)
            llm_params.update(thinking_config)

            logger.info(f"[AGENT] Deep thinking mode enabled: level={mc.thinking_level}")

        # 如果有自定义请求/响应转换器，使用自定义客户端
        if self._request_transformer or self._response_transformer:
            self.llm = self._create_custom_chatopenai(**llm_params)
        else:
            # 创建 ChatOpenAI 实例
            # 如果启用流式，添加回调处理器
            if self.config.agent.enable_streaming:
                llm_params["streaming"] = True
                llm_params["callbacks"] = [StreamCallbackHandler(events=self.events)]
            self.llm = ChatOpenAI(**llm_params)

        # 获取工具列表
        tools = self._get_tools()

        # 构建系统提示词
        system_prompt = self._build_system_prompt()

        # 使用新的 langchain create_agent API
        # 返回的是一个 CompiledStateGraph，可以直接调用 .invoke() 或 .stream()
        self.agent = langchain_create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            debug=False
        )

        # 保存工具引用，用于后续执行
        self._tools = tools
        self._max_iterations = self.config.agent.max_iterations

        logger.info(f"[AGENT] LangChain Agent initialized with {len(tools)} tools")

    def _create_custom_chatopenai(self, **llm_params) -> "CustomChatOpenAI":
        """创建支持自定义请求/响应转换的 ChatOpenAI 实例

        Args:
            **llm_params: ChatOpenAI 初始化参数

        Returns:
            CustomChatOpenAI: 自定义 ChatOpenAI 实例
        """
        return CustomChatOpenAI(
            **llm_params,
            request_transformer=self._request_transformer,
            response_transformer=self._response_transformer
        )

    def _build_thinking_config(self, mc) -> Dict[str, Any]:
        """构建深度思考模型配置

        根据不同模型提供商的 API 格式，构建对应的思考模式参数

        Args:
            mc: ModelConfig 实例

        Returns:
            Dict: 适配特定模型的参数字典
        """
        config = {}

        # 智谱 GLM 深度思考模型
        if "glm" in mc.model.lower():
            # GLM-4 深度思考版本
            if mc.thinking_level == "low":
                config["extra_body"] = {"thinking": {"type": "low"}}
            elif mc.thinking_level == "medium":
                config["extra_body"] = {"thinking": {"type": "medium"}}
            elif mc.thinking_level == "high":
                config["extra_body"] = {"thinking": {"type": "high"}}
            else:
                # 默认启用
                config["extra_body"] = {"thinking": {"type": "medium"}}

        # OpenAI o1 系列 (原生支持深度思考)
        elif "o1" in mc.model.lower() or "o3" in mc.model.lower():
            # 需要设置 reasoning_effort
            config["extra_body"] = {"reasoning_effort": mc.thinking_level}

        # Anthropic Claude 扩展思考
        elif "claude" in mc.model.lower():
            # Claude 3.5+ 支持 extended_thinking
            if mc.thinking_level == "high":
                config["extra_body"] = {"thinking": {"type": "extended", "budget_tokens": mc.thinking_max_tokens or 8192}}

        # 通用的 extra_body 参数（用于其他支持 thinking 的模型）
        elif not config.get("extra_body"):
            config["extra_body"] = {"thinking": {"type": mc.thinking_level}}

        return config

    def _get_tools(self) -> List[Tool]:
        """获取工具列表"""
        # 获取默认工具
        default_tools = get_all_tools()

        # 过滤默认工具
        if self.allow_tools:
            default_tools = [t for t in default_tools if t.name in self.allow_tools]

        # 合并自定义工具
        tools = default_tools + self._custom_tools

        # 添加子 Agent 工具
        for agent in self._sub_agents:
            tools.append(create_sub_agent_tool(agent))

        # 包装工具以支持结果缓存
        if self.result_cache:
            tools = [_wrap_tool_with_cache(t, self.result_cache) for t in tools]

        return tools

    def _build_system_prompt(self) -> str:
        """构建系统提示词字符串

        Args:
            None (使用实例属性 self._system_prompt 和 self._custom_capabilities)

        Returns:
            str: 系统提示词
        """
        # 构建引用传递说明（如果启用）
        ref_instruction = ""
        if self.enable_ref_cache:
            # 使用自定义说明或默认说明
            ref_instruction = self._ref_cache_instruction or self.DEFAULT_REF_INSTRUCTION

        # 如果传入了自定义系统提示词，直接使用并附加引用说明
        if self._system_prompt:
            system_message = self._system_prompt.format(
                name=self.config.agent.name,
                description=self.config.agent.description,
                workspace=self.workspace_path,
                skills=self.skills_loader.get_descriptions(),
                tools="\n".join(f"- {t.name}: {t.description}" for t in get_all_tools())
            )
            # 附加引用说明
            if self.enable_ref_cache:
                system_message += ref_instruction
        else:
            # 构建默认系统提示词
            skills_desc = self.skills_loader.get_descriptions()
            tools_desc = "\n".join(
                f"- {t.name}: {t.description}"
                for t in get_all_tools()
            )

            # 构建能力章节
            capabilities_parts = []
            for title, lines in self._custom_capabilities or self.DEFAULT_CAPABILITIES:
                capabilities_parts.append(f"\n**{title}:**")
                capabilities_parts.extend(lines)

            system_message = f"""You are {self.config.agent.name}, {self.config.agent.description}.
Working directory: {self.workspace_path}

**Skills:**
{skills_desc}

**Available Tools:**
{tools_desc}
{''.join(capabilities_parts)}
{ref_instruction}
"""

        return system_message

    def _load_skills(self):
        """加载 Skills"""
        try:
            skills = self.skills_loader.scan()
            if skills:
                logger.info(f"[SKILLS] Loaded {len(skills)} skills: {', '.join(skills)}")
                self.events.emit(EventType.SKILL_LOADED, {"skills": skills})
        except Exception as e:
            logger.warning(f"[SKILLS] Failed to load skills: {e}")

    async def chat(
        self,
        message: str,
        system_prompt: str = None,
        context: List[Dict[str, Any]] = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """异步聊天接口"""
        # 检查中断状态
        self._check_interrupt()

        # 设置 session_id 到 context variable（供工具获取）
        token = _current_session_id.set(session_id)
        
        try:
            # 设置 session_id 到事件发射器
            if session_id:
                self.events.set_session_id(session_id)

            self.events.emit(EventType.SESSION_START, {"session_id": session_id, "message": message})
            self.events.emit(EventType.USER_MESSAGE, {"message": message, "session_id": session_id})
            self.events.emit(EventType.MODEL_START, {"message": message, "session_id": session_id})

            # 构建输入 - 使用 messages 格式
            input_data = {"messages": [HumanMessage(content=message)]}

            # 获取当前上下文并复制到线程池
            ctx = copy_context()

            # 检查是否启用流式输出
            if self.config.agent.enable_streaming:
                # 使用 stream 方法实现流式输出
                output_content = await self._stream_chat(input_data, ctx, session_id)
                result = None  # 流式输出不需要 result
            else:
                # 执行 Agent - 使用 langchain 的 invoke 方法
                # 返回的是一个包含 messages 的字典
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: ctx.run(lambda: self.agent.invoke(input_data))
                )

                # 从结果中提取最终消息
                messages = result.get("messages", [])
                output_content = ""

                # 获取最后一条 AI 消息
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage):
                        output_content = msg.content
                        break

            # 检查中断状态
            self._check_interrupt()

            self.events.emit(EventType.MODEL_STOP, {})

            # 流式模式下，已经在 _stream_chat 中处理了内容
            # 非流式模式需要从 result 中提取
            thinking_content = ""
            if not self.config.agent.enable_streaming and result:
                # 从结果中提取最终消息
                messages = result.get("messages", [])

                # 获取最后一条 AI 消息
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage):
                        output_content = msg.content
                        # 检查是否有思考内容
                        if hasattr(msg, "additional_kwargs"):
                            kwargs = msg.additional_kwargs
                            if "reasoning_content" in kwargs:
                                thinking_content = kwargs["reasoning_content"]
                        break

            # 如果启用了深度思考，尝试提取思考内容
            if self.config.model.enable_thinking and not thinking_content:
                thinking_content = self._extract_thinking(output_content)
                if thinking_content:
                    # 移除思考内容，只保留最终回复
                    output_content = output_content.replace(thinking_content, "").strip()
                    # 尝试清理思考标记
                    output_content = self._cleanup_thinking_markers(output_content)

            # 发射深度思考事件（非流式模式下）
            if self.config.model.enable_thinking and thinking_content and not self.config.agent.enable_streaming:
                self.events.emit(EventType.THINKING_START, {})
                self.events.emit(EventType.THINKING_CONTENT, {"content": thinking_content})
                self.events.emit(EventType.THINKING_STOP, {})

            self.events.emit(EventType.SESSION_STOP, {"session_id": session_id})
            return {
                "success": True,
                "content": output_content,
                "think": thinking_content,  # 思考过程
                "tool_calls": [],
                "duration": 0,
                "session_id": session_id
            }

        except AgentInterruptedError as e:
            logger.info(f"[AGENT] Agent interrupted: {e}")
            self.events.emit(EventType.MODEL_STOP, {})
            self.events.emit(EventType.SESSION_STOP, {"session_id": session_id})
            return {
                "success": False,
                "content": "Agent execution was interrupted",
                "interrupted": True,
                "session_id": session_id
            }

        except Exception as e:
            logger.error(f"[AGENT] Error: {e}")
            self.events.emit(EventType.MODEL_ERROR, {"error": str(e)})
            self.events.emit(EventType.SESSION_STOP, {"session_id": session_id})
            return {
                "success": False,
                "content": str(e),
                "error": str(e),
                "session_id": session_id
            }
        finally:
            # 重置 session_id
            _current_session_id.reset(token)

    async def _stream_chat(self, input_data: Dict, ctx, session_id: str) -> str:
        """流式聊天处理

        使用回调处理器在 LLM 级别捕获 token，并解析 Agent 流输出中的工具调用事件

        Args:
            input_data: 输入数据
            ctx: 上下文
            session_id: 会话 ID

        Returns:
            str: 最终输出内容
        """
        current_tool_call_id = None  # 当前工具调用 ID
        current_tool_name = None

        # 更新回调处理器的 session_id
        if hasattr(self.llm, 'callbacks'):
            for callback in self.llm.callbacks:
                if isinstance(callback, StreamCallbackHandler):
                    callback.session_id = session_id

        try:
            # 使用 stream 方法获取流式输出
            for chunk in self.agent.stream(input_data, config={"recursion_limit": self._max_iterations}):
                self._check_interrupt()

                # 解析 LangChain Agent stream 输出:
                # - {'model': {'messages': [AIMessage(...)]}} - AI 消息，可能有 tool_calls
                # - {'tools': {'messages': [ToolMessage(...)]}} - 工具返回结果

                # 1. 处理 model 块 - AI 消息和工具调用
                if "model" in chunk:
                    for msg in chunk.get("model", {}).get("messages", []):
                        if isinstance(msg, AIMessage):
                            # 触发工具开始事件
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    if tc.get("id") != current_tool_call_id:
                                        # 结束上一个工具
                                        if current_tool_call_id:
                                            self.events.emit(EventType.TOOL_CALL_STOP, 
                                                {"name": current_tool_name, "session_id": session_id})
                                        current_tool_call_id = tc.get("id")
                                        current_tool_name = tc.get("name")
                                        self.events.emit(EventType.TOOL_CALL_START, {
                                            "name": current_tool_name,
                                            "args": tc.get("args", {}),
                                            "id": current_tool_call_id,
                                            "session_id": session_id
                                        })

                            # 触发思考内容事件
                            kwargs = msg.additional_kwargs or {}
                            if "reasoning_content" in kwargs:
                                self.events.emit(EventType.THINKING_CONTENT, 
                                    {"content": kwargs["reasoning_content"], "session_id": session_id})

                # 2. 处理 tools 块 - 工具返回结果
                if "tools" in chunk:
                    for msg in chunk.get("tools", {}).get("messages", []):
                        if hasattr(msg, "content"):
                            self.events.emit(EventType.TOOL_RESULT, {
                                "content": msg.content,
                                "name": getattr(msg, "name", ""),
                                "tool_call_id": getattr(msg, "tool_call_id", None),
                                "session_id": session_id
                            })
                            # 触发工具结束事件
                            if current_tool_call_id:
                                self.events.emit(EventType.TOOL_CALL_STOP, 
                                    {"name": current_tool_name, "session_id": session_id})
                                current_tool_call_id = None

                await asyncio.sleep(0)

            # 处理最后一个工具调用
            if current_tool_call_id:
                self.events.emit(EventType.TOOL_CALL_STOP, {"name": current_tool_name, "session_id": session_id})

        except Exception as e:
            logger.error(f"[AGENT] Stream error: {e}")
            self.events.emit(EventType.MODEL_ERROR, {"error": str(e), "session_id": session_id})
            raise

        # 从回调中获取完整内容
        if hasattr(self.llm, 'callbacks'):
            for callback in self.llm.callbacks:
                if isinstance(callback, StreamCallbackHandler):
                    return callback.content

        return ""

    def _extract_thinking(self, content: str) -> str:
        """从内容中提取思考内容

        支持多种格式:
        - <thinking>...</thinking>
        - <!-- thinking: ... -->
        - =====thinking===== ... =====

        Args:
            content: 原始内容

        Returns:
            str: 提取的思考内容，如果不存在则返回空字符串
        """
        import re

        patterns = [
            r'<thinking>(.*?)</thinking>',
            r'<!--\s*thinking:\s*(.*?)\s*-->',
            r'=====thinking=====(.*?)=====',  # 匹配 =====thinking===== 内容 =====
            r'\[THINKING\](.*?)\[/THINKING\]',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return ""

    def _cleanup_thinking_markers(self, content: str) -> str:
        """清理残留的思考标记

        Args:
            content: 清理后的内容

        Returns:
            str: 清理后的内容
        """
        import re

        # 清理各种思考标记
        patterns = [
            r'<thinking>\s*</thinking>',
            r'<!--\s*thinking:\s*-->',
            r'=====thinking=====\s*=====',
            r'\[THINKING\]\s*\[/THINKING\]',
        ]

        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)

        return content.strip()

    def run_skill(self, skill_name: str) -> str:
        """运行 Skill"""
        return self.skills_loader.get_skill_content(skill_name)

    def list_skills(self) -> List[str]:
        """列出 Skills"""
        return self.skills_loader.list_skills()

    def list_tools(self) -> List[Dict[str, str]]:
        """列出工具"""
        return [{"name": t.name, "description": t.description} for t in get_all_tools()]


def create_agent(
    config: FrameworkConfig = None,
    config_path: str = None,
    workspace_path: str = None,
    allow_tools: List[str] = None,
    system_prompt: str = None,
    custom_capabilities: List[tuple] = None,
    enable_ref_cache: bool = True,
    ref_cache_instruction: str = None,
    events: EventEmitter = None,
    request_transformer: Callable = None,
    response_transformer: Callable = None,
    tools: List = None,
    sub_agents: List[Agent] = None
) -> Agent:
    """创建 Agent 实例

    Args:
        config: 框架配置
        config_path: 配置文件路径
        workspace_path: 工作目录
        allow_tools: 允许的工具列表
        system_prompt: 自定义系统提示词模板（支持 {name}, {description}, {workspace}, {skills}, {tools} 占位符）
        custom_capabilities: 自定义能力章节列表，格式: [(标题, [行列表]), ...]
            例: [("Custom Section", ["- item1", "- item2"])]
        enable_ref_cache: 是否启用工具结果引用缓存（默认启用）
        ref_cache_instruction: 自定义引用缓存说明（None 时使用默认说明，设为空字符串禁用）
        events: 事件发射器（可选，默认创建新实例）
        request_transformer: 请求转换函数，接收原始请求 dict，返回转换后的请求 dict
        response_transformer: 响应转换函数，接收原始响应 dict，返回转换后的响应 dict
        tools: 自定义工具列表（可选，使用 langchain 的 @tool 装饰器创建的工具）
        sub_agents: 子 Agent 列表（可选，这些 Agent 可以作为工具被调用）

    Returns:
        Agent 实例
    """
    if config is None:
        config = create_config(config_path)
    return Agent(
        config=config,
        workspace_path=workspace_path,
        allow_tools=allow_tools,
        system_prompt=system_prompt,
        custom_capabilities=custom_capabilities,
        enable_ref_cache=enable_ref_cache,
        ref_cache_instruction=ref_cache_instruction,
        events=events,
        request_transformer=request_transformer,
        response_transformer=response_transformer,
        tools=tools,
        sub_agents=sub_agents
    )

