#!/usr/bin/env python3
"""
Agent Framework Logger - 简化日志系统

使用 Python 标准库 logging 模块
"""

import logging
import sys
from typing import Optional


# 默认日志配置
_DEFAULT_LOGGER_NAME = "agent_framework"


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
):
    """
    配置日志系统

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径 (可选)
        format: 日志格式字符串
    """
    logger = logging.getLogger(_DEFAULT_LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除现有处理器
    logger.handlers = []

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    console_handler.setFormatter(logging.Formatter(format))
    logger.addHandler(console_handler)

    # 添加文件处理器
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        file_handler.setFormatter(logging.Formatter(format))
        logger.addHandler(file_handler)


def get_logger(name: str = _DEFAULT_LOGGER_NAME) -> logging.Logger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        logging.Logger 实例
    """
    return logging.getLogger(name)
