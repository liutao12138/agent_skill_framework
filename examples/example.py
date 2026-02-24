#!/usr/bin/env python3
"""Agent Framework - 简单示例（基于 LangChain Agent）"""

import sys
import os
import asyncio

# 设置 UTF-8 输出
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent, setup_logging

setup_logging("INFO")


async def main():
    """基础聊天示例"""
    # 创建 Agent
    agent = create_agent()

    # 列出可用工具
    print("\n=== Available Tools ===")
    tools = agent.list_tools()
    for t in tools:
        print(f"  - {t['name']}: {t['description']}")

    # 简单对话
    user_msg = "请写一个 Python 的 hello world 程序"

    print(f"\n{'='*60}")
    print(f"[USER] {user_msg}")
    print(f"{'='*60}")
    print("[MODEL] ", end="", flush=True)

    response = await agent.chat(user_msg)

    print(f"\n\n{'='*60}")
    print(f"[SUCCESS] {response['success']}")
    print(f"[CONTENT]\n{response.get('content', '')}")

    # 如果启用了深度思考，显示思考过程
    if response.get('think'):
        print(f"\n[THINKING]\n{response['think']}")

    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
