"""回调处理器模块"""

from langchain_core.callbacks import BaseCallbackHandler
from .events import EventEmitter, EventType


class StreamCallbackHandler(BaseCallbackHandler):
    """流式输出回调处理器"""

    def __init__(self, events: EventEmitter = None, session_id: str = None):
        super().__init__()
        self.events = events
        self.session_id = session_id
        self.content = ""
        self.reasoning_content = ""

    def on_llm_new_token(self, token: str, **kwargs):
        """LLM 生成新 token 时调用"""
        if self.events:
            self.events.emit(
                EventType.MODEL_STREAM,
                {"content": token, "session_id": self.session_id}
            )
        self.content += token

    def on_llm_end(self, response, **kwargs):
        """LLM 结束生成时调用"""
        pass

    def on_llm_error(self, error, **kwargs):
        """LLM 错误时调用"""
        if self.events:
            self.events.emit(EventType.MODEL_ERROR, {"error": str(error), "session_id": self.session_id})
