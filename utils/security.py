import hashlib
import hmac
import re
import time
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class UserPermission:
    """用户权限"""
    user_id: str
    allowed: bool = True
    reason: str = ""


class SecurityManager:
    """安全管理器"""

    def __init__(self, config):
        self._config = config
        self._rate_limits: dict = {}
        self._command_whitelist = set(config.get('security.command_whitelist', []))
        self._command_blacklist = set(config.get('security.command_blacklist', []))
        self._blocked_keywords = set(config.get('security.content_filter.blocked_keywords', []))
        self._allowed_users = set(config.get('security.allowed_users', []))
        self._rate_limit_config = config.get('security.rate_limit', {})

    def check_user_permission(self, user_id: str) -> UserPermission:
        """检查用户权限"""
        if not self._allowed_users:
            # 如果没有配置允许用户列表，则允许所有用户
            return UserPermission(user_id, True)

        if user_id in self._allowed_users:
            return UserPermission(user_id, True)
        else:
            return UserPermission(user_id, False, "用户不在允许列表中")

    def check_rate_limit(self, user_id: str) -> tuple[bool, str]:
        """检查速率限制"""
        if not self._rate_limit_config.get('enabled', False):
            return True, ""

        now = time.time()
        minute_key = f"{user_id}:{int(now // 60)}"
        hour_key = f"{user_id}:{int(now // 3600)}"

        # 初始化
        if user_id not in self._rate_limits:
            self._rate_limits[user_id] = {
                'minutes': {},
                'hours': {}
            }

        user_data = self._rate_limits[user_id]

        # 检查每分钟限制
        max_per_minute = self._rate_limit_config.get('max_requests_per_minute', 30)
        if minute_key not in user_data['minutes']:
            user_data['minutes'][minute_key] = 0
        user_data['minutes'][minute_key] += 1

        if user_data['minutes'][minute_key] > max_per_minute:
            return False, f"超过每分钟请求限制 ({max_per_minute})"

        # 检查每小时限制
        max_per_hour = self._rate_limit_config.get('max_requests_per_hour', 200)
        if hour_key not in user_data['hours']:
            user_data['hours'][hour_key] = 0
        user_data['hours'][hour_key] += 1

        if user_data['hours'][hour_key] > max_per_hour:
            return False, f"超过每小时请求限制 ({max_per_hour})"

        return True, ""

    def check_content_safety(self, content: str) -> tuple[bool, str]:
        """检查内容安全"""
        if not self._config.get('security.content_filter.enabled', False):
            return True, ""

        content_lower = content.lower()

        for keyword in self._blocked_keywords:
            if keyword.lower() in content_lower:
                return False, f"内容包含违禁关键词: {keyword}"

        return True, ""

    def check_command_safety(self, command: str) -> tuple[bool, str]:
        """检查命令安全性"""
        command_lower = command.strip().lower()

        # 检查黑名单
        for forbidden in self._command_blacklist:
            if forbidden.lower() in command_lower:
                return False, f"命令包含禁止的操作: {forbidden}"

        # 检查白名单（如果配置了白名单）
        if self._command_whitelist:
            whitelisted = False
            for allowed in self._command_whitelist:
                if command_lower.startswith(allowed.lower()):
                    whitelisted = True
                    break
            if not whitelisted:
                return False, "命令不在允许列表中"

        return True, ""

    def sanitize_input(self, input_str: str) -> str:
        """净化输入"""
        # 移除潜在的危险字符序列
        dangerous_patterns = [
            r'\$\(',  # 命令替换
            r'`.*`',  # 反引号命令替换
            r';\s*\w+',  # 命令链
            r'\|\s*\w+',  # 管道命令
        ]

        sanitized = input_str
        for pattern in dangerous_patterns:
            sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE)

        return sanitized

    def validate_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str
    ) -> bool:
        """验证Webhook签名"""
        if not signature or not secret:
            return True

        expected = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, expected)

    def generate_signature(self, payload: bytes, secret: str) -> str:
        """生成签名"""
        return hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

    def mask_sensitive_data(self, data: str, keywords: List[str] = None) -> str:
        """遮蔽敏感数据"""
        keywords = keywords or [
            'api_key', 'token', 'password', 'secret', 'key',
            'appid', 'appsecret', 'app_key', 'access_token'
        ]

        masked = data
        for keyword in keywords:
            pattern = rf'"{keyword}"\s*:\s*"[^"]*"'
            replacement = lambda m: m.group(0)[:m.group(0).index('"') + 2] + '***MASKED***"'
            masked = re.sub(pattern, replacement, masked, flags=re.IGNORECASE)

        return masked
