"""自定义 LLM 客户端模块"""

from typing import Any, Callable, Dict, List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.outputs import ChatGeneration
from langchain_core.messages import BaseMessage


class CustomChatOpenAI(ChatOpenAI):
    """自定义 ChatOpenAI，支持请求/响应转换

    用于本地部署模型或需要自定义请求/响应格式的场景。

    Args:
        request_transformer: 可选 callable，接收原始请求 dict，返回转换后的请求 dict
        response_transformer: 可选 callable，接收原始响应 dict，返回转换后的响应 dict
        **kwargs: ChatOpenAI 其他参数
    """

    def __init__(
        self,
        request_transformer: Callable = None,
        response_transformer: Callable = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._request_transformer = request_transformer
        self._response_transformer = response_transformer

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """Override _generate to transform requests and responses"""
        payload = self._build_message_config(messages, stop, **kwargs)

        if self._request_transformer:
            payload = self._request_transformer(payload)

        response = self._client.create(payload)

        if self._response_transformer:
            response = self._response_transformer(response)

        return self._parse_response(response)

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs
    ) -> ChatGeneration:
        """Override _agenerate to transform requests and responses asynchronously"""
        payload = self._build_message_config(messages, stop, **kwargs)

        if self._request_transformer:
            payload = self._request_transformer(payload)

        response = await self._client.acreate(payload)

        if self._response_transformer:
            response = self._response_transformer(response)

        return self._parse_response(response)

    def _build_message_config(self, messages, stop=None, **kwargs) -> Dict[str, Any]:
        """构建消息配置"""
        message_dicts = self._create_message_dicts(messages)

        payload = {
            "model": self.model_name,
            "messages": message_dicts,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "n": 1,
            "stream": False,
            "stop": stop,
            "max_tokens": self.max_tokens,
        }

        if self.functions:
            payload["functions"] = self.functions
        if self.function_call:
            payload["function_call"] = self.function_call

        payload.update(kwargs)
        payload = {k: v for k, v in payload.items() if v is not None}

        return payload

    def _create_message_dicts(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        """将 BaseMessage 转换为 API 格式"""
        message_dicts = []
        for message in messages:
            msg_dict = {"type": message.type, "content": message.content}
            if hasattr(message, "name"):
                msg_dict["name"] = message.name
            if hasattr(message, "additional_kwargs"):
                for key, value in message.additional_kwargs.items():
                    msg_dict[key] = value
            message_dicts.append(msg_dict)
        return message_dicts

    def _parse_response(self, response: Dict[str, Any]) -> List[ChatGeneration]:
        """解析 API 响应"""
        if "choices" in response:
            choices = response["choices"]
        elif "messages" in response:
            choices = [{"message": {"content": response.get("text", "")}}]
        else:
            content = response.get("content") or response.get("text") or ""
            choices = [{"message": {"content": content}}]

        generations = []
        for choice in choices:
            msg = choice.get("message", {})
            content = msg.get("content", "")
            generations.append(ChatGeneration(
                message=AIMessage(content=content),
                generation_info=dict(choice.get("finish_reason", None))
            ))

        return generations
