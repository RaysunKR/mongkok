import asyncio
import json
import os
import subprocess
import tempfile
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
from ..utils.logger import get_logger
from ..utils.config_loader import ConfigLoader
from ..utils.security import SecurityManager


class ClaudeClient:
    """Claude Code SDK 客户端 - 调用本地安装的Claude Code CLI"""

    # Claude Code CLI 命令路径
    CLAUDE_CODE_COMMANDS = [
        'claude',           # 标准安装路径
        '/usr/local/bin/claude',  # macOS/Linux常见路径
        os.path.expanduser('~/.local/bin/claude'),  # 用户本地路径
        'claude-code',      # 备用命令名
    ]

    def __init__(self, config: ConfigLoader = None):
        self._config = config or ConfigLoader()
        self._logger = get_logger('ClaudeClient')
        self._security = SecurityManager(self._config)

        # 查找Claude Code CLI
        self._claude_path = self._find_claude_command()

        if not self._claude_path:
            self._logger.warning("未找到Claude Code CLI命令，请确保已正确安装")
        else:
            self._logger.info(f"找到Claude Code CLI: {self._claude_path}")

        claude_config = self._config.claude
        self._model = claude_config.get('model', 'claude-sonnet-4-20250514')
        self._max_tokens = claude_config.get('max_tokens', 4096)
        self._temperature = claude_config.get('temperature', 0.7)

        # 会话文件存储路径
        self._sessions_dir = Path(self._config.storage.get('data_dir', 'data')) / 'sessions'
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        # 当前会话文件
        self._current_session_file: Optional[Path] = None

    def _find_claude_command(self) -> Optional[str]:
        """查找Claude Code CLI命令"""
        for cmd in self.CLAUDE_CODE_COMMANDS:
            try:
                result = subprocess.run(
                    [cmd, '--version'],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    self._logger.info(f"Claude Code CLI版本: {result.stdout.decode().strip()}")
                    return cmd
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

        # 尝试使用which/where查找
        try:
            result = subprocess.run(
                ['which', 'claude'],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                path = result.stdout.decode().strip()
                if path:
                    return path
        except:
            pass

        return None

    def _is_claude_available(self) -> bool:
        """检查Claude Code是否可用"""
        return self._claude_path is not None

    async def chat(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        working_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """发送聊天消息到本地Claude Code"""

        # 安全检查
        allowed, reason = self._security.check_content_safety(message)
        if not allowed:
            return {
                'success': False,
                'error': '内容安全检查失败',
                'reason': reason
            }

        if not self._is_claude_available():
            return {
                'success': False,
                'error': 'Claude Code CLI不可用',
                'reason': '未找到本地安装的Claude Code CLI，请先安装claude'
            }

        try:
            # 创建临时会话
            return await self._run_claude_command(
                message=message,
                conversation_history=conversation_history,
                system_prompt=system_prompt,
                working_dir=working_dir
            )

        except asyncio.TimeoutError:
            self._logger.error("Claude Code执行超时")
            return {
                'success': False,
                'error': '执行超时',
                'reason': 'Claude Code执行超时'
            }
        except Exception as e:
            self._logger.error(f"Claude Code执行失败: {e}")
            return {
                'success': False,
                'error': '执行失败',
                'reason': str(e)
            }

    async def _run_claude_command(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        working_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """运行Claude Code命令"""

        # 如果有系统提示词，添加到消息前
        final_message = message
        if system_prompt:
            final_message = f"System: {system_prompt}\n\nUser: {message}"

        # 如果有对话历史，构建上下文
        if conversation_history:
            context_parts = []
            for msg in conversation_history[-5:]:  # 限制历史长度
                role = msg.get('role', 'Unknown')
                content = msg.get('content', '')
                context_parts.append(f"{role}: {content}")
            context_parts.append(f"user: {message}")
            final_message = '\n\n'.join(context_parts)

        self._logger.info(f"执行Claude Code命令: {message[:100]}...")

        # 构建Claude Code命令
        # Claude Code CLI 格式: claude [选项] <消息>
        cmd = [self._claude_path]

        # 添加常用选项
        cmd.extend([
            '-p',                        # 非交互模式 (Print response and exit)
            '--output-format', 'json',     # 输出JSON格式
            '--permission-mode', 'bypassPermissions',  # 绕过所有权限检查，允许所有工具
        ])

        # 添加模型选项
        if self._model:
            cmd.extend(['--model', self._model])

        # 添加消息
        cmd.append(final_message)

        # 确定工作目录
        work_dir = working_dir or os.getcwd()

        # 执行命令
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._config.advanced.get('timeout_seconds', 120)
            )
        except asyncio.TimeoutError:
            process.kill()
            raise

        result_stdout = stdout.decode('utf-8', errors='ignore')
        result_stderr = stderr.decode('utf-8', errors='ignore')

        self._logger.debug(f"Claude Code stdout: {result_stdout[:500]}")
        self._logger.debug(f"Claude Code stderr: {result_stderr[:500]}")

        # 解析输出
        if process.returncode == 0:
            import re

            # 尝试解析JSON输出
            try:
                output_json = json.loads(result_stdout)
                self._logger.info(f"Claude JSON输出结构: {list(output_json.keys())}")

                # 优先提取result字段（Claude Code CLI的JSON响应格式）
                content = (
                    output_json.get('result', '') or
                    output_json.get('response', '') or
                    output_json.get('content', '') or
                    output_json.get('output', '') or
                    output_json.get('message', '') or
                    (isinstance(output_json.get('response', {}), dict) and output_json.get('response', {}).get('text', '')) or
                    (isinstance(output_json.get('data', {}), dict) and output_json.get('data', {}).get('text', '')) or
                    str(output_json)
                )

                # 如果内容是字典或列表，尝试转换为字符串
                if isinstance(content, (dict, list)):
                    content = json.dumps(content, ensure_ascii=False)

                # 确保content是字符串
                if not isinstance(content, str):
                    content = str(content)

            except json.JSONDecodeError as e:
                self._logger.warning(f"JSON解析失败: {e}, 使用原始输出")
                # 如果不是JSON格式，直接使用输出
                content = result_stdout

            # 清理输出中的ANSI转义序列
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            content = ansi_escape.sub('', content).strip()

            # 额外清理：移除可能的markdown代码块标记
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*$', '', content)
            content = re.sub(r'``\s*', '', content)
            content = content.strip()

            self._logger.info(f"Claude Code执行成功, 内容长度: {len(content)}, 预览: {content[:100]}")

            return {
                'success': True,
                'content': content,
                'raw_output': result_stdout,
                'stderr': result_stderr if result_stderr else None,
                'exit_code': process.returncode
            }
        else:
            # 命令执行失败，返回错误信息
            # 尝试从输出中提取有用信息
            output = result_stdout + result_stderr

            self._logger.error(f"Claude Code执行失败: {output[:200]}")

            return {
                'success': False,
                'error': '命令执行失败',
                'reason': output[:500],
                'exit_code': process.returncode
            }

    async def execute_in_context(
        self,
        instructions: str,
        working_dir: Optional[str] = None,
        read_files: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """在指定上下文中执行Claude Code任务（可读取文件）"""

        if not self._is_claude_available():
            return {
                'success': False,
                'error': 'Claude Code CLI不可用'
            }

        work_dir = working_dir or os.getcwd()

        # 准备上下文信息
        context_message = instructions

        if read_files:
            context_message += "\n\n相关文件:\n\n"
            for file_path in read_files:
                full_path = os.path.join(work_dir, file_path)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        context_message += f"--- {file_path} ---\n{content}\n---\n\n"
                    except Exception as e:
                        context_message += f"--- {file_path} (读取失败: {e}) ---\n\n"
                else:
                    context_message += f"--- {file_path} (文件不存在) ---\n\n"

        self._logger.info(f"在上下文中执行: {instructions[:100]}...")

        return await self._run_claude_command(
            message=context_message,
            working_dir=work_dir
        )

    async def stream_chat(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        working_dir: Optional[str] = None
    ):
        """流式聊天 - 逐步输出Claude Code的响应"""

        if not self._is_claude_available():
            yield "Claude Code CLI不可用"
            return

        # 构建消息
        final_message = message
        if system_prompt:
            final_message = f"System: {system_prompt}\n\nUser: {message}"

        cmd = [self._claude_path, '-p', '--permission-mode', 'bypassPermissions']
        if self._model:
            cmd.extend(['--model', self._model])
        cmd.append(final_message)

        work_dir = working_dir or os.getcwd()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir
            )

            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            buffer = ""

            while True:
                line = await process.stdout.readline()
                if not line:
                    break

                decoded = line.decode('utf-8', errors='ignore')
                # 移除ANSI码
                clean = ansi_escape.sub('', decoded)
                buffer += clean

                # 按行输出
                if '\n' in buffer:
                    lines = buffer.split('\n')
                    buffer = lines.pop()
                    for l in lines:
                        if l.strip():
                            yield l

            if buffer.strip():
                yield buffer

            await process.wait()

        except Exception as e:
            self._logger.error(f"流式聊天失败: {e}")
            yield None

    def _get_default_system_prompt(self) -> str:
        """获取默认系统提示词"""
        return """你是一个全能AI Agent助手，通过飞书机器人与用户交互。

你的能力包括：
1. 文档生成 - 可以创建各种格式的文档
2. 网络浏览和信息收集 - 可以搜索和整理网络信息
3. 程序开发 - 可以编写、调试和优化代码
4. 自动整理结果 - 可以结构化地组织和呈现信息

请以专业、友好、清晰的方式回答用户的问题。如果需要执行某些操作，请先说明你的计划。

注意：始终确保回答的安全性和准确性。"""

    async def analyze_task(self, task: str) -> Dict[str, Any]:
        """分析任务类型并制定执行计划"""
        analysis_prompt = f"""分析以下任务，确定需要使用的工具和执行步骤：

任务：{task}

请以JSON格式返回分析结果，包含以下字段：
- task_type: 任务类型 (document_generation, web_browsing, program_development, general)
- required_tools: 需要使用的工具列表
- steps: 执行步骤数组
- estimated_complexity: 复杂度评估 (low, medium, high)
- additional_requirements: 额外需求（如果有的话）"""

        response = await self.chat(analysis_prompt)

        if response.get('success'):
            try:
                # 尝试解析JSON
                content = response['content']
                # 提取JSON部分
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = content[json_start:json_end]
                    analysis = json.loads(json_str)
                    return {'success': True, 'analysis': analysis}
            except json.JSONDecodeError:
                pass

        return {
            'success': False,
            'error': '任务分析失败',
            'fallback': self._fallback_task_analysis(task)
        }

    def _fallback_task_analysis(self, task: str) -> Dict[str, str]:
        """备用的任务分析"""
        task_lower = task.lower()

        if any(kw in task_lower for kw in ['写文档', '生成文档', '创建文档', '文档']):
            return {
                'task_type': 'document_generation',
                'required_tools': ['document_generator'],
                'steps': ['分析需求', '生成内容', '格式化输出']
            }
        elif any(kw in task_lower for kw in ['搜索', '查找', '获取信息', '上网']):
            return {
                'task_type': 'web_browsing',
                'required_tools': ['web_browsing'],
                'steps': ['执行搜索', '收集信息', '整理结果']
            }
        elif any(kw in task_lower for kw in ['写代码', '开发', '编程', '代码', '程序']):
            return {
                'task_type': 'program_development',
                'required_tools': ['code_developer'],
                'steps': ['分析需求', '编写代码', '测试验证']
            }
        else:
            return {
                'task_type': 'general',
                'required_tools': [],
                'steps': ['理解任务', '生成回答']
            }
