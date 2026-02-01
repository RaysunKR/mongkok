"""
Mongkok AI Agent - 全能AI Agent

一个通过飞书机器人与用户交互的全能AI Agent，集成Claude Code SDK，
支持文档生成、网络浏览、程序开发等多种功能。
"""

__version__ = "1.0.0"
__author__ = "Mongkok AI Team"

from .modules.agent import AgentOrchestrator, get_agent
from .utils.config_loader import ConfigLoader
from .utils.logger import get_logger

__all__ = [
    'AgentOrchestrator',
    'get_agent',
    'ConfigLoader',
    'get_logger'
]


def run_main():
    """同步入口函数，用于命令行执行"""
    import asyncio
    import sys

    # 处理特殊命令（在argparse之前检查）
    if len(sys.argv) > 1:
        if sys.argv[1] == '--check-config':
            from mongkok_agent.main import check_config
            asyncio.run(check_config())
            return

        if sys.argv[1] == '--install-deps':
            from mongkok_agent.main import install_dependencies
            sys.exit(asyncio.run(install_dependencies()))

    # 默认启动主程序
    from mongkok_agent.main import main
    asyncio.run(main())
