#!/usr/bin/env python3
"""Agent Framework - 运行示例"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from examples.example import main

if __name__ == "__main__":
    main()
