#!/usr/bin/env python3
"""Agent Framework Tools - 工具系统"""

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, TimeoutError


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
    def execute(self, **kwargs) -> str:
        pass

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


class ToolRegistry:
    def __init__(self, workspace_path: str = "./workspace"):
        self._tools: Dict[str, BaseTool] = {}
        self._workspace_path = workspace_path
        self._lock = __import__('threading').Lock()
        self._register_defaults()

    def _register_defaults(self):
        defaults = [FileReadTool, FileWriteTool, FileEditTool, BashTool, ListDirTool, GrepTool]
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
        tool = self.get(name)
        if tool is None:
            return f"Error: Unknown tool: {name}"
        definition = tool.get_definition()
        timeout = kwargs.pop("timeout", definition.timeout)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(tool.execute, **kwargs).result(timeout=timeout)
        except TimeoutError:
            return f"Error: Tool timed out after {timeout}s"
        except Exception as e:
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
    return get_tool_registry().execute(name, **kwargs)


def get_tool_definitions() -> List[Dict[str, Any]]:
    return get_tool_registry().get_definitions_as_dicts()
