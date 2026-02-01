import os
import subprocess
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from ..utils.logger import get_logger
from ..utils.config_loader import ConfigLoader
from ..utils.security import SecurityManager


class CodeDeveloper:
    """程序开发模块 - 支持代码生成、测试、执行"""

    # 支持的代码语言
    SUPPORTED_LANGUAGES = {
        'python': {
            'extension': '.py',
            'executable': 'python3',
            'template': '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\n',
            'test_template': '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nimport unittest\n\n'
        },
        'javascript': {
            'extension': '.js',
            'executable': 'node',
            'template': '// JavaScript Code\n',
            'test_template': '// Test Code\n'
        },
        'java': {
            'extension': '.java',
            'executable': 'java',
            'template': '// Java Code\n',
            'compile_cmd': 'javac'
        },
        'cpp': {
            'extension': '.cpp',
            'executable': './',
            'template': '// C++ Code\n#include <iostream>\nusing namespace std;\n\n',
            'compile_cmd': 'g++'
        },
        'bash': {
            'extension': '.sh',
            'executable': 'bash',
            'template': '#!/bin/bash\n',
            'test_template': '#!/bin/bash\n# Test Script\n'
        },
        'go': {
            'extension': '.go',
            'executable': 'go run',
            'template': 'package main\n\nimport "fmt"\n\n',
            'test_template': 'package main\n\n'
        }
    }

    def __init__(self, config: ConfigLoader = None):
        self._config = config or ConfigLoader()
        self._logger = get_logger('CodeDeveloper')
        self._security = SecurityManager(self._config)

        capabilities = self._config.capabilities
        self._enabled = capabilities.get('program_development', True)

        # 工作目录
        self._work_dir = os.path.join(
            self._config.storage.get('data_dir', 'data'),
            'code'
        )
        os.makedirs(self._work_dir, exist_ok=True)

        # 临时目录
        self._temp_dir = os.path.join(
            self._config.storage.get('temp_dir', 'temp'),
            'code'
        )
        os.makedirs(self._temp_dir, exist_ok=True)

    async def generate_code(
        self,
        description: str,
        language: str = 'python',
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成代码"""
        if not self._enabled:
            return {'success': False, 'error': '程序开发功能未启用'}

        if language not in self.SUPPORTED_LANGUAGES:
            return {
                'success': False,
                'error': f'不支持的语言: {language}',
                'supported_languages': list(self.SUPPORTED_LANGUAGES.keys())
            }

        # 生成文件名
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"generated_{timestamp}{self.SUPPORTED_LANGUAGES[language]['extension']}"

        filepath = os.path.join(self._work_dir, filename)

        # 这里可以调用Claude来生成实际的代码
        # 由于这是示例，我们创建一个简单的模板
        template = self.SUPPORTED_LANGUAGES[language]['template']

        code_content = template + f"""\n# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Description: {description}

# Code implementation will go here
# Use AI to generate the actual code based on the description
"""

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code_content)

            self._logger.info(f"代码文件创建成功: {filepath}")

            return {
                'success': True,
                'filepath': filepath,
                'filename': filename,
                'language': language,
                'content': code_content
            }

        except Exception as e:
            self._logger.error(f"代码生成失败: {e}")
            return {'success': False, 'error': str(e)}

    async def execute_code(
        self,
        code: str,
        language: str = 'python',
        timeout: int = 30,
        working_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行代码片段"""
        if not self._enabled:
            return {'success': False, 'error': '程序开发功能未启用'}

        # 安全检查
        allowed, reason = self._security.check_content_safety(code)
        if not allowed:
            return {'success': False, 'error': '代码安全检查失败', 'reason': reason}

        # 检查命令安全性
        allowed, reason = self._security.check_command_safety(code)
        if not allowed:
            return {'success': False, 'error': '代码包含危险操作', 'reason': reason}

        if language not in self.SUPPORTED_LANGUAGES:
            return {'success': False, 'error': f'不支持的语言: {language}'}

        # 创建临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix=self.SUPPORTED_LANGUAGES[language]['extension'],
            dir=self._temp_dir,
            delete=False
        ) as temp_file:
            temp_file.write(code)
            temp_path = temp_file.name

        try:
            # 构建执行命令
            lang_config = self.SUPPORTED_LANGUAGES[language]
            exec_cmd = []

            if language == 'python':
                exec_cmd = ['python3', temp_path]
            elif language == 'javascript':
                exec_cmd = ['node', temp_path]
            elif language == 'bash':
                os.chmod(temp_path, 0o755)
                exec_cmd = ['bash', temp_path]
            elif language == 'go':
                exec_cmd = ['go', 'run', temp_path]
            elif language in ['java', 'cpp']:
                # 需要编译
                compile_cmd = [lang_config['compile_cmd'], temp_path]
                compile_result = await self._run_command(compile_cmd, timeout)

                if not compile_result['success']:
                    return {
                        'success': False,
                        'error': '编译失败',
                        'output': compile_result.get('stderr', '')
                    }

                # 获取可执行文件路径
                if language == 'java':
                    exec_cmd = ['java', os.path.splitext(os.path.basename(temp_path))[0]]
                    os.chdir(os.path.dirname(temp_path))
                else:  # cpp
                    exec_path = temp_path.replace('.cpp', '')
                    exec_cmd = [exec_path]

            self._logger.info(f"执行代码: {language}")

            # 执行代码
            result = await self._run_command(exec_cmd, timeout)

            # 清理临时文件
            try:
                os.unlink(temp_path)
                if language in ['java', 'cpp']:
                    exec_path = temp_path.replace(f".{language}", '').replace('.cpp', '')
                    if os.path.exists(exec_path):
                        os.unlink(exec_path)
                        if language == 'java':
                            class_file = temp_path.replace('.java', '.class')
                            if os.path.exists(class_file):
                                os.unlink(class_file)
            except:
                pass

            return {
                'success': result['success'],
                'stdout': result.get('stdout', ''),
                'stderr': result.get('stderr', ''),
                'exit_code': result.get('exit_code', -1),
                'language': language
            }

        except asyncio.TimeoutError:
            return {'success': False, 'error': '代码执行超时', 'timeout': timeout}
        except Exception as e:
            self._logger.error(f"代码执行失败: {e}")
            return {'success': False, 'error': str(e)}

    async def _run_command(
        self,
        command: List[str],
        timeout: int
    ) -> Dict[str, Any]:
        """运行命令"""
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._temp_dir
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            return {
                'success': process.returncode == 0,
                'stdout': stdout.decode('utf-8', errors='ignore'),
                'stderr': stderr.decode('utf-8', errors='ignore'),
                'exit_code': process.returncode
            }

        except asyncio.TimeoutError:
            try:
                process.kill()
            except:
                pass
            return {
                'success': False,
                'stdout': '',
                'stderr': 'Execution timeout',
                'exit_code': -1
            }

    async def test_code(
        self,
        code: str,
        tests: List[str],
        language: str = 'python'
    ) -> Dict[str, Any]:
        """运行测试"""
        if not self._enabled:
            return {'success': False, 'error': '程序开发功能未启用'}

        results = []

        for test in tests:
            # 拼接代码和测试
            full_code = code + "\n\n" + test

            result = await self.execute_code(full_code, language)

            results.append({
                'test': test[:50] + '...' if len(test) > 50 else test,
                'passed': result['success'],
                'output': result.get('stdout', ''),
                'error': result.get('stderr', '')
            })

        passed = sum(1 for r in results if r['passed'])

        self._logger.info(f"测试完成: {passed}/{len(results)} 通过")

        return {
            'success': passed == len(results),
            'total_tests': len(results),
            'passed_tests': passed,
            'failed_tests': len(results) - passed,
            'results': results
        }

    async def analyze_code(
        self,
        code: str,
        language: str = 'python'
    ) -> Dict[str, Any]:
        """分析代码"""
        if not self._enabled:
            return {'success': False, 'error': '程序开发功能未启用'}

        analysis = {
            'language': language,
            'lines': len(code.split('\n')),
            'characters': len(code),
            'issues': [],
            'suggestions': []
        }

        # 基本代码分析
        lines = code.split('\n')

        # 检查空行过多
        empty_lines = sum(1 for line in lines if not line.strip())
        if empty_lines > len(lines) * 0.5:
            analysis['issues'].append(f'空行过多 ({empty_lines} / {len(lines)})')

        # 检查代码长度
        long_lines = [(i + 1, len(line)) for i, line in enumerate(lines) if len(line) > 100]
        if long_lines:
            analysis['issues'].append(f'{len(long_lines)} 行超过100字符')
            analysis['suggestions'].append('建议将长行拆分为多行以提高可读性')

        # Python特定分析
        if language == 'python':
            # 检查是否有docstring
            if '"""' not in code and "'''" not in code:
                analysis['suggestions'].append('建议添加docstring说明')

            # 检查是否有main入口
            if '__main__' not in code:
                analysis['suggestions'].append('建议添加 if __name__ == "__main__" 入口')

            # 检查import
            imports = [line for line in lines if line.strip().startswith('import') or line.strip().startswith('from')]
            analysis['imports_count'] = len(imports)

        self._logger.info(f"代码分析完成")

        return {
            'success': True,
            **analysis
        }

    async def format_code(
        self,
        code: str,
        language: str = 'python'
    ) -> Dict[str, Any]:
        """格式化代码"""
        if not self._enabled:
            return {'success': False, 'error': '程序开发功能未启用'}

        # 基本格式化：移除多余空行，统一缩进
        formatted_lines = []
        empty_count = 0

        for line in code.split('\n'):
            stripped = line.rstrip()

            if not stripped:
                empty_count += 1
                if empty_count <= 2:  # 最多连续2个空行
                    formatted_lines.append('')
            else:
                empty_count = 0
                formatted_lines.append(stripped)

        # 移除末尾空行
        while formatted_lines and not formatted_lines[-1]:
            formatted_lines.pop()

        formatted_code = '\n'.join(formatted_lines)

        self._logger.info(f"代码格式化完成")

        return {
            'success': True,
            'formatted_code': formatted_code,
            'language': language
        }

    async def create_project_scaffold(
        self,
        project_name: str,
        project_type: str = 'basic'
    ) -> Dict[str, Any]:
        """创建项目脚手架"""
        if not self._enabled:
            return {'success': False, 'error': '程序开发功能未启用'}

        project_dir = os.path.join(self._work_dir, project_name)

        try:
            os.makedirs(project_dir, exist_ok=True)

            if project_type == 'python':
                # Python项目结构
                dirs = ['src', 'tests', 'docs', 'data']
                for d in dirs:
                    os.makedirs(os.path.join(project_dir, d), exist_ok=True)

                # 创建基础文件
                files = {
                    'README.md': f"# {project_name}\n\nProject description here.\n",
                    'requirements.txt': '# Add your requirements here\n',
                    '.gitignore': '__pycache__/\n*.pyc\n.pytest_cache/\n.env\n',
                    'src/__init__.py': '',
                    'tests/__init__.py': '',
                    'tests/test_main.py': 'import unittest\n\nclass TestMain(unittest.TestCase):\n    pass\n\nif __name__ == "__main__":\n    unittest.main()\n'
                }

                for file_path, content in files.items():
                    full_path = os.path.join(project_dir, file_path)
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(content)

            elif project_type == 'basic':
                # 基础项目
                os.makedirs(os.path.join(project_dir, 'src'), exist_ok=True)
                with open(os.path.join(project_dir, 'README.md'), 'w') as f:
                    f.write(f"# {project_name}\n\n")

            self._logger.info(f"项目脚手架创建成功: {project_dir}")

            return {
                'success': True,
                'project_name': project_name,
                'project_dir': project_dir,
                'project_type': project_type,
                'structure': self._get_directory_structure(project_dir)
            }

        except Exception as e:
            self._logger.error(f"项目脚手架创建失败: {e}")
            return {'success': False, 'error': str(e)}

    def _get_directory_structure(self, directory: str) -> List[str]:
        """获取目录结构"""
        structure = []
        for root, dirs, files in os.walk(directory):
            level = root.replace(directory, '').count(os.sep)
            indent = '    ' * level
            structure.append(f"{indent}{os.path.basename(root)}/")
            sub_indent = '    ' * (level + 1)
            for file in files:
                structure.append(f"{sub_indent}{file}")
        return structure
