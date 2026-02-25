#!/usr/bin/env python3
"""Agent Framework - 自定义系统提示词示例

演示如何自定义系统提示词和能力章节
"""

import sys
import os
import asyncio
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent, DEFAULT_CAPABILITIES

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')


async def main():
    """自定义提示词示例"""
    print("\n=== 示例 1: 自定义能力章节 ===")

    # 自定义能力章节
    my_capabilities = [
        ("My Special Abilities", [
            "- Can solve complex math problems",
            "- Expert at code review",
            "- Good at explaining concepts"
        ]),
        ("Response Style", [
            "- Always provide step-by-step explanations",
            "- Include code examples when relevant",
            "- Summarize key points at the end"
        ])
    ]

    # 合并默认能力和自定义能力
    agent = create_agent(custom_capabilities=DEFAULT_CAPABILITIES + my_capabilities)

    response = await agent.chat("What is 2+2? Explain step by step.")
    print(f"[CONTENT] {response.get('content', '')}")

    print("\n=== 示例 2: 自定义系统提示词模板 ===")

    # 自定义系统提示词模板
    custom_prompt = """You are {name}, a helpful AI assistant.
Working directory: {workspace}

Your personality: Patient, knowledgeable, and always willing to help.

**Skills:**
{skills}

**Available Tools:**
{tools}

Please provide clear and concise answers."""

    agent2 = create_agent(system_prompt=custom_prompt)

    response2 = await agent2.chat("Hello! What can you do?")
    print(f"[CONTENT] {response2.get('content', '')}")

    print("\n=== 示例 3: 完全自定义 ===")

    # 完全自定义
    agent3 = create_agent(
        system_prompt="You are a Python expert. Write clean, Pythonic code.",
        custom_capabilities=[
            ("Python Best Practices", [
                "- Use list comprehensions",
                "- Follow PEP 8",
                "- Write docstrings"
            ])
        ]
    )

    response3 = await agent3.chat("Write a function to calculate factorial.")
    print(f"[CONTENT] {response3.get('content', '')}")


if __name__ == "__main__":
    asyncio.run(main())
