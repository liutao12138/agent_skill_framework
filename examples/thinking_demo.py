#!/usr/bin/env python3
"""Agent Framework - 深度思考模型示例

演示如何使用支持深度思考的模型（如 GLM-4-Plus, OpenAI o1, Claude 3.5+）
"""

import sys
import os
import asyncio
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent, create_config

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')


async def main():
    """深度思考示例"""
    # 创建配置，启用深度思考
    config = create_config()

    # 启用深度思考
    config.model.enable_thinking = True
    config.model.thinking_level = "high"  # low/medium/high
    config.model.thinking_max_tokens = 8192

    print(f"\n=== Thinking Config ===")
    print(f"  enable_thinking: {config.model.enable_thinking}")
    print(f"  thinking_level: {config.model.thinking_level}")
    print(f"  thinking_max_tokens: {config.model.thinking_max_tokens}")
    print(f"  model: {config.model.model}")

    # 创建 Agent
    agent = create_agent(config=config)

    # 复杂推理任务
    user_msg = "请解决这个数学问题：如果一个数列的前三项是 2, 4, 8，这个数列可能是等比数列还是等差数列？请解释你的推理过程。"

    print(f"\n{'='*60}")
    print(f"[USER] {user_msg}")
    print(f"{'='*60}")
    print("[MODEL] ", end="", flush=True)

    response = await agent.chat(user_msg)

    print(f"\n\n{'='*60}")
    print(f"[SUCCESS] {response['success']}")

    # 显示思考过程
    if response.get('think'):
        print(f"\n[THINKING]\n{response['think']}")

    # 显示最终答案
    print(f"\n[ANSWER]\n{response.get('content', '')}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
