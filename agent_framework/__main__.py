#!/usr/bin/env python3
"""
Agent Framework __main__ module

运行方式:
    python -m agent_framework
    python -m agent_framework --config config.yaml
    python -m agent_framework --message "Hello"
"""

from . import AgentRunner

if __name__ == "__main__":
    AgentRunner().run()
