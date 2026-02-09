#!/usr/bin/env python3
"""
Agent Framework __main__ module

运行方式:
    python -m agent_framework
    python -m agent_framework --config config.yaml
    python -m agent_framework --message "Hello"
    python -m agent_framework --session "my-session-123"
"""

import asyncio
import sys
import os
import uuid

# 确保 agent_framework 在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent


def parse_args():
    """解析命令行参数"""
    import argparse
    parser = argparse.ArgumentParser(description="Agent Framework CLI")
    parser.add_argument("--config", "-c", type=str, default=None, help="配置文件路径")
    parser.add_argument("--message", "-m", type=str, default=None, help="输入消息")
    parser.add_argument("--session", "-s", type=str, default=None, help="会话ID (session_id)")
    return parser.parse_args()


async def run_cli():
    """运行命令行交互"""
    args = parse_args()

    # 使用提供的 session_id 或自动生成
    session_id = args.session or str(uuid.uuid4())[:8]

    print("=" * 60)
    print("  Agent Framework CLI")
    print(f"  Session ID: {session_id}")
    print("=" * 60)

    agent = create_agent(config_path=args.config)

    if args.message:
        # 单次消息模式
        response = await agent.chat(args.message, session_id=session_id)
        print(f"\n[RESULT] Success: {response['success']}")
        print(f"[RESULT] Content:\n{response.get('content', '')}")
    else:
        # 交互模式
        print("\n输入消息与 Agent 对话，输入 'quit' 或 'exit' 退出")
        print("-" * 60)

        while True:
            try:
                message = input(f"\n[{session_id}][USER] ").strip()
                if message.lower() in ['quit', 'exit', 'q', '退出']:
                    print("再见！")
                    break
                if not message:
                    continue

                response = await agent.chat(message, session_id=session_id)
                print(f"\n[{session_id}][AGENT] {response.get('content', '')}")

            except KeyboardInterrupt:
                print("\n再见！")
                break
            except Exception as e:
                print(f"\n[ERROR] {e}")


if __name__ == "__main__":
    asyncio.run(run_cli())
