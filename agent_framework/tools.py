#!/usr/bin/env python3
"""Agent Framework Tools - 工具系统

使用 langchain 的 @tool 装饰器创建工具
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

from langchain_core.tools import tool

from .config import get_config

logger = logging.getLogger("agent_framework")


# ============ 辅助函数 ============


def _get_workspace(workspace_path: str = None) -> Path:
    """获取工作空间路径"""
    if workspace_path is None:
        workspace_path = get_config().workspace.root_path
    return Path(workspace_path).resolve()


def _validate_path(path: str, workspace: Path) -> tuple[bool, str, Path]:
    """验证路径是否在工作空间内"""
    try:
        path_obj = Path(path)
        abs_path = (workspace / path_obj).resolve() if not path_obj.is_absolute() else path_obj.resolve()

        forbidden = ["/etc", "/root", "/home", "C:\\Windows", "C:\\Users\\Admin\\Desktop", "/proc", "/sys", "/dev"]
        if any(str(abs_path).startswith(p) for p in forbidden):
            return False, f"Path is forbidden: {path}", abs_path

        if not abs_path.is_relative_to(workspace):
            return False, f"Path escapes workspace: {path}", abs_path

        return True, "", abs_path
    except Exception as e:
        return False, f"Invalid path: {e}", Path(path)


def _is_dangerous(command: str) -> bool:
    """检查命令是否危险"""
    dangerous = [r'rm\s+-rf\s+/', r'sudo', r'mkfs', r'chmod\s+777', r'>dev/null.*&', r'wget.*\|.*sh', r'curl.*\|.*sh']
    return any(re.search(p, command, re.IGNORECASE) for p in dangerous)


# ============ 工具定义 ============


@tool
def read_file(path: str, limit: int = None, offset: int = None) -> str:
    """Read file contents from workspace.
    
    Args:
        path: File path relative to workspace (required)
        limit: Maximum number of lines to read (optional)
        offset: Line offset to start reading from (optional)
    """
    workspace = _get_workspace()
    valid, error, abs_path = _validate_path(path, workspace)
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


@tool
def write_file(path: str, content: str, mode: str = "w") -> str:
    """Write content to a file in workspace.
    
    Args:
        path: File path relative to workspace (required)
        content: Content to write (required)
        mode: Write mode - "w" (write), "a" (append) (optional, default "w")
    """
    workspace = _get_workspace()
    valid, error, abs_path = _validate_path(path, workspace)
    if not valid:
        return f"Error: {error}"

    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        return f"Success: Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """Edit file by replacing exact text.
    
    Args:
        path: File path (required)
        old_text: Text to find and replace (required)
        new_text: Text to replace with (required)
        replace_all: Replace all occurrences (optional, default False)
    """
    workspace = _get_workspace()
    valid, error, abs_path = _validate_path(path, workspace)
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


@tool
def bash(command: str, timeout: int = 60) -> str:
    """Run shell command in workspace.
    
    Args:
        command: Shell command to execute (required)
        timeout: Timeout in seconds (optional, default 60)
    """
    workspace = _get_workspace()
    if _is_dangerous(command):
        return "Error: Dangerous command blocked"
    try:
        result = subprocess.run(command, shell=True, cwd=str(workspace), capture_output=True, text=True, timeout=timeout)
        output = (result.stdout + result.stderr).strip() or "(no output)"
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


@tool
def list_dir(path: str = ".", recursive: bool = False) -> str:
    """List directory contents.
    
    Args:
        path: Directory path (optional, default ".")
        recursive: List recursively (optional, default False)
    """
    workspace = _get_workspace()
    valid, error, abs_path = _validate_path(path, workspace)
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


@tool
def grep(pattern: str, path: str = ".", glob: str = None, output_mode: str = "content", head_limit: int = None, i: bool = False) -> str:
    """Search for text pattern in files.
    
    Args:
        pattern: Pattern to search for (required)
        path: Directory to search in (optional, default ".")
        glob: File glob pattern (optional)
        output_mode: Output mode - "content", "files_with_matches", "count" (optional, default "content")
        head_limit: Maximum number of results (optional)
        i: Case insensitive search (optional, default False)
    """
    workspace = _get_workspace()
    valid, error, abs_path = _validate_path(path, workspace)
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


# ============ Memory 存储 ============


class MemoryStore:
    """内存存储，用于工具结果持久化"""

    def __init__(self):
        self._data: Dict[str, str] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    def set(self, key: str, value: str, metadata: Dict[str, Any] = None) -> bool:
        self._data[key] = value
        self._metadata[key] = metadata or {}
        self._metadata[key]["timestamp"] = time.time()
        return True

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            if key in self._metadata:
                del self._metadata[key]
            return True
        return False

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
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
        return list(self._data.keys())[:limit]

    def clear(self):
        self._data.clear()
        self._metadata.clear()


_memory_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store


def reset_memory_store():
    global _memory_store
    _memory_store = None


@tool
def memory(action: str, key: str = None, value: str = None, query: str = None, limit: int = 10) -> str:
    """Persistently store and retrieve tool results.
    
    Args:
        action: Action to perform - "get", "set", "search", "delete", "list", "clear" (required)
        key: Key for the stored value (required for get/set/delete actions)
        value: Value to store (required for set action)
        query: Search query (required for search action)
        limit: Maximum number of results (optional, default 10)
    """
    store = get_memory_store()

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


# ============ 默认工具列表 ============


DEFAULT_TOOLS = [
    read_file,
    write_file,
    edit_file,
    bash,
    list_dir,
    grep,
    memory
]


def get_all_tools(workspace_path: str = None) -> List:
    """获取所有默认工具

    Args:
        workspace_path: 工作空间路径（可选）

    Returns:
        List[BaseTool]: 工具列表
    """
    return DEFAULT_TOOLS
