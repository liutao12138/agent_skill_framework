#!/usr/bin/env python3
"""
Agent Framework Events - 事件通知系统
"""

import threading
import time
import json
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from queue import Queue
from datetime import datetime


class EventType(Enum):
    """事件类型枚举"""
    MODEL_START = "model_start"
    MODEL_STOP = "model_stop"
    MODEL_ERROR = "model_error"
    MODEL_STREAM = "model_stream"  # 流式输出 token
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
    type: str
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    session_id: Optional[str] = None
    call_id: Optional[str] = None  # 工具调用ID，用于追踪


class EventEmitter:
    """事件发射器"""

    def __init__(self, max_queue_size: int = 1000):
        self._handlers: List[Callable] = []
        self._lock = threading.Lock()
        self._session_id: Optional[str] = None
        self._queue: Queue = Queue(max_queue_size)

    def set_session_id(self, session_id: str):
        self._session_id = session_id

    def on(self, handler: Callable):
        """注册事件处理器

        Args:
            handler: 事件处理函数
        """
        with self._lock:
            self._handlers.append(handler)

    def off(self, handler: Callable) -> bool:
        """移除事件处理器

        Args:
            handler: 要移除的处理函数

        Returns:
            bool: 是否成功移除
        """
        with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)
                return True
            return False

    def emit(self, event_type, data: Dict[str, Any] = None, source: str = "", call_id: str = None) -> bool:
        """发射事件

        Args:
            event_type: 事件类型，可以是 EventType 枚举或字符串
            data: 事件数据
            source: 事件来源
            call_id: 工具调用ID

        Returns:
            bool: 是否成功发射
        """
        # 将 EventType 枚举转换为字符串
        type_value = event_type.value if hasattr(event_type, 'value') else event_type
        event = Event(type=type_value, data=data or {}, source=source, session_id=self._session_id, call_id=call_id)
        with self._lock:
            try:
                self._queue.put_nowait(event)
            except:
                pass
            self._dispatch(event)
        return True

    def _dispatch(self, event: Event):
        """分发事件到处理器"""
        for handler in self._handlers:
            try:
                handler.handle(event) if hasattr(handler, 'handle') else handler(event)
            except:
                pass
