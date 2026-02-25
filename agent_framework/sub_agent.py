"""子 Agent 模块"""

import asyncio
import concurrent.futures
from typing import Any, Dict

from langchain_core.tools import Tool

from .events import EventEmitter, EventType


class SubAgent:
    """子 Agent 工具，用于在 Agent 中调用其他 Agent"""

    def __init__(self, agent: "Agent", name: str = None, description: str = None):
        self.agent = agent
        self.name = name or agent.config.agent.name
        self.description = description or agent.config.agent.description

    def invoke(self, input_data: Dict[str, Any]) -> str:
        """同步调用子 Agent"""
        message = input_data.get("message", "") if isinstance(input_data, dict) else str(input_data)
        session_id = input_data.get("session_id") if isinstance(input_data, dict) else None

        # 检查中断状态
        self.agent._check_interrupt()

        # 发射子 Agent 开始事件
        self.agent.events.emit(EventType.SUBAGENT_START, {"name": self.name, "message": message, "session_id": session_id})

        # 同步执行
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.agent.chat(message, session_id=session_id))
                    result = future.result(timeout=300)
            else:
                result = asyncio.run(self.agent.chat(message, session_id=session_id))
        except RuntimeError:
            result = asyncio.run(self.agent.chat(message, session_id=session_id))
        except Exception as e:
            self.agent.events.emit(EventType.SUBAGENT_ERROR, {"name": self.name, "error": str(e), "session_id": session_id})
            return f"Error: {str(e)}"

        # 发射子 Agent 结束事件
        if result.get("success"):
            self.agent.events.emit(EventType.SUBAGENT_STOP, {"name": self.name, "session_id": session_id})
            return result.get("content", "")
        else:
            self.agent.events.emit(EventType.SUBAGENT_ERROR, {"name": self.name, "error": result.get('error', result.get('content', 'Unknown error')), "session_id": session_id})
            return f"Error: {result.get('error', result.get('content', 'Unknown error'))}"

    def __repr__(self):
        return f"SubAgent(name={self.name})"


def create_sub_agent_tool(agent: "Agent", name: str = None, description: str = None) -> Tool:
    """创建子 Agent 工具"""
    sub_agent = SubAgent(agent, name, description)
    return Tool(
        name=name or f"agent_{agent.config.agent.name.lower().replace(' ', '_')}",
        description=description or f"Use this tool to delegate tasks to {agent.config.agent.name}. {agent.config.agent.description}",
        func=sub_agent.invoke
    )
