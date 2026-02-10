#!/usr/bin/env python3
"""Agent Framework - 简单示例（流式输出）"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent, setup_logging
from agent_framework.events import EventType, ConsoleEventHandler, Event

setup_logging("DEBUG")


class StreamingTokenPrinter:
    """流式 Token 监听器 - 用于实时打印模型输出的 token"""

    def __init__(self):
        self.enabled = True

    def handle(self, event: Event):
        if event.type == EventType.MODEL_STREAM:
            chunk = event.data.get('chunk', '')
            # 默认console事件有，这里不打印，仅示例


async def main():
    """基础聊天示例（流式输出）"""
    agent = create_agent()

    # 添加流式 Token 监听器
    token_printer = StreamingTokenPrinter()
    agent.events.add_handler(token_printer)

    user_msg = "请写一个react的应用初始化勾子函数代码"

    print(f"\n{'='*60}")
    print(f"[USER] {user_msg}")
    print(f"{'='*60}")
    print("[MODEL] ", end="", flush=True)

    # 流式输出
    response = await agent.chat(user_msg, stream=True)
    content = response.get('content', '')

    print(f"\n\n{'='*60}")
    print(f"[Reply] {content}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
