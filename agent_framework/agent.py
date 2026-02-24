#!/usr/bin/env python3
"""Agent Framework - 基于 LangChain Agent

直接使用 LangChain 的 Agent 能力，简化框架实现
"""

import asyncio
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import BaseTool, StructuredTool
from langchain.agents.factory import create_agent as langchain_create_agent

from .config import get_config, create_config, FrameworkConfig
from .logger import get_logger
from .skill_loader import get_skills_loader
from .tools import get_tool_registry, BaseTool as FrameworkBaseTool
from .events import EventEmitter, EventType
from .result_cache import create_result_cache

logger = get_logger()

# 全局事件发射器
_events: Optional[EventEmitter] = None


def get_events() -> EventEmitter:
    """获取全局事件发射器"""
    global _events
    if _events is None:
        _events = EventEmitter()
    return _events


def _create_langchain_tool(framework_tool: FrameworkBaseTool, result_cache=None) -> BaseTool:
    """将框架工具转换为 LangChain 工具
    
    Args:
        framework_tool: 框架工具实例
        result_cache: 结果缓存实例（可选）
    """
    definition = framework_tool.get_definition()

    # 构建参数模式
    properties = {}
    required = []
    for param in definition.parameters:
        prop = {"type": param.type, "description": param.description}
        if param.enum:
            prop["enum"] = param.enum
        if param.default is not None:
            prop["default"] = param.default
        properties[param.name] = prop
        if param.required:
            required.append(param.name)

    args_schema = {
        "type": "object",
        "properties": properties,
        "required": required
    }

    # 获取执行函数
    def execute_func(**kwargs):
        """同步执行工具，支持引用解析"""
        
        # 解析参数中的引用
        if result_cache:
            for key, value in kwargs.items():
                if isinstance(value, str) and value.startswith("$"):
                    # 解析引用
                    resolved = result_cache.resolve_reference(value)
                    if resolved is not None:
                        kwargs[key] = resolved
        
        # 执行工具
        if framework_tool._is_async():
            # 如果是异步工具，使用事件循环同步执行
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                raw_result = loop.run_until_complete(framework_tool.execute(**kwargs))
            finally:
                loop.close()
        else:
            raw_result = framework_tool.execute(**kwargs)
        
        # 如果有缓存，存储结果并返回引用格式
        if result_cache and raw_result:
            # 存储结果
            ref_id = result_cache.put(raw_result, {
                "tool": definition.name,
                "args": kwargs
            })
            # 返回带引用的结果
            result_str = str(raw_result)
            return f"[RESULT:{ref_id}]{result_str}[/RESULT]"
        
        return raw_result

    # 创建 LangChain 工具
    return StructuredTool(
        name=definition.name,
        description=definition.description,
        args_schema=args_schema,
        func=execute_func
    )


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
        ref_cache_instruction: str = None
    ):
        self.config = config or get_config()
        self.workspace_path = workspace_path or self.config.workspace.root_path
        self.events = get_events()
        self.skills_loader = get_skills_loader(self.workspace_path)
        self.tool_registry = get_tool_registry()
        self.allow_tools = allow_tools

        # 引用缓存 - 用于工具结果传递（每个 Agent 独立实例）
        self.enable_ref_cache = enable_ref_cache
        self.result_cache = create_result_cache() if enable_ref_cache else None
        
        # 自定义引用缓存说明（None 时使用默认说明）
        self._ref_cache_instruction = ref_cache_instruction

        # 自定义系统提示词和能力章节
        self._system_prompt = system_prompt
        self._custom_capabilities = custom_capabilities or []

        # 初始化 LangChain 组件
        self._init_langchain()

        # 加载 Skills
        self._load_skills()

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

        # 创建 ChatOpenAI 实例
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

    def _get_tools(self) -> List[BaseTool]:
        """获取工具列表"""
        all_tools = self.tool_registry.get_all()

        if self.allow_tools:
            tools = [t for t in all_tools if t.name in self.allow_tools]
        else:
            tools = all_tools

        return [_create_langchain_tool(t, self.result_cache) for t in tools]

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
                tools="\n".join(f"- {t.name}: {t.description}" for t in self.tool_registry.get_all())
            )
            # 附加引用说明
            if self.enable_ref_cache:
                system_message += ref_instruction
        else:
            # 构建默认系统提示词
            skills_desc = self.skills_loader.get_descriptions()
            tools_desc = "\n".join(
                f"- {t.name}: {t.description}"
                for t in self.tool_registry.get_all()
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
        self.events.emit(EventType.USER_MESSAGE, {"message": message})

        try:
            # 构建输入 - 使用 messages 格式
            input_data = {"messages": [HumanMessage(content=message)]}

            # 执行 Agent - 使用 langchain 的 invoke 方法
            # 返回的是一个包含 messages 的字典
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.agent.invoke(input_data)
            )

            self.events.emit(EventType.MODEL_STOP, {})

            # 从结果中提取最终消息
            messages = result.get("messages", [])
            output_content = ""
            thinking_content = ""

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

            # 发射深度思考事件
            if self.config.model.enable_thinking and thinking_content:
                self.events.emit(EventType.THINKING_START, {})
                self.events.emit(EventType.THINKING_CONTENT, {"content": thinking_content})
                self.events.emit(EventType.THINKING_STOP, {})

            return {
                "success": True,
                "content": output_content,
                "think": thinking_content,  # 思考过程
                "tool_calls": [],
                "duration": 0
            }

        except Exception as e:
            logger.error(f"[AGENT] Error: {e}")
            return {
                "success": False,
                "content": str(e),
                "error": str(e)
            }

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
        return [{"name": t.name, "description": t.description} for t in self.tool_registry.get_all()]


def create_agent(
    config: FrameworkConfig = None,
    config_path: str = None,
    workspace_path: str = None,
    allow_tools: List[str] = None,
    system_prompt: str = None,
    custom_capabilities: List[tuple] = None,
    enable_ref_cache: bool = True,
    ref_cache_instruction: str = None
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
        ref_cache_instruction=ref_cache_instruction
    )


async def run_chat(message: str, config_path: str = None) -> Dict[str, Any]:
    """快捷聊天接口"""
    agent = create_agent(config_path=config_path)
    return await agent.chat(message)
