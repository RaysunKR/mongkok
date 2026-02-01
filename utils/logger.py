import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional


class AgentLogger:
    """日志管理器"""

    _instance: Optional['AgentLogger'] = None
    _loggers: dict = {}

    def __new__(cls) -> 'AgentLogger':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def setup_logger(
        self,
        name: str,
        log_file: str = "logs/agent.log",
        level: str = "INFO",
        max_size_mb: int = 10,
        backup_count: int = 5
    ) -> logging.Logger:
        """配置日志器"""

        if name in self._loggers:
            return self._loggers[name]

        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, level.upper()))

        # 清除已有处理器
        logger.handlers.clear()

        # 文件处理器
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, level.upper()))

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, level.upper()))

        # 设置格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        self._loggers[name] = logger
        return logger

    def get_logger(self, name: str) -> logging.Logger:
        """获取日志器"""
        if name not in self._loggers:
            return self.setup_logger(name)
        return self._loggers[name]


def get_logger(name: str) -> logging.Logger:
    """便捷函数：获取日志器"""
    return AgentLogger().get_logger(name)
