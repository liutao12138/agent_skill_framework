#!/usr/bin/env python3
"""Agent Framework Model Client - 异步模型调用客户端"""

import json
import time
import httpx
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, AsyncGenerator, Union

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


class AsyncStreamResponse:
    """异步流式响应"""
    def __init__(self, generator: AsyncGenerator[str, None], on_complete: callable = None):
        self._generator = generator
        self._on_complete = on_complete
        self._content = ""
        self._tool_calls = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = await self._generator.__anext__()
            self._content += chunk
            return chunk
        except StopAsyncIteration:
            if self._on_complete:
                self._on_complete()
            raise

    @property
    def content(self):
        return self._content

    @property
    def tool_calls(self):
        return self._tool_calls

    @tool_calls.setter
    def tool_calls(self, value):
        self._tool_calls = value


class BaseModelClient:
    """异步模型客户端基类"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int, retry_times: int, retry_delay: float, **kwargs):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        self.extra_kwargs = kwargs
        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _build_body(self, messages: List[Dict], tools: Optional[List], stream: bool, **kwargs) -> Dict[str, Any]:
        body = {"model": self.model, "messages": messages, "stream": stream}
        for key in ["max_tokens", "temperature", "top_p", "frequency_penalty", "presence_penalty", "stop"]:
            if key in kwargs:
                body[key] = kwargs[key]
        if tools:
            body["tools"] = tools
            body["tool_choice"] = kwargs.get("tool_choice", "auto")
        return body

    def _log_request(self, body: Dict):
        """打印请求体（debug级别）"""
        # 隐藏敏感信息
        log_body = body.copy()
        if "messages" in log_body:
            # 只显示最后一条用户消息的摘要
            for msg in log_body["messages"]:
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if len(content) > 200:
                        msg["content"] = content[:200] + "..."
        logger.debug(f"[MODEL] Request body: {json.dumps(log_body, ensure_ascii=False)}")

    async def _make_request(self, body: Dict, stream: bool) -> httpx.Response:
        url = f"{self.base_url}/chat/completions"
        self._log_request(body)
        for attempt in range(self.retry_times):
            try:
                client = await self._get_client()
                response = await client.post(url, headers=self.headers, json=body)
                response.raise_for_status()
                return response
            except Exception as e:
                import traceback
                error_details = f"{type(e).__name__}: {e}"
                
                # 429错误：使用指数退避
                is_429 = isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429
                if is_429:
                    wait_time = self.retry_delay * (2 ** attempt)  # 指数增长: 1s, 2s, 4s...
                    logger.warning(f"[MODEL] Rate limited (429), waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    if attempt < self.retry_times - 1:
                        continue
                else:
                    logger.warning(f"[MODEL] Request attempt {attempt + 1} failed: {error_details}")
                    if attempt < self.retry_times - 1:
                        time.sleep(self.retry_delay * (attempt + 1))
                
                logger.error(f"[MODEL] Request failed after {self.retry_times} attempts: {error_details}")
                logger.error(f"[MODEL] Full traceback:\n{traceback.format_exc()}")
        raise Exception(f"Request failed after {self.retry_times} attempts")

    def _make_stream_request(self, body: Dict) -> AsyncStreamResponse:
        """发起流式请求并yield内容块"""
        self._log_request(body)
        url = f"{self.base_url}/chat/completions"
        content_parts = []
        tool_calls = []

        async def collect_stream():
            nonlocal content_parts, tool_calls
            for attempt in range(self.retry_times):
                try:
                    client = await self._get_client()
                    async with client.stream("POST", url, headers=self.headers, json=body) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            data = self._parse_chunk(line.encode() if isinstance(line, str) else line)
                            if data:
                                choice = data.get("choices", [{}])[0]
                                delta = choice.get("delta", {})
                                content_delta = delta.get("content", "")
                                if content_delta:
                                    content_parts.append(content_delta)
                                    yield content_delta
                                # 收集tool_calls
                                tc = delta.get("tool_calls")
                                if tc:
                                    tool_calls.extend(tc)
                    break
                except Exception as e:
                    import traceback
                    error_details = f"{type(e).__name__}: {e}"
                    
                    # 429错误：使用指数退避
                    is_429 = isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429
                    if is_429:
                        wait_time = self.retry_delay * (2 ** attempt)
                        logger.warning(f"[MODEL] Stream rate limited (429), waiting {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.warning(f"[MODEL] Stream request attempt {attempt + 1} failed: {error_details}")
                        if attempt < self.retry_times - 1:
                            time.sleep(self.retry_delay * (attempt + 1))
                        else:
                            logger.error(f"[MODEL] Stream request failed: {error_details}")
                            logger.error(f"[MODEL] Full traceback:\n{traceback.format_exc()}")
                            raise Exception(f"Stream request failed after {self.retry_times} attempts")

        def on_complete():
            full_content = "".join(content_parts)
            logger.debug(f"[MODEL] Stream response content:\n{full_content}")
            if tool_calls:
                logger.debug(f"[MODEL] Stream response tool_calls:\n{json.dumps(tool_calls, ensure_ascii=False, indent=2)}")

        response = AsyncStreamResponse(collect_stream(), on_complete)
        response._tool_calls = tool_calls  # 设置收集到的tool_calls
        return response

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

        logger.debug(f"[MODEL] Response content:\n{content}")
        if tool_calls:
            logger.debug(f"[MODEL] Response tool_calls:\n{json.dumps([tc.__dict__ for tc in tool_calls], ensure_ascii=False, indent=2)}")

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

    async def chat(self, messages: List[Dict], tools: Optional[List] = None, stream: bool = False, **kwargs) -> Union[ModelResponse, AsyncGenerator[str, None]]:
        """异步聊天接口"""
        body = self._build_body(messages, tools, stream, **kwargs)
        logger.info(f"[MODEL] Request: model={self.model}, stream={stream}, tools={len(tools) if tools else 0}")

        if not stream:
            resp = await self._make_request(body, stream)
            resp_json = resp.json()
            return self._parse_response(resp_json)

        # 流式响应
        return self._make_stream_request(body)

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
