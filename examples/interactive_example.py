#!/usr/bin/env python3
"""Agent Framework - 交互式对话示例
支持用户输入，输出提示词和模型响应
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import create_agent


def print_separator(title: str = ""):
    print("\n" + "=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)


def main():
    """交互式对话示例"""
    print_separator("Agent Framework 交互式对话")

    # 创建 Agent
    agent = create_agent()

    # 获取并显示系统提示词
    system_prompt = agent._build_system_prompt()
    print_separator("系统提示词 (System Prompt)")
    print(system_prompt)

    # 显示 Agent 统计信息
    print_separator("Agent 统计信息")
    stats = agent.get_statistics()
    print(f"技能数量: {stats['skills']['total_skills']}")
    print(f"工具数量: {stats['tools']['count']}")
    print(f"工具列表: {[t['name'] for t in stats['tools']['tools']]}")

    print_separator("开始对话")
    print("输入您的问题 (输入 'quit' 或 'exit' 退出):\n")

    while True:
        try:
            # 用户输入
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\n感谢使用，再见！")
                break

            # 显示用户消息
            print_separator("用户消息 (User Message)")
            print(user_input)

            # 发送消息并计时
            import time
            start_time = time.time()

            # 执行对话（关闭流式以便显示完整响应）
            response = agent.chat(user_input, stream=False)

            duration = time.time() - start_time

            # 显示模型响应
            print_separator("模型响应 (Model Response)")
            content = response.get('content', '')
            print(content)

            # 显示工具调用
            if response.get('tool_calls'):
                print_separator("工具调用 (Tool Calls)")
                for tool in response['tool_calls']:
                    print(f"  - {tool}")

            # 显示迭代次数和耗时
            print(f"\n迭代次数: {response.get('iterations', 1)}")
            print(f"耗时: {duration:.2f}秒")
            print(f"成功: {'是' if response.get('success') else '否'}")

            if response.get('error'):
                print(f"错误: {response['error']}")

            # 显示消息历史
            print_separator("消息历史 (Message History)")
            history = agent.get_message_history()
            for i, msg in enumerate(history):
                role = msg.get('role', 'unknown')
                content_preview = msg.get('content', '')[:200]
                if len(msg.get('content', '')) > 200:
                    content_preview += "..."
                print(f"[{i+1}] {role}: {content_preview}")

        except KeyboardInterrupt:
            print("\n\n检测到中断信号，正在退出...")
            break
        except Exception as e:
            print(f"\n发生错误: {e}")
            continue


if __name__ == "__main__":
    main()
