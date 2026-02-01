import json
import os
from typing import Any, Dict


class ConfigLoader:
    """配置加载器"""

    _instance: 'ConfigLoader' = None
    _config: Dict[str, Any] = {}

    def __new__(cls, config_path: str = None) -> 'ConfigLoader':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: str = None):
        if not hasattr(self, '_initialized'):
            self._config_path = config_path or os.path.join(
                os.path.dirname(__file__), '..', 'config', 'config.json'
            )
            self.load_config()
            self._initialized = True

    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not os.path.exists(self._config_path):
            raise FileNotFoundError(f"配置文件不存在: {self._config_path}")

        with open(self._config_path, 'r', encoding='utf-8') as f:
            self._config = json.load(f)

        return self._config

    def save_config(self, config: Dict[str, Any] = None) -> bool:
        """保存配置文件"""
        config_to_save = config or self._config

        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)

        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> bool:
        """设置配置项"""
        keys = key.split('.')
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value
        return self.save_config()

    @property
    def feishu(self) -> Dict[str, Any]:
        """获取飞书配置"""
        return self._config.get('feishu', {})

    @property
    def claude(self) -> Dict[str, Any]:
        """获取Claude配置"""
        return self._config.get('claude', {})

    @property
    def security(self) -> Dict[str, Any]:
        """获取安全配置"""
        return self._config.get('security', {})

    @property
    def capabilities(self) -> Dict[str, Any]:
        """获取能力配置"""
        return self._config.get('capabilities', {})

    @property
    def logging(self) -> Dict[str, Any]:
        """获取日志配置"""
        return self._config.get('logging', {})

    @property
    def storage(self) -> Dict[str, Any]:
        """获取存储配置"""
        return self._config.get('storage', {})

    @property
    def advanced(self) -> Dict[str, Any]:
        """获取高级配置"""
        return self._config.get('advanced', {})


# 全局配置实例
config = ConfigLoader()
