#!/usr/bin/env python3
"""Agent Framework - 基类模块"""

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_framework.events import EventType


def _resolve_path(path: str) -> str:
    """解析为绝对路径"""
    p = Path(path)
    return str(p.absolute() if not p.is_absolute() else p)


class BaseAgent:
    """Agent 基类 - 包含通用功能"""

    # 默认的系统提示词模板（可外部覆盖）
    DEFAULT_CAPABILITIES = [
        ("Core Capabilities", [
            "- **Search & Research**: Use search tools to find information",
            "- **Summarize & Synthesize**: Combine multiple results",
            "- **File Operations**: Read, write, and edit files as needed",
            "- **Shell Commands**: Execute bash commands when required"
        ]),
        ("Tool Result Reference & Variable Substitution", [
            "- **Natural Language**: Describe what you need (e.g., 'path from last grep')",
            "- **Direct Reference**: Use `${tool_result.N}` (0-indexed)",
            "- **Last Result**: Use `${tool_result.last}`",
            "- **Memory Storage**: Use `memory` tool and `${memory.KEY}`"
        ]),
        ("Response Guidelines", [
            "- Search first before answering",
            "- Synthesize multiple sources",
            "- Use tools immediately when task matches",
            "- Prefer concrete actions over lengthy explanations"
        ])
    ]

    def __init__(self, workspace_path: str):
        self.workspace_path = _resolve_path(workspace_path)
        self._message_history: List[Dict[str, Any]] = []
        self._last_request_time = 0
        self._tool_results: List[Dict[str, Any]] = []

    def _get_capability_sections(self) -> List[tuple]:
        """获取系统提示词能力章节（子类可覆盖）"""
        return self.DEFAULT_CAPABILITIES

    def _build_system_prompt_base(self, name: str, description: str,
                                   skills_desc: str = "",
                                   tools_desc: str = "",
                                   custom_sections: List[tuple] = None) -> str:
        """构建系统提示词基础框架

        Args:
            name: Agent名称
            description: Agent描述
            skills_desc: Skills描述（可选）
            tools_desc: 可用工具描述（可选）
            custom_sections: 自定义章节列表 [(标题, [行列表]), ...]（可选）
        """
        parts = [f"You are {name}, {description}", f"Working directory: {self.workspace_path}"]

        if skills_desc:
            parts.append(f"\n**Skills:**\n{skills_desc}")

        if tools_desc:
            parts.append(f"\n**Available Tools:**\n{tools_desc}")

        # 添加能力章节
        sections = custom_sections or self._get_capability_sections()
        for title, lines in sections:
            parts.append(f"\n**{title}:**")
            parts.extend(lines)

        return "\n".join(parts)

    def _parse_tool_call(self, tool_call) -> Dict[str, Any]:
        """解析工具调用对象，返回统一格式的字典"""
        if hasattr(tool_call, 'function'):
            func = tool_call.function
            return {
                "id": tool_call.id,
                "name": func.get("name", "") if isinstance(func, dict) else func.name,
                "arguments": func.get("arguments", "") if isinstance(func, dict) else func.arguments,
            }
        else:
            func = tool_call.get("function", {})
            return {
                "id": tool_call.get("id", ""),
                "name": func.get("name", ""),
                "arguments": func.get("arguments", ""),
            }

    def _is_subagent_call(self, tool_call: Dict[str, Any]) -> bool:
        """检查是否是子Agent调用"""
        return tool_call.get("name", "").startswith("subagent_")

    def _parse_tool_args(self, args_str: str) -> Dict[str, Any]:
        """解析工具参数JSON字符串"""
        try:
            return json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            return {"raw": args_str}

    def _apply_rate_limit(self, rate_limit_delay: float):
        """应用请求限流"""
        elapsed = time.time() - self._last_request_time
        if elapsed < rate_limit_delay:
            time.sleep(rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    async def _collect_response(self, response, stream: bool, emit_stop_event: bool = True):
        """收集模型响应内容"""
        if stream:
            content = ""
            async for chunk in response:
                content += chunk
                if hasattr(self, 'events'):
                    self.events.emit_model_stream(chunk)
            tool_calls = response.tool_calls or []
            if emit_stop_event and hasattr(self, 'events'):
                self.events.emit(EventType.MODEL_STOP, {"iteration": None, "session_id": None})
        else:
            content = response.content
            tool_calls = response.tool_calls or []
        return content, tool_calls

    def _format_tool_calls(self, tool_calls: List) -> List[Dict[str, Any]]:
        """格式化工具调用为可序列化格式"""
        return [
            {
                "id": tc.get("id", ""),
                "type": tc.get("type", ""),
                "function": {
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", "")
                }
            }
            for tc in tool_calls
        ]

    def _should_stop(self, response, stream: bool, tool_calls: List) -> bool:
        """判断是否应该停止循环"""
        if stream:
            return not tool_calls
        from .model_client import StopReason
        return response.stop_reason == StopReason.STOP

    def _prune_messages(self, messages: List[Dict[str, Any]], max_msgs: int) -> List[Dict[str, Any]]:
        """滑动窗口：保留system消息和最近N条消息"""
        if len(messages) <= max_msgs:
            return messages

        system_msg = messages[0] if messages[0].get("role") == "system" else None
        recent = messages[-max_msgs:]
        result = [system_msg] + recent if system_msg else recent
        return result

    def _find_tool_result_by_description(self, description: str) -> Optional[str]:
        """根据自然语言描述查找工具结果"""
        if not self._tool_results:
            return None

        description_lower = description.lower()

        for result in reversed(self._tool_results):
            tool_name = result.get("tool_name", "").lower()

            if tool_name in description_lower or "上一次" in description:
                output = result.get("output", "")
                if "\n" in output:
                    paths = [
                        line.split(":")[0] for line in output.strip().split("\n")
                        if ":" in line and line.split(":")[0] and not line.split(":")[0].startswith("Error")
                    ]
                    if paths:
                        return "\n".join(paths[:5])
                return output

        return None

    def _resolve_placeholders(self, args: Dict[str, Any], memory_store=None) -> Dict[str, Any]:
        """解析参数中的占位符"""
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
                    value = value.replace(tool_match.group(0), self._tool_results[index].get("output", ""))

            # 2. ${tool_result.last}
            if "${tool_result.last}" in value and self._tool_results:
                value = value.replace("${tool_result.last}", self._tool_results[-1].get("output", ""))

            # 3. ${memory.KEY}
            if memory_store:
                memory_match = re.search(r'\$\{memory\.([^}]+)\}', value)
                if memory_match:
                    mem_key = memory_match.group(1)
                    mem_value = memory_store.get(mem_key)
                    if mem_value is not None:
                        value = value.replace(memory_match.group(0), mem_value)

            # 4. ${natural.QUERY}
            natural_match = re.search(r'\$\{natural\.([^}]+)\}', value)
            if natural_match:
                query = natural_match.group(1)
                resolved_value = self._find_tool_result_by_description(query)
                if resolved_value is not None:
                    value = value.replace(natural_match.group(0), resolved_value)

            resolved[key] = value

        return resolved
