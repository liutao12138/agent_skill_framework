#!/usr/bin/env python3
"""Agent Framework - 简单示例（基于 LangChain Agent）"""

import sys
import os
import asyncio
import logging

# 设置 UTF-8 输出
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent
from agent_framework.events import EventEmitter, EventType

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')


class EventLogger:
    """事件日志记录器"""

    def __init__(self):
        self.stream_content = ""  # 用于累积流式输出

    def handle(self, event):
        """处理事件"""
        event_type = event.type
        data = event.data
        timestamp = event.timestamp

        # 格式化时间
        from datetime import datetime
        time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]

        # 处理流式 token 事件 - 每个 token 都会触发
        if event_type == EventType.MODEL_STREAM.value:
            content = data.get('content', '')
            if content:
                self.stream_content += content
                print(f"[{time_str}] 🔤 [STREAM] Token: '{content}'", flush=True)
            return

        # 根据事件类型打印不同颜色的信息
        if event_type == EventType.MODEL_START.value:
            print(f"\n[{time_str}] 🔵 [EVENT] 模型开始处理")
            print(f"         Message: {data.get('message', '')[:50]}...")
        elif event_type == EventType.MODEL_STOP.value:
            print(f"\n[{time_str}] 🟢 [EVENT] 模型处理完成")
            print(f"         完整输出长度: {len(self.stream_content)} 字符")
            self.stream_content = ""  # 重置
        elif event_type == EventType.THINKING_START.value:
            print(f"\n[{time_str}] 💭 [EVENT] 开始思考")
        elif event_type == EventType.THINKING_CONTENT.value:
            content = data.get('content', '')
            if content:
                print(f"[{time_str}] 💭 思考内容: {content[:100]}...")
        elif event_type == EventType.THINKING_STOP.value:
            print(f"[{time_str}] 💭 [EVENT] 思考结束")
        elif event_type == EventType.TOOL_CALL_START.value:
            print(f"\n[{time_str}] 🔧 [EVENT] 开始调用工具: {data.get('name', '')}")
            print(f"         参数: {data.get('args', {})}")
        elif event_type == EventType.TOOL_CALL_STOP.value:
            print(f"[{time_str}] 🔧 [EVENT] 工具调用完成: {data.get('name', '')}")
        elif event_type == EventType.TOOL_RESULT.value:
            result = data.get('content', '')
            print(f"[{time_str}] 📤 [EVENT] 工具返回结果: {result[:100]}...")
        elif event_type == EventType.SESSION_START.value:
            print(f"\n[{time_str}] 📡 [EVENT] 会话开始: {data.get('session_id', '')}")
        elif event_type == EventType.SESSION_STOP.value:
            print(f"[{time_str}] 📡 [EVENT] 会话结束: {data.get('session_id', '')}")
        elif event_type == EventType.USER_MESSAGE.value:
            print(f"[{time_str}] 💬 [EVENT] 用户消息: {data.get('message', '')[:50]}...")
        elif event_type == EventType.ERROR.value:
            print(f"\n[{time_str}] ❌ [EVENT] 错误: {data.get('error', '')}")
        else:
            # 其他事件
            print(f"[{time_str}] 📋 [EVENT] {event_type}: {data}")


async def main():
    """基础聊天示例"""
    # 创建事件发射器
    events = EventEmitter()

    # 注册事件处理器
    event_logger = EventLogger()
    events.on(event_logger)

    # 打印调试信息：确认 handler 已注册
    print(f"\n=== DEBUG: 已注册的事件处理器数量: {len(events._handlers)} ===")

    # 创建 Agent，传入事件发射器
    agent = create_agent(events=events)

    # 打印调试信息：确认 Agent 使用的是同一个 events
    print(f"=== DEBUG: Agent events 处理器数量: {len(agent.events._handlers)} ===")

    # 简单对话 - 使用一个需要调用工具的请求
    user_msg = "请列出当前目录的文件"

    print(f"\n{'='*60}")
    print(f"[USER] {user_msg}")
    print(f"{'='*60}")
    print("[MODEL] ", end="", flush=True)

    response = await agent.chat(user_msg)

    print(f"\n\n{'='*60}")
    print(f"[SUCCESS] {response['success']}")
    print(f"[CONTENT]\n{response.get('content', '')}")

    # 如果启用了深度思考，显示思考过程
    if response.get('think'):
        print(f"\n[THINKING]\n{response['think']}")

    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
