#!/usr/bin/env python3
"""Agent Framework - 简单示例"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent


def main():
    """基础聊天示例"""
    # 创建 Agent
    agent = create_agent()

    # 发送消息
    response = agent.chat("你好，请简单介绍一下你自己？")
    content = response.get('content', '')
    print(f"\nReply: {content}")


if __name__ == "__main__":
    main()
