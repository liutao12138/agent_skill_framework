#!/usr/bin/env python3
"""
示例：工具结果变量传递

演示如何使用占位符引用之前的工具结果：
- ${tool_result.N} - 引用第N次工具执行结果
- ${tool_result.last} - 引用最后一次工具结果
- ${memory.KEY} - 从全局存储获取值
"""

import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_framework.tools import (
    BaseTool, WorkspaceTool, ToolDefinition, ToolParameter,
    ToolCategory, get_memory_store, truncate_tool_result, ToolRegistry,
    reset_memory_store
)


# ============ 模拟搜索工具（不依赖文件系统） ============

class MockSearchTool(BaseTool):
    """模拟搜索工具 - 用于演示变量传递"""

    def __init__(self):
        super().__init__("search", "Search for files or patterns")
        self._definition = ToolDefinition(
            name=self.name,
            description="Search for files or patterns (mock)",
            category=ToolCategory.SEARCH,
            parameters=[
                ToolParameter("pattern", "string", "Search pattern", required=True),
            ],
            returns="Search results with paths",
            timeout=10
        )
        # 模拟的搜索结果
        self._mock_results = {
            "python": "file1.py\nfile2.py\nfile3.py",
            "config": "config.yaml\nsettings.json",
            "agent": "agent.py\nsub_agent.py",
        }

    def execute(self, pattern: str, **kwargs) -> str:
        # 模拟搜索
        result = self._mock_results.get(pattern.lower(), f"No matches for: {pattern}")
        # 保存到全局存储
        store = get_memory_store()
        store.set("last_search_result", result)
        store.set("last_search_files", result)
        return result


# ============ 模拟总结工具 ============

class MockSummaryTool(BaseTool):
    """模拟总结工具 - 用于演示变量传递"""

    def __init__(self):
        super().__init__("summary", "Summarize content")
        self._definition = ToolDefinition(
            name=self.name,
            description="Summarize given paths or content (mock)",
            category=ToolCategory.FILE,
            parameters=[
                ToolParameter("content", "string", "Content to summarize", required=True),
            ],
            returns="Summary",
            timeout=10
        )
        self._summaries = {}

    def execute(self, content: str, **kwargs) -> str:
        # 模拟总结
        lines = content.split('\n')
        summary = f"Summary of {len(lines)} items:\n"
        for i, line in enumerate(lines[:5], 1):
            summary += f"  {i}. {line}\n"
        if len(lines) > 5:
            summary += f"  ... and {len(lines) - 5} more"
        self._summaries["last"] = summary
        return summary


# ============ 模拟读取文件工具 ============

class MockReadTool(BaseTool):
    """模拟读取文件工具 - 用于演示变量传递"""

    def __init__(self):
        super().__init__("mock_read", "Read file contents (demo)")
        self._definition = ToolDefinition(
            name=self.name,
            description="Read file contents (demo)",
            category=ToolCategory.FILE,
            parameters=[
                ToolParameter("path", "string", "File path", required=True),
            ],
            returns="File contents",
            timeout=10
        )
        self._files = {
            "file1.py": "def hello():\n    print('Hello World')\n    return True",
            "file2.py": "class Calculator:\n    def add(self, a, b):\n        return a + b",
            "file3.py": "import os\n\ndef main():\n    pass",
            "agent.py": "# Agent implementation\nclass Agent:\n    def run(self):\n        return True",
            "config.yaml": "key: value\ntimeout: 30",
        }

    def execute(self, path: str, **kwargs) -> str:
        # 清理路径（去掉空格等）
        path = path.strip()
        
        result = self._files.get(path, f"File not found: {path}")
        # 保存到全局存储
        store = get_memory_store()
        store.set(f"file_{path}", result)
        return result


# ============ 模拟Agent ============

class MockAgent:
    """模拟Agent的变量替换和工具执行"""

    def __init__(self):
        self._tool_results = []  # 保存工具执行结果历史
        reset_memory_store()

    def _resolve_placeholders(self, args: dict) -> dict:
        """解析占位符"""
        import re
        resolved = {}

        for key, value in args.items():
            if not isinstance(value, str):
                resolved[key] = value
                continue

            # ${tool_result.N}
            tool_match = re.search(r'\$\{tool_result\.(\d+)\}', value)
            if tool_match:
                index = int(tool_match.group(1))
                if 0 <= index < len(self._tool_results):
                    result = self._tool_results[index].get("output", "")
                    value = value.replace(tool_match.group(0), result)

            # ${tool_result.last}
            if "${tool_result.last}" in value:
                if self._tool_results:
                    result = self._tool_results[-1].get("output", "")
                    value = value.replace("${tool_result.last}", result)

            # ${memory.KEY}
            memory_match = re.search(r'\$\{memory\.([^}]+)\}', value)
            if memory_match:
                mem_key = memory_match.group(1)
                store = get_memory_store()
                mem_value = store.get(mem_key)
                if mem_value is not None:
                    value = value.replace(memory_match.group(0), mem_value)

            resolved[key] = value

        return resolved

    def execute_tool(self, name: str, **kwargs) -> dict:
        """执行工具并保存结果"""
        # 解析占位符
        resolved_args = self._resolve_placeholders(kwargs)

        # 获取工具并执行
        tool = registry.get(name)
        if tool is None:
            output = f"Error: Unknown tool: {name}"
        else:
            output = tool.execute(**resolved_args)

        # 保存结果
        result = {
            "tool_name": name,
            "output": output,
            "success": not output.startswith("Error:")
        }
        self._tool_results.append(result)

        return result


# ============ 演示变量传递 ============

# 创建工具注册表
registry = ToolRegistry("./workspace")
registry.register(MockSearchTool())
registry.register(MockSummaryTool())
registry.register(MockReadTool())


async def demo_variable_passing():
    """演示变量传递功能"""
    print("=" * 70)
    print("演示：工具结果变量传递")
    print("=" * 70)

    # 创建模拟Agent
    agent = MockAgent()

    # ===== 演示1: ${tool_result.last} =====
    print("\n【演示1】使用 ${tool_result.last} 引用上次结果")
    print("-" * 50)
    print(">> 执行 search 工具，搜索 'python'")
    result1 = agent.execute_tool("search", pattern="python")
    print(f"结果:\n{result1['output']}")

    print("\n>> 执行 summary 工具，使用 ${tool_result.last} 引用搜索结果")
    print(f"参数: {{'content': '${{tool_result.last}}'}}")
    result2 = agent.execute_tool("summary", content="${tool_result.last}")
    print(f"结果:\n{result2['output']}")

    # ===== 演示2: ${tool_result.N} =====
    print("\n【演示2】使用 ${tool_result.0} 引用指定索引的结果")
    print("-" * 50)
    print(f">> 引用第0次搜索结果: {agent._tool_results[0]['tool_name']}")
    result3 = agent.execute_tool("summary", content="${tool_result.0}")
    print(f"结果:\n{result3['output']}")

    # ===== 演示3: ${memory.KEY} =====
    print("\n【演示3】使用 ${memory.KEY} 从全局存储获取")
    print("-" * 50)
    store = get_memory_store()
    print(">> 全局存储中的内容:")
    for key in store.list_keys():
        value = store.get(key)[:80] if len(store.get(key)) > 80 else store.get(key)
        print(f"   {key}: {value}")

    print("\n>> 使用 ${memory.last_search_files} 获取存储的路径列表")
    result4 = agent.execute_tool("summary", content="${memory.last_search_files}")
    print(f"结果:\n{result4['output']}")

    # ===== 演示4: 直接读取文件 =====
    print("\n【演示4】直接读取文件")
    print("-" * 50)
    print(">> 直接读取 file1.py")
    result5 = agent.execute_tool("mock_read", path="file1.py")
    print(f"文件内容:\n{result5['output']}")

    # ===== 演示5: 工具执行历史 =====
    print("\n【演示5】工具执行历史")
    print("-" * 50)
    print("工具执行历史:")
    for i, res in enumerate(agent._tool_results):
        status = "OK" if res['success'] else "FAIL"
        preview = res['output'][:60].replace('\n', ' ')
        print(f"  [{i}] {res['tool_name']}: {status} - {preview}...")

    print("\n" + "=" * 70)
    print("演示完成！")
    print("=" * 70)
    print("\n【变量传递格式说明】")
    print("  ${tool_result.N}    - 引用第N次工具执行结果（0-indexed）")
    print("  ${tool_result.last} - 引用最后一次工具执行结果")
    print("  ${memory.KEY}      - 从全局存储获取值")
    print("\n【使用场景】")
    print("  1. 搜索文件 -> 读取文件内容")
    print("  2. 获取路径列表 -> 批量处理文件")
    print("  3. 存储中间结果 -> 跨轮次引用")
    print("  4. Chain: search -> read -> summarize")


# ============ 直接运行 ============

if __name__ == "__main__":
    asyncio.run(demo_variable_passing())
