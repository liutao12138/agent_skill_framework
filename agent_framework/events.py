#!/usr/bin/env python3
"""
Agent Framework Events - 事件通知系统
"""

import json
import threading
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from queue import Queue, Empty
from datetime import datetime


class EventType(Enum):
    """事件类型"""
    MODEL_START = "model_start"
    MODEL_STOP = "model_stop"
    MODEL_ERROR = "model_error"
    THINKING_START = "thinking_start"
    THINKING_CONTENT = "thinking_content"
    THINKING_STOP = "thinking_stop"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_STOP = "tool_call_stop"
    TOOL_CALL_ERROR = "tool_call_error"
    TOOL_RESULT = "tool_result"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_STOP = "subagent_stop"
    SUBAGENT_ERROR = "subagent_error"
    SKILL_LOAD = "skill_load"
    SKILL_LOADED = "skill_loaded"
    SESSION_START = "session_start"
    SESSION_STOP = "session_stop"
    SESSION_UPDATE = "session_update"
    PROGRESS = "progress"
    TODO_UPDATE = "todo_update"
    ERROR = "error"
    WARNING = "warning"
    USER_MESSAGE = "user_message"


@dataclass
class Event:
    """事件"""
    type: EventType
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    session_id: Optional[str] = None
    message_id: Optional[str] = None


class ConsoleEventHandler:
    """控制台事件处理器"""

    def __init__(self, show_timestamps: bool = True):
        self.show_timestamps = show_timestamps

    def handle(self, event: Event):
        ts = f"[{datetime.fromtimestamp(event.timestamp).strftime('%H:%M:%S')}]" if self.show_timestamps else ""
        data = event.data

        handlers = {
            EventType.THINKING_CONTENT: lambda: print(f"{ts} {data.get('content', '')}", end="", flush=True),
            EventType.TOOL_CALL_START: lambda: print(f"{ts} 🔧 调用工具: {data.get('tool_name')}\n{ts}   参数: {json.dumps(data.get('input', {}), indent=2)}"),
            EventType.TOOL_CALL_STOP: lambda: print(f"{ts} ✅ 工具完成: {data.get('tool_name')} ({data.get('duration', 0):.2f}s)"),
            EventType.TOOL_RESULT: lambda: print(f"{ts} 📋 工具结果: {data.get('tool_name')}"),
            EventType.SUBAGENT_START: lambda: print(f"{ts} 🤖 启动子Agent: {data.get('name')}"),
            EventType.SUBAGENT_STOP: lambda: print(f"{ts} ✅ 子Agent完成: {data.get('name')} ({data.get('duration', 0):.2f}s)"),
            EventType.SKILL_LOADED: lambda: print(f"{ts} 📚 加载技能: {data.get('skill_name')}"),
            EventType.ERROR: lambda: print(f"{ts} ❌ 错误: {data.get('error')}"),
            EventType.WARNING: lambda: print(f"{ts} ⚠️  警告: {data.get('warning')}"),
            EventType.PROGRESS: lambda: print(f"{ts} 📊 进度: {data.get('current', 0)}/{data.get('total', 0)} - {data.get('message', '')}"),
        }

        handler = handlers.get(event.type)
        if handler:
            handler()
        else:
            print(f"{ts} [{event.type.value}] {event.data}")


class EventEmitter:
    """事件发射器"""

    def __init__(self, max_queue_size: int = 1000):
        self._handlers: List[Callable] = []
        self._callbacks: List[Callable] = []
        self._lock = threading.Lock()
        self._session_id: Optional[str] = None
        self._queue: Queue = Queue(max_queue_size)

    def set_session_id(self, session_id: str):
        self._session_id = session_id

    def emit(self, event_type: EventType, data: Dict[str, Any] = None, source: str = "") -> bool:
        event = Event(type=event_type, data=data or {}, source=source, session_id=self._session_id)
        with self._lock:
            try:
                self._queue.put_nowait(event)
            except:
                pass
            self._dispatch(event)
        return True

    def _dispatch(self, event: Event):
        for handler in self._handlers:
            try:
                handler.handle(event) if hasattr(handler, 'handle') else handler(event)
            except:
                pass

    def add_handler(self, handler):
        with self._lock:
            self._handlers.append(handler)

    def remove_handler(self, handler) -> bool:
        with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)
                return True
            return False

    def add_callback(self, callback: Callable, event_types: List[EventType] = None):
        with self._lock:
            self._callbacks.append((callback, event_types or []))

    # 便捷方法
    def emit_thinking(self, content: str, incremental: bool = False):
        self.emit(EventType.THINKING_CONTENT, {"content": content, "incremental": incremental})

    def emit_tool_call(self, tool_name: str, tool_input: Dict[str, Any] = None):
        self.emit(EventType.TOOL_CALL_START, {"tool_name": tool_name, "input": tool_input or {}})

    def emit_tool_result(self, tool_name: str, result: str, success: bool = True, duration: float = 0):
        self.emit(EventType.TOOL_RESULT, {"tool_name": tool_name, "result": result, "success": success, "duration": duration})

    def emit_subagent_start(self, name: str, task: str):
        self.emit(EventType.SUBAGENT_START, {"name": name, "task": task})

    def emit_skill_loaded(self, skill_name: str):
        self.emit(EventType.SKILL_LOADED, {"skill_name": skill_name})

    def emit_error(self, error: str):
        self.emit(EventType.ERROR, {"error": error})


_event_emitter: Optional[EventEmitter] = None


def get_event_emitter() -> EventEmitter:
    global _event_emitter
    if _event_emitter is None:
        from .config import get_config
        config = get_config()
        _event_emitter = EventEmitter(config.event_queue_size if hasattr(config, 'event_queue_size') else 1000)
        _event_emitter.add_handler(ConsoleEventHandler())
    return _event_emitter


def emit_event(event_type: EventType, data: Dict[str, Any] = None) -> bool:
    return get_event_emitter().emit(event_type, data)
