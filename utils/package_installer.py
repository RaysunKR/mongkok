import subprocess
import sys
import asyncio
import os
from typing import List, Optional, Tuple
from ..utils.logger import get_logger
from ..utils.config_loader import ConfigLoader


class PackageInstaller:
    """自动安装扩展包管理器"""

    def __init__(self, config: ConfigLoader = None):
        self._config = config or ConfigLoader()
        self._logger = get_logger('PackageInstaller')
        self._advanced_config = self._config.advanced
        self._enabled = self._advanced_config.get('auto_package_install', True)

        # 检测是否使用uv环境，优先使用uv pip
        self._use_uv = self._check_uv_available()

    def _check_uv_available(self) -> bool:
        """检查uv是否可用"""
        try:
            result = subprocess.run(
                ['uv', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                self._logger.info(f"检测到uv可用: {result.stdout.strip()}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._logger.info("uv不可用，将使用pip")
        return False

    async def install_package(
        self,
        package_name: str,
        version: Optional[str] = None,
        upgrade: bool = False
    ) -> Tuple[bool, str]:
        """安装Python包"""
        if not self._enabled:
            return False, "自动安装功能已禁用"

        try:
            spec = package_name
            if version:
                spec = f"{package_name}=={version}"

            # 使用uv pip或传统pip
            if self._use_uv:
                args = ['uv', 'pip', 'install']
            else:
                args = [sys.executable, '-m', 'pip', 'install']

            if upgrade:
                args.append('--upgrade')
            args.append(spec)

            self._logger.info(f"正在安装包: {spec}")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._advanced_config.get('timeout_seconds', 60) + 60
            )

            if process.returncode == 0:
                self._logger.info(f"成功安装包: {spec}")
                return True, f"成功安装包: {spec}"
            else:
                error_msg = stderr.decode('utf-8', errors='ignore')
                self._logger.error(f"安装包失败: {error_msg}")
                return False, f"安装失败: {error_msg}"

        except asyncio.TimeoutError:
            return False, "安装超时"
        except Exception as e:
            self._logger.error(f"安装异常: {e}")
            return False, f"安装异常: {str(e)}"

    async def install_multiple_packages(
        self,
        packages: List[Tuple[str, Optional[str]]]
    ) -> Tuple[int, List[str]]:
        """安装多个包"""
        results = []
        success_count = 0

        for package_name, version in packages:
            success, message = await self.install_package(package_name, version)
            if success:
                success_count += 1
            results.append(message)

        return success_count, results

    def check_package_installed(self, package_name: str) -> bool:
        """检查包是否已安装"""
        try:
            if self._use_uv:
                args = ['uv', 'pip', 'show', package_name]
            else:
                args = [sys.executable, '-m', 'pip', 'show', package_name]
            result = subprocess.run(
                args,
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except:
            return False

    def get_package_version(self, package_name: str) -> Optional[str]:
        """获取已安装包的版本"""
        try:
            if self._use_uv:
                args = ['uv', 'pip', 'show', package_name]
            else:
                args = [sys.executable, '-m', 'pip', 'show', package_name]
            result = subprocess.run(
                args,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('Version:'):
                        return line.split(':', 1)[1].strip()
            return None
        except:
            return None

    async def ensure_packages(
        self,
        requirements: List[str],
        force_reinstall: bool = False
    ) -> Tuple[bool, List[str]]:
        """确保所需包已安装"""
        if not requirements:
            return True, []

        messages = []
        all_success = True

        for requirement in requirements:
            package_name = requirement.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].strip()

            if not force_reinstall and self.check_package_installed(package_name):
                version = self.get_package_version(package_name)
                messages.append(f"包已存在: {package_name} (版本: {version})")
                continue

            success, msg = await self.install_package(requirement)
            messages.append(msg)
            if not success:
                all_success = False

        return all_success, messages

    async def install_feishu_sdk(self) -> Tuple[bool, str]:
        """安装飞书SDK"""
        return await self.install_package('lark-oapi')

    async def install_web_browsing_packages(self) -> Tuple[bool, str]:
        """安装网络浏览相关包"""
        packages = [
            ('requests', None),
            ('beautifulsoup4', None),
            ('selenium', None),
            ('playwright', None),
        ]
        success_count, results = await self.install_multiple_packages(packages)
        return success_count == len(packages), '\n'.join(results)

    async def install_document_generation_packages(self) -> Tuple[bool, str]:
        """安装文档生成相关包"""
        packages = [
            ('markdown', None),
            ('python-docx', None),
            ('reportlab', None),
            ('jinja2', None),
        ]
        success_count, results = await self.install_multiple_packages(packages)
        return success_count == len(packages), '\n'.join(results)

    async def install_claude_packages(self) -> Tuple[bool, str]:
        """安装Claude相关包"""
        # Anthropic官方SDK
        return await self.install_package('anthropic')
