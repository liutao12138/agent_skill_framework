#!/usr/bin/env python3
"""Agent Framework Model Client - 模型调用客户端"""

import json
import time
import requests
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Union

from agent_framework.logger import get_logger


logger = get_logger()

class StopReason(Enum):
    """停止原因"""
    STOP = "stop"
    TOOL_USE = "tool_use"
    LENGTH = "length"
    ERROR = "error"


@dataclass
class Message:
    """消息"""
    role: str
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    type: str
    function: Dict[str, str]


@dataclass
class UsageInfo:
    """使用信息"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ModelResponse:
    """模型响应"""
    content: str
    stop_reason: StopReason
    tool_calls: Optional[List[ToolCall]] = None
    usage: Optional[UsageInfo] = None
    raw_response: Optional[Dict[str, Any]] = None


class StreamCallback:
    """流式响应回调"""
    def __init__(self):
        self._callbacks = {"on_start": [], "on_content": [], "on_tool_call": [], "on_stop": [], "on_error": []}

    def on_start(self, func):
        self._callbacks["on_start"].append(func)
        return func

    def on_content(self, func):
        self._callbacks["on_content"].append(func)
        return func

    def on_tool_call(self, func):
        self._callbacks["on_tool_call"].append(func)
        return func

    def on_stop(self, func):
        self._callbacks["on_stop"].append(func)
        return func

    def on_error(self, func):
        self._callbacks["on_error"].append(func)
        return func

    def _trigger(self, event: str, *args, **kwargs):
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except:
                pass


class StreamResponse:
    """流式响应包装器"""
    def __init__(self):
        self._content = ""
        self._tool_calls = []
        self._generator = None

    def __iter__(self):
        return iter(self._generator)

    @property
    def content(self):
        return self._content

    @property
    def tool_calls(self):
        return self._tool_calls

    def add_tool_calls(self, tool_calls):
        self._tool_calls.extend(tool_calls)

    def _build_generator(self, response, callback, parse_chunk_func):
        for line in response.iter_lines():
            chunk = parse_chunk_func(line)
            if chunk:
                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                content = delta.get("content", "")
                if content:
                    self._content += content
                    if callback:
                        callback._trigger("on_content", content)
                    yield content
                tool_calls_data = delta.get("tool_calls")
                if tool_calls_data:
                    self.add_tool_calls(tool_calls_data)
                    if callback:
                        callback._trigger("on_tool_call", tool_calls_data)
        if callback:
            callback._trigger("on_stop")


class BaseModelClient:
    """模型客户端基类"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int, retry_times: int, retry_delay: float, **kwargs):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        self.extra_kwargs = kwargs
        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    def _build_body(self, messages: List[Dict], tools: Optional[List], stream: bool, **kwargs) -> Dict[str, Any]:
        body = {"model": self.model, "messages": messages, "stream": stream}
        for key in ["max_tokens", "temperature", "top_p", "frequency_penalty", "presence_penalty", "stop"]:
            if key in kwargs:
                body[key] = kwargs[key]
        if tools:
            body["tools"] = tools
            body["tool_choice"] = kwargs.get("tool_choice", "auto")
        if "mindie_options" in self.extra_kwargs:
            body.update(self.extra_kwargs["mindie_options"])
        return body

    def _make_request(self, body: Dict, stream: bool) -> requests.Response:
        url = f"{self.base_url}/chat/completions"
        for attempt in range(self.retry_times):
            try:
                response = requests.post(url, headers=self.headers, json=body, stream=stream, timeout=self.timeout)
                response.raise_for_status()
                return response
            except Exception as e:
                if attempt < self.retry_times - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error(f"Request failed after {self.retry_times} attempts: {e}")
        raise Exception(f"Request failed after {self.retry_times} attempts")

    def _parse_response(self, response: Dict) -> ModelResponse:
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "") or ""
        stop_reason = choice.get("finish_reason", "stop")
        try:
            stop_reason = StopReason(stop_reason)
        except ValueError:
            stop_reason = StopReason.STOP

        tool_calls = [ToolCall(id=tc.get("id", ""), type=tc.get("type", "function"), function=tc.get("function", {}))
                      for tc in message.get("tool_calls", [])]

        usage = response.get("usage", {})
        usage_info = UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0)
        )

        return ModelResponse(content=content, stop_reason=stop_reason, tool_calls=tool_calls or None, usage=usage_info, raw_response=response)

    def _parse_chunk(self, chunk: bytes) -> Optional[Dict[str, Any]]:
        try:
            line = chunk.decode("utf-8").strip()
            if not line:
                return None
            line = line[6:] if line.startswith("data: ") else line
            
            if not line or line == "[DONE]":
                return None
            return json.loads(line)
        except:
            return None

    def chat(self, messages: List[Dict], tools: Optional[List] = None, stream: bool = False, callback: Optional[StreamCallback] = None, **kwargs) -> Union[ModelResponse, Generator[str, None, None]]:
        body = self._build_body(messages, tools, stream, **kwargs)
        response = self._make_request(body, stream)

        if not stream:
            return self._parse_response(response.json())

        stream_response = StreamResponse()
        stream_response._generator = stream_response._build_generator(response, callback, self._parse_chunk)
        return stream_response

    def get_model_info(self) -> Dict[str, Any]:
        return {"model": self.model, "base_url": self.base_url}


class OpenAIClient(BaseModelClient):
    """OpenAI 兼容客户端"""
    pass


class MindieClient(BaseModelClient):
    """MindIE 客户端"""
    def get_model_info(self) -> Dict[str, Any]:
        return {"model": self.model, "provider": "mindie", "base_url": self.base_url}


# 工厂函数
def create_client(base_url: str = None, api_key: str = None, model: str = None, provider: str = "openai") -> BaseModelClient:
    from .config import get_config
    config = get_config()
    mc = config.model
    Client = MindieClient if provider == "mindie" else OpenAIClient
    return Client(
        base_url=base_url or mc.base_url,
        api_key=api_key or mc.api_key,
        model=model or mc.model,
        timeout=mc.timeout,
        retry_times=mc.retry_times,
        retry_delay=mc.retry_delay
    )

# ModelClient 是 BaseModelClient 的别名（保持向后兼容）
ModelClient = BaseModelClient
