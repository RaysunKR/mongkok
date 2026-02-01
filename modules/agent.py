import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
import json

from .claude_client import ClaudeClient
from .feishu_bot import FeishuBot, _markdown_to_feishu_rich_text
from .document_generator import DocumentGenerator
from .web_browser import WebBrowser
from .code_developer import CodeDeveloper

from ..utils.logger import get_logger
from ..utils.config_loader import ConfigLoader
from ..utils.security import SecurityManager
from ..utils.package_installer import PackageInstaller


class AgentOrchestrator:
    """全能AI Agent编排器 - 协调各个模块处理用户请求"""

    def __init__(self, config: ConfigLoader = None):
        self._config = config or ConfigLoader()
        self._logger = get_logger('AgentOrchestrator')
        self._security = SecurityManager(self._config)

        # 初始化各模块
        self._claude_client = ClaudeClient(self._config)
        self._feishu_bot = FeishuBot(self._config)
        self._document_generator = DocumentGenerator(self._config)
        self._web_browser = WebBrowser(self._config)
        self._code_developer = CodeDeveloper(self._config)
        self._package_installer = PackageInstaller(self._config)

        # 设置飞书机器人默认消息处理器
        self._feishu_bot.set_default_handler(self._handle_user_message)

        # 会话历史存储
        self._conversation_history: Dict[str, List[Dict[str, str]]] = {}

        # 任务队列
        self._task_queue: List[Dict[str, Any]] = []
        self._processing = False

        self._logger.info("Agent编排器初始化完成")

    async def handle_message(
        self,
        content: str,
        chat_id: str,
        sender_id: str,
        message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """处理用户消息（外部调用接口）"""
        try:
            self._logger.info("=" * 60)
            self._logger.info(f"处理用户消息 - chat_id: {chat_id}, sender_id: {sender_id}, message_id: {message_id}")
            self._logger.info(f"消息内容: {content[:500] if len(content) > 500 else content}")

            # 获取对话历史
            history = self._get_conversation_history(chat_id)
            self._logger.info(f"当前对话历史长度: {len(history)}")

            # 添加当前消息到历史
            history.append({
                "role": "user",
                "content": content
            })

            # 分析任务类型
            self._logger.info("发送'正在分析'提示消息")
            await self._feishu_bot.send_text_message(
                chat_id,
                "收到您的请求，正在分析并处理..."
            )

            self._logger.info("开始任务分析")
            task_analysis = await self._analyze_task(content)

            self._logger.info(f"任务分析结果: {task_analysis.get('analysis', {})}")
            self._logger.info(f"分析成功: {task_analysis.get('success')}")

            # 根据任务类型执行相应的操作
            self._logger.info("开始执行任务")
            response = await self._execute_task(task_analysis, content, chat_id, sender_id, history)

            self._logger.info(f"任务执行结果 - 成功: {response.get('success')}")

            # 添加响应到历史
            if response.get('success'):
                response_text = response.get('content', response.get('message', ''))
                history.append({
                    "role": "assistant",
                    "content": response_text
                })

                # 限制历史长度
                self._conversation_history[chat_id] = history[-20:]
                self._logger.info(f"更新后的对话历史长度: {len(self._conversation_history[chat_id])}")

            self._logger.info("=" * 60)
            return response

        except Exception as e:
            self._logger.error(f"处理用户消息失败: {e}")
            # 发送错误消息
            await self._feishu_bot.send_text_message(
                chat_id,
                f"处理请求时出错: {str(e)}"
            )
            return {'success': False, 'error': str(e)}

    async def _handle_user_message(
        self,
        message_type: str,
        content: str,
        chat_id: str,
        sender_id: str,
        message_id: Optional[str] = None,
        raw_event: Optional[Dict[str, Any]] = None
    ):
        """飞书机器人消息处理器"""
        await self.handle_message(content, chat_id, sender_id, message_id)

    async def _analyze_task(self, task: str) -> Dict[str, Any]:
        """分析任务类型"""
        try:
            # 使用Claude分析任务
            analysis_result = await self._claude_client.analyze_task(task)

            if analysis_result.get('success'):
                return analysis_result
            else:
                # 使用备用分析
                return {
                    'success': True,
                    'analysis': analysis_result.get('fallback', {
                        'task_type': 'general',
                        'required_tools': [],
                        'steps': ['处理请求']
                    })
                }

        except Exception as e:
            self._logger.error(f"任务分析失败: {e}")
            return {
                'success': True,
                'analysis': self._claude_client._fallback_task_analysis(task)
            }

    async def _execute_task(
        self,
        task_analysis: Dict[str, Any],
        original_content: str,
        chat_id: str,
        sender_id: str,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """执行任务"""
        analysis = task_analysis.get('analysis', {})
        task_type = analysis.get('task_type', 'general')
        required_tools = analysis.get('required_tools', [])

        self._logger.info(f"执行任务 - 类型: {task_type}, 工具: {required_tools}")

        try:
            # 根据任务类型选择执行策略
            if task_type == 'document_generation' or 'document_generator' in required_tools:
                return await self._handle_document_generation(original_content, chat_id, history)

            elif task_type == 'web_browsing' or 'web_browsing' in required_tools:
                return await self._handle_web_browsing(original_content, chat_id, history)

            elif task_type == 'program_development' or 'code_developer' in required_tools:
                return await self._handle_code_development(original_content, chat_id, history)

            else:
                # 通用处理 - 直接使用Claude
                return await self._handle_general_query(original_content, chat_id, history)

        except Exception as e:
            self._logger.error(f"任务执行失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'message': f'处理请求时出错: {str(e)}'
            }

    async def _handle_document_generation(
        self,
        content: str,
        chat_id: str,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """处理文档生成任务"""
        self._logger.info("执行文档生成任务")

        # 使用Claude生成文档内容
        prompt = f"""根据以下需求生成文档内容（使用Markdown格式）：

{content}

请生成结构清晰、内容完整的文档。"""

        response = await self._claude_client.chat(prompt, history)

        if not response.get('success'):
            return response

        doc_content = response.get('content', '')

        # 生成Markdown文档
        doc_result = await self._document_generator.generate_markdown(
            doc_content,
            title="AI_Generated_Document"
        )

        if doc_result.get('success'):
            filepath = doc_result.get('filepath', '')
            filename = doc_result.get('filename', '')

            # 生成HTML版本
            html_result = await self._document_generator.generate_html(
                doc_content,
                title="AI_Generated_Document"
            )

            # 发送响应
            message = f"""文档生成完成！

**文档类型**: Markdown
**文件名**: {filename}
**文件路径**: {filepath}

文档内容预览：

---
{doc_content[:500]}{'...' if len(doc_content) > 500 else ''}
---

如需其他格式（Word、PDF），请告诉我。"""

            await self._feishu_bot.send_text_message(chat_id, message)

            return {
                'success': True,
                'content': message,
                'files': [doc_result.get('filename')]
            }
        else:
            # 发送纯文本响应
            await self._feishu_bot.send_text_message(
                chat_id,
                f"文档生成失败: {doc_result.get('error')}\n\n以下是生成的内容：\n\n{doc_content}"
            )
            return {'success': True, 'content': doc_content}

    async def _handle_web_browsing(
        self,
        content: str,
        chat_id: str,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """处理网络浏览任务"""
        self._logger.info("执行网络浏览任务")

        # 首先使用Claude理解用户意图
        intent_response = await self._claude_client.chat(
            f"分析以下请求，提取搜索关键词和意图：{content}\n\n请只返回搜索关键词，不要其他内容。",
            history
        )

        search_query = content  # 默认使用原始内容

        if intent_response.get('success'):
            response_content = intent_response.get('content', '')
            # 尝试提取关键词
            if '关键词' in response_content or 'keyword' in response_content.lower():
                # 简单提取
                lines = response_content.split('\n')
                for line in lines:
                    if line.strip() and not line.startswith('#'):
                        search_query = line.strip()
                        break

        await self._feishu_bot.send_text_message(
            chat_id,
            f"正在搜索: {search_query}"
        )

        # 执行搜索
        search_result = await self._web_browser.search(search_query, max_results=5)

        if not search_result.get('success'):
            await self._feishu_bot.send_text_message(
                chat_id,
                f"搜索失败: {search_result.get('error')}"
            )
            return search_result

        results = search_result.get('results', [])

        # 获取详细内容
        detailed_results = []
        for i, result in enumerate(results[:3], 1):
            title = result.get('title', '/')
            url = result.get('url', '')
            desc = result.get('description', '')

            await self._feishu_bot.send_text_message(
                chat_id,
                f"正在获取第 {i} 条结果: {title}"
            )

            page_result = await self._web_browser.fetch_page(url)

            if page_result.get('success'):
                detailed_results.append({
                    'title': title,
                    'url': url,
                    'description': desc,
                    'content': page_result.get('text', '')[:1000]  # 限制长度
                })

                await asyncio.sleep(0.5)  # 避免请求过快

        # 使用Claude整理结果
        summary_prompt = f"""请根据以下搜索结果，整理并回答用户的问题：
用户问题：{content}

搜索结果：
{json.dumps(detailed_results, ensure_ascii=False, indent=2)}

请给出结构清晰、准确的回答。"""

        summary_response = await self._claude_client.chat(summary_prompt, history)

        if summary_response.get('success'):
            answer = summary_response.get('content', '')

            # 添加搜索来源信息
            sources = "\n\n**信息来源：**\n"
            for result in results:
                sources += f"- [{result.get('title', '来源')}]({result.get('url', '')})\n"

            full_response = answer + sources

            await self._feishu_bot.send_text_message(chat_id, full_response[:2000])

            return {
                'success': True,
                'content': full_response,
                'sources': [r.get('url') for r in results]
            }
        else:
            await self._feishu_bot.send_text_message(
                chat_id,
                f"结果整理失败，以下是搜索结果摘要：\n\n{search_result}"
            )
            return {'success': True, 'content': str(search_result)}

    async def _handle_code_development(
        self,
        content: str,
        chat_id: str,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """处理代码开发任务"""
        self._logger.info("执行代码开发任务")

        # 生成代码
        code_result = await self._claude_client.chat(
            f"请根据以下需求编写代码：\n\n{content}\n\n请只返回代码，不要包含其他说明。",
            history
        )

        if not code_result.get('success'):
            return code_result

        code_content = code_result.get('content', '')

        # 分析代码语言
        language = 'python'  # 默认
        if code_content.strip().startswith('function') or code_content.strip().startswith('const') or code_content.strip().startswith('let'):
            language = 'javascript'
        elif code_content.strip().startswith('#include') or code_content.strip().startswith('using'):
            language = 'cpp'
        elif code_content.strip().startswith('package main'):
            language = 'go'

        # 尝试执行代码
        exec_result = await self._code_developer.execute_code(code_content, language)

        if exec_result.get('success'):
            output = exec_result.get('stdout', '')

            message = f"""代码执行成功！

**语言**: {language}
**输出**:
```
{output}
```

代码：
```{language}
{code_content}
```"""

            await self._feishu_bot.send_text_message(chat_id, message)

        else:
            error_output = exec_result.get('stderr', exec_result.get('error', ''))
            message = f"""代码生成如下，但执行时出现错误：

**语言**: {language}
**错误**: {error_output}

代码：
```{language}
{code_content}
```"""

            await self._feishu_bot.send_text_message(chat_id, message)

        return {
            'success': True,
            'content': code_content,
            'execution_result': exec_result
        }

    async def _handle_general_query(
        self,
        content: str,
        chat_id: str,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """处理通用查询"""
        self._logger.info("处理通用查询")

        response = await self._claude_client.chat(content, history)

        if response.get('success'):
            answer = response.get('content', '')
            # 检查是否包含Markdown格式
            if any(pattern in answer for pattern in ['**', '*\\*', '```', '###', '## ', '# ', '\u003e ', '- ']):
                # 包含Markdown，转换为飞书富文本
                rich_text_elements = _markdown_to_feishu_rich_text(answer)
                await self._feishu_bot.send_rich_text_message(chat_id, rich_text_elements)
            else:
                # 纯文本，发送简化为文本消息
                await self._feishu_bot.send_text_message(chat_id, answer)

            return {'success': True, 'content': answer}
        else:
            error_response = f"抱歉，我无法处理您的请求: {response.get('error', '未知错误')}"
            await self._feishu_bot.send_text_message(chat_id, error_response)

            return {'success': False, 'error': response.get('error')}

    def _get_conversation_history(self, chat_id: str) -> List[Dict[str, str]]:
        """获取对话历史"""
        if chat_id not in self._conversation_history:
            self._conversation_history[chat_id] = []
        return self._conversation_history[chat_id]

    async def auto_install_missing_packages(self) -> Dict[str, Any]:
        """自动检查并安装缺失的包"""
        self._logger.info("检查缺失的包...")

        required_packages = [
            'lark-oapi',
            'websockets',
            'fastapi',
            'uvicorn',
            'aiohttp',
            'beautifulsoup4',
            'markdown',
            'python-docx',
            'reportlab',
            'jinja2'
        ]

        success, messages = await self._package_installer.ensure_packages(required_packages)

        for msg in messages:
            self._logger.info(msg)

        return {
            'success': success,
            'messages': messages
        }

    async def auto_search_and_execute(self, query: str, chat_id: str) -> Dict[str, Any]:
        """在网上搜索满足用户需要的方法并自动执行"""
        self._logger.info(f"自动搜索并执行: {query}")

        await self._feishu_bot.send_text_message(
            chat_id,
            "正在网上搜索解决方案..."
        )

        # 搜索
        search_result = await self._web_browser.search(query, max_results=3)

        if not search_result.get('success'):
            return search_result

        results = search_result.get('results', [])

        # 获取第一个结果的内容
        if results:
            first_result = results[0]
            url = first_result.get('url', '')

            await self._feishu_bot.send_text_message(
                chat_id,
                f"正在获取解决方案: {first_result.get('title', '')}"
            )

            page_result = await self._web_browser.fetch_page(url)

            if page_result.get('success'):
                content = page_result.get('text', '')

                # 使用Claude分析和总结
                summary_response = await self._claude_client.chat(
                    f"请总结以下内容中的解决方案步骤：\n\n{content[:2000]}",
                    []
                )

                if summary_response.get('success'):
                    summary = summary_response.get('content', '')

                    await self._feishu_bot.send_text_message(
                        chat_id,
                        f"找到的解决方案：\n\n{summary}\n\n如需我帮助执行，请告诉我。"
                    )

                    return {
                        'success': True,
                        'solution': summary,
                        'source_url': url
                    }

        return {
            'success': False,
            'error': '未找到可行的解决方案'
        }

    async def start(self):
        """启动Agent"""
        self._logger.info("启动AI Agent...")

        # 检查并安装缺失的包
        if self._config.advanced.get('auto_package_install', True):
            await self.auto_install_missing_packages()

        # 启动飞书机器人
        await self._feishu_bot.start()

    async def stop(self):
        """停止Agent"""
        self._logger.info("停止AI Agent...")
        await self._feishu_bot.stop()


# 全局Agent实例
_agent_instance: Optional[AgentOrchestrator] = None


def get_agent(config: ConfigLoader = None) -> AgentOrchestrator:
    """获取全局Agent实例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = AgentOrchestrator(config)
    return _agent_instance
