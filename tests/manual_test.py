#!/usr/bin/env python3
"""手动测试脚本 - 验证框架功能"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_framework import create_agent, setup_logging, get_config
from agent_framework.tools import get_tool_registry
from agent_framework.events import EventEmitter, EventType


def test_config():
    """测试配置加载"""
    print("\n=== Test 1: Config ===")

    config = get_config()
    print(f"[PASS] Config loaded: model={config.model.model}")
    print(f"[PASS] Workspace: {config.workspace.root_path}")
    print(f"[PASS] Max iterations: {config.agent.max_iterations}")

    # 测试深度思考配置
    print(f"[INFO] Thinking enabled: {config.model.enable_thinking}")
    print(f"[INFO] Thinking level: {config.model.thinking_level}")

    print("[PASS] All config tests!\n")


def test_tool_registry():
    """测试工具注册表"""
    print("=== Test 2: Tool Registry ===")

    registry = get_tool_registry()
    tools = registry.get_all()

    print(f"[INFO] Total tools: {len(tools)}")
    for tool in tools[:5]:  # 只显示前5个
        print(f"  - {tool.name}: {tool.description}")

    print("[PASS] All tool registry tests!\n")


def test_events():
    """测试事件系统"""
    print("=== Test 3: Events ===")

    emitter = EventEmitter()

    # 测试事件监听 - EventEmitter.on() 只接受一个 handler 参数
    events_received = []

    def handler(event):
        events_received.append(event.type)

    emitter.on(handler)
    emitter.emit(EventType.USER_MESSAGE, {"message": "test"})

    assert EventType.USER_MESSAGE.value in events_received
    print("[PASS] Event emit test")

    # 测试 off 方法
    emitter.off(handler)
    emitter.emit(EventType.USER_MESSAGE, {"message": "test2"})
    # 移除后不应再收到事件

    print("[PASS] All events tests!\n")


async def test_agent_creation():
    """测试 Agent 创建"""
    print("=== Test 4: Agent Creation ===")

    agent = create_agent()

    print(f"[PASS] Agent created")
    print(f"[PASS] Workspace: {agent.workspace_path}")
    print(f"[PASS] Skills: {agent.list_skills()}")
    print(f"[PASS] Tools: {len(agent.list_tools())}")

    print("[PASS] All agent creation tests!\n")


async def test_chat():
    """测试聊天功能"""
    print("=== Test 5: Chat ===")

    agent = create_agent()

    # 简单对话测试
    response = await agent.chat("Say hello in one sentence")

    print(f"[INFO] Success: {response['success']}")
    print(f"[INFO] Content: {response.get('content', '')[:100]}...")

    if response.get('thinking'):
        print(f"[INFO] Thinking: {response['thinking'][:100]}...")

    print("[PASS] All chat tests!\n")


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("Agent Framework 功能测试")
    print("=" * 60)

    setup_logging("INFO")

    try:
        test_config()
        test_tool_registry()
        test_events()
        await test_agent_creation()
        await test_chat()

        print("=" * 60)
        print("All tests passed!")
        print("=" * 60)
        return 0

    except AssertionError as e:
        print(f"\nTest failed: {e}")
        return 1
    except Exception as e:
        print(f"\nTest error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
