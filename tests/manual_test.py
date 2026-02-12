#!/usr/bin/env python3
"""手动测试脚本 - 验证所有新功能"""
import sys
import asyncio
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_framework.tools import (
    truncate_tool_result, TOOL_RESULT_HARD_LIMIT,
    get_memory_store, reset_memory_store,
    MemoryTool, ToolRegistry, execute_tool, execute_tool_async,
    BaseTool, WorkspaceTool, ToolDefinition, ToolParameter, MemoryStore
)
from agent_framework.events import EventEmitter, EventType


def test_truncate_tool_result():
    """测试工具结果截断功能"""
    print("\n=== Test 1: Tool Result Truncation ===")

    # 测试1: 短结果不应被截断
    result = "Hello, World!"
    truncated = truncate_tool_result(result)
    assert truncated == result, "Short result should remain unchanged"
    print("[PASS] Short result test")

    # 测试2: 超过硬上限的结果应被截断
    long_result = "x" * (TOOL_RESULT_HARD_LIMIT + 1000)
    truncated = truncate_tool_result(long_result)
    assert len(truncated) < len(long_result), "Long result should be truncated"
    assert "[... 内容被截断" in truncated, "Truncated result should contain marker"
    print(f"[PASS] Long result truncation test (original: {len(long_result)}, truncated: {len(truncated)})")

    # 测试3: 保留头部和尾部
    head = "HEAD_CONTENT"
    tail = "TAIL_CONTENT"
    result_with_head_tail = head + "y" * 10000 + tail
    truncated = truncate_tool_result(result_with_head_tail)
    assert truncated.startswith(head), "Should preserve head"
    assert truncated.endswith(tail), "Should preserve tail"
    print("[PASS] Head/Tail preservation test")

    print("[PASS] All truncation tests!\n")


def test_memory_store():
    """测试全局Memory存储（用于${memory.KEY}引用）"""
    print("=== Test 2: Global Memory Storage ===")

    reset_memory_store()
    store = get_memory_store()
    store.clear()

    # 测试设置和获取
    store.set("key1", "value1")
    assert store.get("key1") == "value1", "Set and get should match"
    print("[PASS] Set/Get test")

    # 测试删除
    store.delete("key1")
    assert store.get("key1") is None, "Should not get after delete"
    print("[PASS] Delete test")

    # 测试搜索
    store.set("test1", "hello world")
    store.set("test2", "hello python")
    results = store.search("hello")
    assert len(results) == 2, "Should find two matches"
    print("[PASS] Search test")

    # 测试列出键
    keys = store.list_keys()
    assert len(keys) == 2, "Should list two keys"
    print("[PASS] List keys test")

    # 测试清空
    store.clear()
    assert len(store.list_keys()) == 0, "Should have no keys after clear"
    print("[PASS] Clear test")

    print("[PASS] All memory storage tests!\n")


def test_memory_tool():
    """测试MemoryTool（Agent级存储）"""
    print("=== Test 3: MemoryTool (Agent-level Storage) ===")

    # 重置全局存储（确保干净的状态）
    reset_memory_store()

    # 模拟Agent - 每个Agent有自己独立的MemoryStore
    agent1_memory = MemoryStore()
    agent2_memory = MemoryStore()

    # Agent1存储数据
    agent1_memory.set("test_key", "value1")

    # Agent2无法访问Agent1的存储
    result = agent2_memory.get("test_key")
    assert result is None, "Different agents should have isolated storage"
    print("[PASS] Agent isolation test")

    # Agent1可以访问自己的存储
    result = agent1_memory.get("test_key")
    assert result == "value1", "Agent should access its own storage"
    print("[PASS] Agent self-storage test")

    # 测试MemoryTool（通过_get_memory_store降级到全局存储）
    reset_memory_store()
    tool = MemoryTool()
    result = tool.execute(action="set", key="shared_key", value="shared_value")
    assert "Success" in result, "set operation should succeed"
    print("[PASS] MemoryTool set test")

    result = tool.execute(action="get", key="shared_key")
    assert result == "shared_value", "get should return correct value"
    print("[PASS] MemoryTool get test")

    print("[PASS] All MemoryTool tests!\n")


def test_async_tool():
    """测试异步工具执行"""
    print("=== Test 4: Async Tool Execution ===")

    # 创建带异步方法的工具
    class AsyncTestTool(WorkspaceTool):
        def __init__(self):
            super().__init__("async_test", "Test async tool")
            self._definition = ToolDefinition(
                name=self.name, description=self.description,
                parameters=[ToolParameter("value", "string", "A value", required=True)],
                returns="Processed value"
            )

        async def execute(self, value: str, **kwargs) -> str:
            await asyncio.sleep(0.01)  # 模拟异步操作
            return f"async: {value}"

    async_tool = AsyncTestTool()

    # 测试异步方法检测
    assert async_tool._is_async() is True, "Async method should be detected"
    print("[PASS] Async method detection test")

    # 创建临时registry并注册工具
    import tempfile
    registry = ToolRegistry(tempfile.mkdtemp())
    registry.register(async_tool)

    # 测试同步执行异步方法
    result = registry.execute("async_test", value="test")
    assert "async: test" in result, "Should be able to execute async method synchronously"
    print("[PASS] Sync execute async method test")

    print("[PASS] All async tool tests!\n")


def test_events_no_callbacks():
    """测试events中已删除_callbacks"""
    print("=== Test 5: Events No Callbacks ===")

    emitter = EventEmitter()

    # 验证没有_callbacks属性
    has_callbacks = hasattr(emitter, '_callbacks')
    assert not has_callbacks, "EventEmitter should not have _callbacks attribute"
    print("[PASS] EventEmitter has no _callbacks attribute")

    # 验证没有add_callback方法
    has_add_callback = hasattr(emitter, 'add_callback')
    assert not has_add_callback, "EventEmitter should not have add_callback method"
    print("[PASS] EventEmitter has no add_callback method")

    # 验证有_handlers属性
    assert hasattr(emitter, '_handlers'), "EventEmitter should have _handlers attribute"
    print("[PASS] EventEmitter has _handlers attribute")

    print("[PASS] All Events tests!\n")


def test_variable_substitution():
    """测试变量替换功能（在Agent中）"""
    print("=== Test 6: Variable Substitution ===")

    from agent_framework.tools import MemoryStore

    # 模拟Agent的变量替换逻辑 - 每个Agent有自己的MemoryStore
    class MockAgent:
        def __init__(self):
            self._tool_results = []
            self._memory_store = MemoryStore()  # Agent级存储

        def _resolve_placeholders(self, args):
            import re
            resolved = {}

            for key, value in args.items():
                if not isinstance(value, str):
                    resolved[key] = value
                    continue

                # 1. ${tool_result.N}
                tool_match = re.search(r'\$\{tool_result\.(\d+)\}', value)
                if tool_match:
                    index = int(tool_match.group(1))
                    if 0 <= index < len(self._tool_results):
                        result = self._tool_results[index].get("output", "")
                        value = value.replace(tool_match.group(0), result)

                # 2. ${tool_result.last}
                if "${tool_result.last}" in value:
                    if self._tool_results:
                        result = self._tool_results[-1].get("output", "")
                        value = value.replace("${tool_result.last}", result)

                # 3. ${memory.KEY} - 使用Agent的MemoryStore
                memory_match = re.search(r'\$\{memory\.([^}]+)\}', value)
                if memory_match:
                    mem_key = memory_match.group(1)
                    mem_value = self._memory_store.get(mem_key)
                    if mem_value is not None:
                        value = value.replace(memory_match.group(0), mem_value)

                resolved[key] = value

            return resolved

    agent = MockAgent()

    # 保存一个工具结果
    agent._tool_results.append({
        "tool_name": "grep",
        "output": "path/to/file.py",
        "success": True
    })

    # 测试 ${tool_result.0}
    args = {"path": "${tool_result.0}"}
    resolved = agent._resolve_placeholders(args)
    assert resolved["path"] == "path/to/file.py", "tool_result.0 should be replaced"
    print("[PASS] ${tool_result.N} substitution test")

    # 测试 ${tool_result.last}
    args = {"path": "${tool_result.last}"}
    resolved = agent._resolve_placeholders(args)
    assert resolved["path"] == "path/to/file.py", "tool_result.last should be replaced"
    print("[PASS] ${tool_result.last} substitution test")

    # 测试 ${memory.KEY} - 使用Agent的MemoryStore
    agent._memory_store.set("my_path", "/workspace/file.txt")
    args = {"path": "${memory.my_path}"}
    resolved = agent._resolve_placeholders(args)
    assert resolved["path"] == "/workspace/file.txt", "memory key should be replaced"
    print("[PASS] ${memory.KEY} substitution test (agent storage)")

    print("[PASS] All variable substitution tests!\n")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("Agent Framework 功能测试")
    print("=" * 60)

    try:
        test_truncate_tool_result()
        test_memory_store()
        test_memory_tool()
        test_async_tool()
        test_events_no_callbacks()
        test_variable_substitution()

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
    sys.exit(main())
