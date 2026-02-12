#!/usr/bin/env python3
"""Agent Framework Tools - 工具系统"""

import asyncio
import inspect
import os
import re
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, Awaitable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from .logger import get_logger


class ToolCategory(Enum):
    FILE = "file"
    SYSTEM = "system"
    SEARCH = "search"


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = False
    default: Any = None
    enum: List[Any] = field(default_factory=list)


@dataclass
class ToolDefinition:
    name: str
    description: str
    category: ToolCategory = ToolCategory.FILE
    parameters: List[ToolParameter] = field(default_factory=list)
    returns: str = ""
    timeout: int = 30
    require_workspace: bool = True


class BaseTool(ABC):
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._definition: Optional[ToolDefinition] = None

    @abstractmethod
    def execute(self, **kwargs) -> Union[str, Awaitable[str]]:
        """执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            str: 同步执行结果
            Awaitable[str]: 异步执行结果（协程）
        """
        pass

    def _is_async(self) -> bool:
        """检查execute方法是否为异步方法"""
        return inspect.iscoroutinefunction(self.execute)

    def get_definition(self) -> ToolDefinition:
        return self._definition or ToolDefinition(name=self.name, description=self.description)


class WorkspaceTool(BaseTool):
    def __init__(self, name: str, description: str, workspace_path: str = "./workspace"):
        super().__init__(name, description)
        self.workspace_path = Path(workspace_path).resolve()

    def _validate_path(self, path: str) -> Tuple[bool, str, Path]:
        try:
            path_obj = Path(path)
            abs_path = (self.workspace_path / path_obj).resolve() if not path_obj.is_absolute() else path_obj.resolve()

            forbidden = ["/etc", "/root", "/home", "C:\\Windows", "C:\\Users\\Admin\\Desktop", "/proc", "/sys", "/dev"]
            if any(str(abs_path).startswith(p) for p in forbidden):
                return False, f"Path is forbidden: {path}", abs_path

            if not abs_path.is_relative_to(self.workspace_path):
                return False, f"Path escapes workspace: {path}", abs_path

            return True, "", abs_path
        except Exception as e:
            return False, f"Invalid path: {e}", Path(path)


class FileReadTool(WorkspaceTool):
    def __init__(self, workspace_path: str = "./workspace", max_file_size: int = 10 * 1024 * 1024):
        super().__init__("read_file", "Read file contents from workspace", workspace_path)
        self.max_file_size = max_file_size
        self._definition = ToolDefinition(
            name=self.name, description=self.description, category=ToolCategory.FILE,
            parameters=[
                ToolParameter("path", "string", "File path relative to workspace", required=True),
                ToolParameter("limit", "integer", "Maximum lines to read"),
                ToolParameter("offset", "integer", "Line offset to start"),
            ],
            returns="File contents", timeout=30)

    def execute(self, path: str, limit: int = None, offset: int = None, **kwargs) -> str:
        valid, error, abs_path = self._validate_path(path)
        if not valid:
            return f"Error: {error}"
        if not abs_path.exists():
            return f"Error: File not found: {path}"
        if not abs_path.is_file():
            return f"Error: Not a file: {path}"
        try:
            lines = abs_path.read_text(encoding="utf-8").splitlines()
            if offset:
                lines = lines[offset:]
            if limit:
                lines = lines[:limit]
            return f"File: {path}\nSize: {len(lines)} bytes\n\n" + "\n".join(lines)
        except Exception as e:
            return f"Error reading file: {e}"


class FileWriteTool(WorkspaceTool):
    def __init__(self, workspace_path: str = "./workspace"):
        super().__init__("write_file", "Write content to a file in workspace", workspace_path)
        self._definition = ToolDefinition(
            name=self.name, description=self.description, category=ToolCategory.FILE,
            parameters=[
                ToolParameter("path", "string", "File path relative to workspace", required=True),
                ToolParameter("content", "string", "Content to write", required=True),
                ToolParameter("mode", "string", "Write mode", default="w", enum=["w", "a", "wb", "ab"]),
            ],
            returns="Success message", timeout=30)

    def execute(self, path: str, content: str, mode: str = "w", **kwargs) -> str:
        valid, error, abs_path = self._validate_path(path)
        if not valid:
            return f"Error: {error}"
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            if mode in ["wb", "ab"]:
                abs_path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
            else:
                abs_path.write_text(content, encoding="utf-8")
            return f"Success: Wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


class FileEditTool(WorkspaceTool):
    def __init__(self, workspace_path: str = "./workspace"):
        super().__init__("edit_file", "Edit file by replacing exact text", workspace_path)
        self._definition = ToolDefinition(
            name=self.name, description=self.description, category=ToolCategory.FILE,
            parameters=[
                ToolParameter("path", "string", "File path", required=True),
                ToolParameter("old_text", "string", "Text to find", required=True),
                ToolParameter("new_text", "string", "Text to replace", required=True),
                ToolParameter("replace_all", "boolean", "Replace all", default=False),
            ],
            returns="Edit result", timeout=30)

    def execute(self, path: str, old_text: str, new_text: str, replace_all: bool = False, **kwargs) -> str:
        valid, error, abs_path = self._validate_path(path)
        if not valid or not abs_path.exists():
            return f"Error: File not found"
        try:
            content = abs_path.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: Text not found"
            count = content.count(old_text) if replace_all else 1
            new_content = content.replace(old_text, new_text, 1 if not replace_all else -1)
            abs_path.write_text(new_content, encoding="utf-8")
            return f"Success: Made {count} replacement(s) in {path}"
        except Exception as e:
            return f"Error editing file: {e}"


class BashTool(WorkspaceTool):
    def __init__(self, workspace_path: str = "./workspace"):
        super().__init__("bash", "Run shell command in workspace", workspace_path)
        self._definition = ToolDefinition(
            name=self.name, description=self.description, category=ToolCategory.SYSTEM,
            parameters=[
                ToolParameter("command", "string", "Shell command", required=True),
                ToolParameter("timeout", "integer", "Timeout in seconds", default=60),
            ],
            returns="Command output", timeout=300)

    def _is_dangerous(self, command: str) -> bool:
        dangerous = [r'rm\s+-rf\s+/', r'sudo', r'mkfs', r'chmod\s+777', r'>dev/null.*&', r'wget.*\|.*sh', r'curl.*\|.*sh']
        return any(re.search(p, command, re.IGNORECASE) for p in dangerous)

    def execute(self, command: str, timeout: int = 60, **kwargs) -> str:
        if self._is_dangerous(command):
            return "Error: Dangerous command blocked"
        try:
            result = subprocess.run(command, shell=True, cwd=str(self.workspace_path), capture_output=True, text=True, timeout=timeout)
            output = (result.stdout + result.stderr).strip() or "(no output)"
            return output
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error: {e}"


class ListDirTool(WorkspaceTool):
    def __init__(self, workspace_path: str = "./workspace"):
        super().__init__("list_dir", "List directory contents", workspace_path)
        self._definition = ToolDefinition(
            name=self.name, description=self.description, category=ToolCategory.FILE,
            parameters=[
                ToolParameter("path", "string", "Directory path", default="."),
                ToolParameter("recursive", "boolean", "List recursively", default=False),
            ],
            returns="Directory listing", timeout=10)

    def execute(self, path: str = ".", recursive: bool = False, **kwargs) -> str:
        valid, error, abs_path = self._validate_path(path)
        if not valid or not abs_path.exists():
            return f"Error: Directory not found"
        if not abs_path.is_dir():
            return f"Error: Not a directory"

        def list_recursive(p: Path, prefix: str = ""):
            items = []
            try:
                for item in sorted(p.iterdir()):
                    if item.name.startswith("."):
                        continue
                    marker = "/" if item.is_dir() else ""
                    items.append(f"{prefix}{item.name}{marker}")
                    if item.is_dir() and recursive:
                        items.extend(list_recursive(item, prefix + "  "))
            except PermissionError:
                items.append(f"{prefix}[Permission denied]")
            return items

        lines = list_recursive(abs_path)
        return "\n".join(lines) or "(empty directory)"


class GrepTool(WorkspaceTool):
    def __init__(self, workspace_path: str = "./workspace"):
        super().__init__("grep", "Search for text pattern in files", workspace_path)
        self._definition = ToolDefinition(
            name=self.name, description=self.description, category=ToolCategory.SEARCH,
            parameters=[
                ToolParameter("pattern", "string", "Pattern to search", required=True),
                ToolParameter("path", "string", "Directory to search", default="."),
                ToolParameter("glob", "string", "File glob pattern"),
                ToolParameter("output_mode", "string", "Output mode", default="content", enum=["content", "files_with_matches", "count"]),
                ToolParameter("head_limit", "integer", "Limit results"),
                ToolParameter("-i", "boolean", "Case insensitive", default=False),
            ],
            returns="Search results", timeout=30)

    def execute(self, pattern: str, path: str = ".", glob: str = None, output_mode: str = "content", head_limit: int = None, i: bool = False, **kwargs) -> str:
        valid, error, abs_path = self._validate_path(path)
        if not valid or not abs_path.exists():
            return f"Error: Directory not found"
        try:
            cmd = ["grep", "-r", "-n"]
            if i:
                cmd.append("-i")
            if output_mode == "count":
                cmd.append("-c")
            elif output_mode == "files_with_matches":
                cmd.append("-l")
            if glob:
                cmd.extend(["--include", glob])
            if head_limit:
                cmd.extend(["-m", str(head_limit)])
            cmd.extend([pattern, str(abs_path)])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = (result.stdout + result.stderr).strip()
            return output or f"No matches found for: {pattern}"
        except subprocess.TimeoutExpired:
            return "Error: Search timed out"
        except Exception as e:
            return f"Error during search: {e}"


# ============ Memory 工具（用于持久化存储工具结果）============


class MemoryStore:
    """内存存储，用于工具结果持久化"""

    def __init__(self):
        self._data: Dict[str, str] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    def set(self, key: str, value: str, metadata: Dict[str, Any] = None) -> bool:
        """存储值"""
        self._data[key] = value
        self._metadata[key] = metadata or {}
        self._metadata[key]["timestamp"] = time.time()
        return True

    def get(self, key: str) -> Optional[str]:
        """获取值"""
        return self._data.get(key)

    def delete(self, key: str) -> bool:
        """删除值"""
        if key in self._data:
            del self._data[key]
            if key in self._metadata:
                del self._metadata[key]
            return True
        return False

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索存储的内容"""
        results = []
        query_lower = query.lower()
        for key, value in self._data.items():
            if query_lower in key.lower() or query_lower in value.lower():
                meta = self._metadata.get(key, {})
                results.append({
                    "key": key,
                    "value": value,
                    "timestamp": meta.get("timestamp", 0)
                })
                if len(results) >= limit:
                    break
        return results

    def list_keys(self, limit: int = 100) -> List[str]:
        """列出所有键"""
        return list(self._data.keys())[:limit]

    def clear(self):
        """清空存储"""
        self._data.clear()
        self._metadata.clear()

    def __contains__(self, key: str) -> bool:
        return key in self._data


# 全局内存存储实例
_memory_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store


def reset_memory_store():
    """重置内存存储（用于测试）"""
    global _memory_store
    _memory_store = None


class MemoryTool(WorkspaceTool):
    """持久化存储工具，用于保存和检索工具结果"""

    def __init__(self, workspace_path: str = "./workspace"):
        super().__init__("memory", "Persistently store and retrieve tool results", workspace_path)
        self._definition = ToolDefinition(
            name=self.name, description=self.description, category=ToolCategory.SYSTEM,
            parameters=[
                ToolParameter("action", "string", "Action: get, set, search, delete, list, clear", required=True, enum=["get", "set", "search", "delete", "list", "clear"]),
                ToolParameter("key", "string", "Key for the stored value"),
                ToolParameter("value", "string", "Value to store (for set action)"),
                ToolParameter("query", "string", "Search query (for search action)"),
                ToolParameter("limit", "integer", "Limit results (default: 10)", default=10),
            ],
            returns="Stored/retrieved/searched results", timeout=10)

    def execute(self, action: str, key: str = None, value: str = None, query: str = None, limit: int = 10, **kwargs) -> str:
        # 优先使用Agent传递的memory_store，否则降级到全局存储
        store = kwargs.get("_memory_store") or get_memory_store()

        if action == "set":
            if not key:
                return "Error: key is required for set action"
            store.set(key, value or "")
            return f"Success: Stored '{key}'"

        elif action == "get":
            if not key:
                return "Error: key is required for get action"
            result = store.get(key)
            if result is None:
                return f"Not found: {key}"
            return result

        elif action == "search":
            results = store.search(query or "", limit=limit)
            if not results:
                return f"No results found for: {query}"
            lines = [f"[{r['key']}] (ts: {r['timestamp']:.0f}):\n{r['value'][:500]}" for r in results]
            return "\n---\n".join(lines)

        elif action == "delete":
            if not key:
                return "Error: key is required for delete action"
            if store.delete(key):
                return f"Deleted: {key}"
            return f"Not found: {key}"

        elif action == "list":
            keys = store.list_keys(limit=limit)
            if not keys:
                return "(empty storage)"
            return "\n".join(f"- {k}" for k in keys)

        elif action == "clear":
            store.clear()
            return "Storage cleared"

        else:
            return f"Error: Unknown action: {action}"


class ToolRegistry:
    def __init__(self, workspace_path: str = "./workspace"):
        self._tools: Dict[str, BaseTool] = {}
        self._workspace_path = workspace_path
        self._lock = threading.Lock()
        self._register_defaults()

    def _register_defaults(self):
        defaults = [FileReadTool, FileWriteTool, FileEditTool, BashTool, ListDirTool, GrepTool, MemoryTool]
        for ToolClass in defaults:
            self.register(ToolClass(self._workspace_path))

    def register(self, tool: BaseTool) -> bool:
        with self._lock:
            if tool.name in self._tools:
                return False
            self._tools[tool.name] = tool
            return True

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_definitions_as_dicts(self) -> List[Dict[str, Any]]:
        return [self._to_format(d.get_definition()) for d in self._tools.values()]

    def _to_format(self, d: ToolDefinition) -> Dict:
        props = {p.name: {"type": p.type, "description": p.description} for p in d.parameters}
        required = [p.name for p in d.parameters if p.required]
        return {"type": "function", "function": {"name": d.name, "description": d.description, "parameters": {"type": "object", "properties": props, "required": required}}}

    def execute(self, name: str, **kwargs) -> str:
        """同步执行工具（保持向后兼容）"""
        tool = self.get(name)
        if tool is None:
            get_logger().error(f"[TOOL] Unknown tool: {name}")
            return f"Error: Unknown tool: {name}"
        definition = tool.get_definition()
        timeout = kwargs.pop("timeout", definition.timeout)
        get_logger().info(f"[TOOL] Executing: {name}, args={list(kwargs.keys())}")

        def _execute():
            if tool._is_async():
                # 异步方法需要在新事件循环中执行
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(tool.execute(**kwargs))
                finally:
                    new_loop.close()
            else:
                return tool.execute(**kwargs)

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(_execute).result(timeout=timeout)
            # 截断过长的结果
            truncated = truncate_tool_result(result)
            get_logger().debug(f"[TOOL] Result: {truncated[:200]}..." if len(truncated) > 200 else f"[TOOL] Result: {truncated}")
            return truncated
        except TimeoutError:
            get_logger().error(f"[TOOL] Timeout: {name} exceeded {timeout}s")
            return f"Error: Tool timed out after {timeout}s"
        except Exception as e:
            get_logger().error(f"[TOOL] Error: {name} failed: {e}\n{traceback.format_exc()}")
            return f"Error: Tool execution failed: {e}"

    async def execute_async(self, name: str, **kwargs) -> str:
        """异步执行工具

        Args:
            name: 工具名称
            **kwargs: 工具参数

        Returns:
            str: 工具执行结果
        """
        tool = self.get(name)
        if tool is None:
            get_logger().error(f"[TOOL] Unknown tool: {name}")
            return f"Error: Unknown tool: {name}"

        definition = tool.get_definition()
        timeout = kwargs.pop("timeout", definition.timeout)
        get_logger().info(f"[TOOL] Async executing: {name}, args={list(kwargs.keys())}")

        try:
            if tool._is_async():
                # 异步方法直接await
                result = await asyncio.wait_for(tool.execute(**kwargs), timeout=timeout)
            else:
                # 同步方法在线程池中执行
                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(executor, tool.execute, kwargs),
                        timeout=timeout
                    )
            # 截断过长的结果
            truncated = truncate_tool_result(result)
            get_logger().debug(f"[TOOL] Result: {truncated[:200]}..." if len(truncated) > 200 else f"[TOOL] Result: {truncated}")
            return truncated
        except TimeoutError:
            get_logger().error(f"[TOOL] Timeout: {name} exceeded {timeout}s")
            return f"Error: Tool timed out after {timeout}s"
        except Exception as e:
            get_logger().error(f"[TOOL] Error: {name} failed: {e}\n{traceback.format_exc()}")
            return f"Error: Tool execution failed: {e}"

    def list_tools(self) -> List[Dict[str, Any]]:
        return [{"name": t.name, "description": t.description, "category": t.get_definition().category.value} for t in self._tools.values()]


_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _tool_registry
    if _tool_registry is None:
        from .config import get_config
        _tool_registry = ToolRegistry(get_config().workspace.root_path)
    return _tool_registry


def execute_tool(name: str, **kwargs) -> str:
    get_logger().info(f"[TOOL] Direct call: {name}, kwargs={kwargs}")
    return get_tool_registry().execute(name, **kwargs)


async def execute_tool_async(name: str, **kwargs) -> str:
    """异步执行工具

    Args:
        name: 工具名称
        **kwargs: 工具参数

    Returns:
        str: 工具执行结果
    """
    get_logger().info(f"[TOOL] Direct async call: {name}, kwargs={kwargs}")
    return await get_tool_registry().execute_async(name, **kwargs)


# ============ 工具结果截断配置 ============

# 硬上限字符数
TOOL_RESULT_HARD_LIMIT = 10 * 1024  # 10K 字符

# 默认保留头部和尾部的比例（各50%）
TOOL_RESULT_HEAD_RATIO = 0.5
TOOL_RESULT_TAIL_RATIO = 0.5


def truncate_tool_result(result: str, context_window: int = None, head_ratio: float = TOOL_RESULT_HEAD_RATIO,
                         tail_ratio: float = TOOL_RESULT_TAIL_RATIO, hard_limit: int = TOOL_RESULT_HARD_LIMIT) -> str:
    """截断工具结果

    当结果超过上下文窗口的30%或硬上限(10K字符)时，截断为头部+尾部+标记

    Args:
        result: 原始结果
        context_window: 上下文窗口大小（token数），默认根据硬上限估算（约2500 tokens）
        head_ratio: 头部保留比例
        tail_ratio: 尾部保留比例
        hard_limit: 硬上限字符数

    Returns:
        str: 截断后的结果
    """
    if not result:
        return result

    # 估算上下文窗口的30%
    if context_window is None:
        # 默认假设1 token ≈ 4字符，30%上下文窗口约等于硬上限
        context_limit = hard_limit
    else:
        context_limit = int(context_window * 0.3)

    # 取硬上限和上下文限制的较小值
    max_length = min(hard_limit, context_limit)

    if len(result) <= max_length:
        return result

    # 计算头部和尾部分配
    head_length = int(max_length * head_ratio)
    tail_length = int(max_length * tail_ratio)

    # 确保有足够空间放置标记
    marker = f"\n[... 内容被截断 ({len(result)} 字符) ...]\n"
    marker_length = len(marker)

    if head_length + tail_length + marker_length > max_length:
        # 调整头部和尾部大小
        available = max_length - marker_length
        head_length = int(available * head_ratio)
        tail_length = available - head_length

    head = result[:head_length]
    tail = result[-tail_length:] if tail_length > 0 else ""

    return head + marker + tail


def get_tool_definitions(allowed_tools: List[str] = None) -> List[Dict[str, Any]]:
    """获取工具定义列表

    Args:
        allowed_tools: 可用工具名称列表，如果为 None 则返回所有工具
    """
    registry = get_tool_registry()
    all_tools = registry.get_definitions_as_dicts()

    if allowed_tools is None:
        return all_tools

    # 过滤工具
    return [tool for tool in all_tools if tool.get("function", {}).get("name") in allowed_tools]
