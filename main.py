#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mongkok AI Agent - 主入口文件

一个通过飞书机器人与用户交互的全能AI Agent
"""

import asyncio
import argparse
import os
import signal
import sys

# 添加父目录到Python路径，以便正确导入模块
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from mongkok_agent import AgentOrchestrator, ConfigLoader, get_logger
from mongkok_agent.modules import FeishuBot


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Mongkok AI Agent')
    parser.add_argument('--config', '-c', default=None,
                       help='配置文件路径 (默认: config/config.json)')
    parser.add_argument('--debug', '-d', action='store_true',
                       help='调试模式')
    parser.add_argument('--check-config', action='store_true',
                       help='检查配置')
    parser.add_argument('--install-deps', action='store_true',
                       help='安装依赖')

    args = parser.parse_args()

    # 处理特殊命令
    if args.check_config:
        await check_config()
        return

    if args.install_deps:
        import sys
        sys.exit(await install_dependencies())

    # 加载配置
    config = ConfigLoader(args.config)

    # 如果调试模式，设置日志级别
    if args.debug:
        config._config['logging']['level'] = 'DEBUG'

    logger = get_logger('Main')

    logger.info("=" * 50)
    logger.info("Mongkok AI Agent 启动中...")
    logger.info(f"版本: 1.0.0")
    logger.info("=" * 50)

    # 创建并启动Agent
    agent = AgentOrchestrator(config)

    # 信号处理标志
    shutdown_event = asyncio.Event()

    def signal_handler(sig, frame):
        logger.info("收到停止信号，正在关闭...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 启动服务
        async def run_with_shutdown():
            task = asyncio.create_task(agent.start())
            await shutdown_event.wait()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await agent.stop()

        await run_with_shutdown()

    except KeyboardInterrupt:
        logger.info("程序被中断")
    except Exception as e:
        logger.error(f"程序异常: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
    finally:
        logger.info("程序已关闭")


async def check_config():
    """检查配置文件"""
    config = ConfigLoader()
    logger = get_logger('ConfigCheck')

    logger.info("检查配置文件...")

    # 检查飞书配置
    feishu = config.feishu
    if not feishu.get('app_id'):
        logger.warning("未配置飞书 app_id")
    if not feishu.get('app_secret'):
        logger.warning("未配置飞书 app_secret")

    # 检查Claude配置
    claude = config.claude
    if not claude.get('cli_path'):
        logger.info("未指定Claude CLI路径，将自动查找")
    else:
        logger.info(f"使用指定Claude CLI路径: {claude.get('cli_path')}")

    # 检查安全配置
    allowed_users = config.security.get('allowed_users', [])
    if not allowed_users:
        logger.info("未配置允许用户列表，将允许所有用户")
    else:
        logger.info(f"允许用户列表: {allowed_users}")

    logger.info("配置检查完成")


async def install_dependencies():
    """安装依赖包"""
    logger = get_logger('Install')

    logger.info("检查并安装依赖包...")

    from mongkok_agent.utils.package_installer import PackageInstaller

    installer = PackageInstaller()

    required_packages = [
        'lark-oapi',
        'websockets',
        'fastapi',
        'uvicorn[standard]',
        'aiohttp',
        'beautifulsoup4',
        'markdown',
        'python-docx',
        'reportlab',
        'jinja2'
    ]

    success, messages = await installer.ensure_packages(required_packages)

    for msg in messages:
        logger.info(msg)

    if success:
        logger.info("所有依赖包已就绪")
        return 0
    else:
        logger.error("部分依赖包安装失败")
        return 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--check-config':
        asyncio.run(check_config())
    elif len(sys.argv) > 1 and sys.argv[1] == '--install-deps':
        sys.exit(asyncio.run(install_dependencies()))
    else:
        asyncio.run(main())
