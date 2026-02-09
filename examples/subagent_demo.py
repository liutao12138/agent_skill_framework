#!/usr/bin/env python3
"""Agent Framework - SubAgent 示例
演示如何注册和使用自定义子Agent
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent
from agent_framework.sub_agent import SubAgentConfig
from agent_framework import create_agent, setup_logging

setup_logging("DEBUG")

def setup_custom_subagents(agent):
    """注册自定义子Agent"""
    manager = agent.subagent_manager

    # 注册代码编写子Agent
    manager.register(SubAgentConfig(
        name="coder",
        description="Expert coder for implementing features",
        system_prompt="""You are an expert coding agent. Your job is to write clean, well-documented code.
Always follow best practices and explain your code.""",
        allowed_tools=["bash", "read_file", "write_file", "list_dir"],
        max_iterations=50,
    ))

    # 注册代码审查子Agent
    manager.register(SubAgentConfig(
        name="reviewer",
        description="Expert code reviewer for finding issues",
        system_prompt="""You are a code review expert. Review code for:
- Potential bugs
- Security vulnerabilities
- Performance issues
- Code style violations
Provide detailed feedback with line numbers if possible.""",
        allowed_tools=["bash", "read_file", "list_dir"],
        max_iterations=30,
    ))

    # 注册文档编写子Agent
    manager.register(SubAgentConfig(
        name="writer",
        description="Expert technical writer for documentation",
        system_prompt="""You are a technical documentation writer. Write clear, concise documentation
that explains concepts in a way that beginners can understand.
Use examples where appropriate.""",
        allowed_tools=["read_file", "write_file"],
        max_iterations=20,
    ))

    print(f"[SETUP] Registered {len(manager._configs)} subagents:")
    for name in manager._configs:
        print(f"  - subagent_{name}")


def print_separator(title: str = ""):
    print("\n" + "=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)


async def main():
    """主函数"""
    print_separator("SubAgent Demo")

    # 创建 Agent
    agent = create_agent()

    # 注册自定义子Agent
    setup_custom_subagents(agent)

    # 显示已注册的子Agent工具定义
    print_separator("SubAgent Tools")
    definitions = agent.subagent_manager.get_subagent_definitions()
    for d in definitions:
        print(f"- {d['function']['name']}: {d['function']['description']}")

    # 测试子Agent调用
    print_separator("Test: Ask model to use subagent")
    print("Task: '请使用 coder 子Agent 写一个 Python hello world 程序'")

    response = await agent.chat(
        "请使用 coder 子Agent 写一个 Python hello world 程序",
        stream=False
    )

    print(f"\n[RESULT] Success: {response['success']}")
    print(f"[RESULT] Content:\n{response['content']}")

    if response.get('subagent_results'):
        print(f"\n[SUBAGENT] Results: {len(response['subagent_results'])}")
        for sr in response['subagent_results']:
            print(f"  - {sr['subagent_name']}: success={sr['result'].get('success')}")

    print(f"\n[INFO] Total iterations: {response['iterations']}")
    print(f"[INFO] Duration: {response['duration']:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
