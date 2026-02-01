import asyncio
import json
import re
from typing import Dict, Any, Optional, Callable, List
from lark_oapi import Client
from lark_oapi.core.enum import LogLevel
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.event.custom import CustomizedEventProcessor, CustomizedEvent
from lark_oapi.event.dispatcher_handler import EventException
from lark_oapi.ws.client import Client as WSClient
from ..utils.logger import get_logger
from ..utils.config_loader import ConfigLoader
from ..utils.security import SecurityManager


def _markdown_to_feishu_rich_text(markdown: str) -> List[Dict[str, Any]]:
    """将Markdown转换为飞书富文本格式

    飞书富文本使用特定的元素结构，需要将Markdown语法转换为对应的飞书元素
    返回的元素可以直接用于 Feishu post 消息的 content 中
    """
    elements = []
    lines = markdown.split('\n')
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        i += 1

        # 跳过空行
        if not line or line.isspace():
            continue

        # 处理标题 #
        if line.strip().startswith('#'):
            stripped = line.lstrip()
            level = 0
            while level < len(stripped) and stripped[level] == '#':
                level += 1
            title = stripped[level:].strip()
            elements.append({
                "tag": "heading",
                "heading_level": min(level, 6),
                "elements": [{
                    "tag": "text",
                    "text": title
                }]
            })
        # 处理代码块 ```
        elif line.strip().startswith('```'):
            code_type = 'plain'
            code_match = re.match(r'```(\w*)', line.strip())
            if code_match:
                code_type = code_match.group(1) or 'plain'

            # 收集代码内容
            code_lines = []
            while i < n:
                code_line = lines[i]
                if code_line.strip().startswith('```'):
                    i += 1
                    break
                code_lines.append(code_line)
                i += 1

            code_content = '\n'.join(code_lines).rstrip()
            elements.append({
                "tag": "code",
                "language": code_type,
                "elements": [{
                    "tag": "text",
                    "text": code_content
                }]
            })
        # 处理无序列表 - * 或 + 或 -
        elif re.match(r'^\s*[\-\*+]\s+', line):
            match = re.match(r'^(\s*)[\-\*+]\s+(.+)$', line)
            if match:
                indent_spaces = len(match.group(1))
                list_content = match.group(2).strip()
                elements.append({
                    "tag": "unordered_list",
                    "indent": indent_spaces // 2,
                    "elements": [{
                        "tag": "text",
                        "text": list_content
                    }]
                })
        # 处理有序列表 1. 2.
        elif re.match(r'^\s*\d+\.\s+', line):
            match = re.match(r'^\s*\d+\.\s+(.+)$', line)
            if match:
                list_content = match.group(1).strip()
                elements.append({
                    "tag": "ordered_list",
                    "indent": 0,
                    "elements": [{
                        "tag": "text",
                        "text": list_content
                    }]
                })
        # 处理引用 >
        elif re.match(r'^\s*>\s+', line):
            quote_content = re.sub(r'^\s*>\s+', '', line)
            elements.append({
                "tag": "quote",
                "elements": [{
                    "tag": "text",
                    "text": quote_content
                }]
            })
        # 普通段落
        else:
            # 处理行内Markdown语法，构建元素列表
            line_elements = []
            pos = 0
            remaining = line

            # 处理加粗 **text**
            while remaining:
                bold_match = re.search(r'\*\*([^*]+)\*\*', remaining)
                italic_match = re.search(r'(?<!\*)\*([^*]+)\*(?!\*)', remaining)
                link_match = re.search(r'\[([^\]]+)\]\(([^\)]+)\)', remaining)

                # 找到最前面的匹配
                next_pos = len(remaining)
                next_type = None
                next_match = None

                if bold_match:
                    if bold_match.start() < next_pos:
                        next_pos = bold_match.start()
                        next_type = 'bold'
                        next_match = bold_match
                if italic_match:
                    if italic_match.start() < next_pos:
                        next_pos = italic_match.start()
                        next_type = 'italic'
                        next_match = italic_match
                if link_match:
                    if link_match.start() < next_pos:
                        next_pos = link_match.start()
                        next_type = 'link'
                        next_match = link_match

                # 添加匹配前的普通文本
                if next_pos > 0:
                    text_part = remaining[:next_pos]
                    if text_part:
                        line_elements.append({
                            "tag": "text",
                            "text": text_part
                        })

                # 处理匹配
                if next_type == 'bold':
                    line_elements.append({
                        "tag": "text",
                        "style": {"bold": True},
                        "text": next_match.group(1)
                    })
                    remaining = remaining[next_match.end():]
                elif next_type == 'italic':
                    line_elements.append({
                        "tag": "text",
                        "style": {"italic": True},
                        "text": next_match.group(1)
                    })
                    remaining = remaining[next_match.end():]
                elif next_type == 'link':
                    line_elements.append({
                        "tag": "a",
                        "text": next_match.group(1),
                        "href": next_match.group(2)
                    })
                    remaining = remaining[next_match.end():]
                else:
                    # 没有更多匹配，添加剩余文本
                    if remaining:
                        line_elements.append({
                            "tag": "text",
                            "text": remaining
                        })
                    break

            # 如果只有一个纯文本元素，简化结构
            if len(line_elements) == 1 and line_elements[0]["tag"] == "text" and "style" not in line_elements[0]:
                elements.append({
                    "tag": "text",
                    "text": line_elements[0]["text"]
                })
            elif line_elements:
                # 多个元素或包含格式，使用段落包裹
                elements.append({
                    "tag": "paragraph",
                    "elements": line_elements
                })

    return elements

class FeishuBot:
    """飞书机器人模块 - 使用WebSocket长连接方式对接"""

    def __init__(self, config: ConfigLoader = None):
        self._config = config or ConfigLoader()
        self._logger = get_logger('FeishuBot')
        self._security = SecurityManager(self._config)

        feishu_config = self._config.feishu

        # 飞书客户端配置
        self._app_id = feishu_config.get('app_id', '')
        self._app_secret = feishu_config.get('app_secret', '')
        self._encrypt_key = feishu_config.get('encrypt_key', '')
        self._verification_token = feishu_config.get('verification_token', '')
        self._bot_name = feishu_config.get('bot_name', 'AI Agent')

        # 初始化飞书客户端（用于发送消息）
        self._client = Client.builder() \
            .app_id(self._app_id) \
            .app_secret(self._app_secret) \
            .log_level(LogLevel.INFO) \
            .build()

        # 事件处理器
        self._message_handlers: Dict[str, Callable] = {}
        self._default_handler: Optional[Callable] = None

        # WebSocket客户端
        self._ws_client: Optional[WSClient] = None
        self._event_handler: Optional[EventDispatcherHandler] = None
        self._running = False

        self._logger.info(f"FeishuBot (WebSocket长连接模式) 初始化完成: {self._bot_name}")

    def _setup_event_handler(self) -> EventDispatcherHandler:
        """设置事件处理器"""
        self._logger.info("设置事件处理器...")

        # 创建事件分发器 builder
        handler_builder = EventDispatcherHandler.builder(
            self._encrypt_key,
            self._verification_token,
            LogLevel.INFO
        )

        # 注册 P1 消息接收事件处理器
        self._logger.info("注册 P1 自定义事件处理器: im.message.receive_v1")
        handler_builder.register_p1_customized_event("im.message.receive_v1", self._handle_message_event)

        # 注册 P2 消息接收事件处理器（WebSocket可能发送P2格式）
        self._logger.info("注册 P2 自定义事件处理器: im.message.receive_v1")
        handler_builder.register_p2_customized_event("im.message.receive_v1", self._handle_message_event_p2)

        # 注册忽略其他事件的处理器（避免日志错误）
        ignore_events = [
            ("p2", "im.chat.access_event.bot_p2p_chat_entered_v1"),
            ("p2", "im.message.message_read_v1"),
        ]
        for schema, event_type in ignore_events:
            self._logger.info(f"注册忽略事件处理器: {schema}.{event_type}")
            handler_builder.register_p2_customized_event(event_type, self._handle_ignored_event)

        self._logger.info("事件处理器注册完成")

        # 构建实际的事件处理器
        handler = handler_builder.build()
        self._logger.info("事件处理器构建完成")

        self._logger.info(f"已注册的处理器: {list(handler._processorMap.keys())}")
        return handler

    def _handle_ignored_event(self, event: CustomizedEvent) -> None:
        """忽略不需要处理的事件"""
        self._logger.debug(f"忽略事件: {event.header.event_type if event.header else 'unknown'}")

    def _handle_message_event(self, event: CustomizedEvent) -> None:
        """处理消息事件 (P1)"""
        try:
            self._logger.info("收到P1消息事件")

            # P1格式的event直接从event.event获取
            event_data = event.event if event.event else {}

            # 输出完整的原始事件数据（便于调试）
            self._logger.info(f"P1事件uuid: {event.uuid}, type: {event.type}")
            self._logger.info(f"P1事件数据: {json.dumps(event_data, ensure_ascii=False, indent=2)}")

            # 获取消息详情
            message_id = event_data.get('message', {}).get('message_id', '')
            chat_id = event_data.get('message', {}).get('chat_id', '')
            sender_id = event_data.get('sender', {}).get('sender_id', {}).get('user_id', '')
            sender_type = event_data.get('sender', {}).get('sender_id', {}).get('sender_type', '')
            message_type = event_data.get('message', {}).get('message_type', '')

            self._logger.info(f"消息详情 - 类型: {message_type}, 发送者类型: {sender_type}, 发送者ID: {sender_id}, 消息ID: {message_id}, 聊天ID: {chat_id}")

            # 用户权限检查
            self._logger.info(f"检查用户权限: {sender_id}")
            permission = self._security.check_user_permission(sender_id)
            if not permission.allowed:
                self._logger.warning(f"权限被拒绝: {permission.reason}")
                asyncio.create_task(self.send_text_message(
                    chat_id,
                    f"抱歉，您没有使用权限: {permission.reason}"
                ))
                return
            self._logger.info("权限检查通过")

            # 速率限制检查
            self._logger.info(f"检查速率限制: {sender_id}")
            allowed, reason = self._security.check_rate_limit(sender_id)
            if not allowed:
                self._logger.warning(f"速率限制触发: {reason}")
                asyncio.create_task(self.send_text_message(
                    chat_id,
                    f"请求过于频繁，请稍后再试: {reason}"
                ))
                return
            self._logger.info("速率限制检查通过")

            # 获取消息内容
            self._logger.info(f"解析消息内容, message_type: {message_type}")
            content = self._get_message_content(event_data)
            self._logger.info(f"消息内容: {content[:200] if content else '(空)'}")

            # 调用处理器
            handler = self._message_handlers.get(message_type, self._default_handler)
            self._logger.info(f"查找处理器 - 消息类型: {message_type}, 使用处理器: {'default' if handler == self._default_handler else message_type}")

            if handler:
                self._logger.info("异步调用消息处理器")
                asyncio.create_task(
                    handler(
                        message_type=message_type,
                        content=content,
                        chat_id=chat_id,
                        sender_id=sender_id,
                        message_id=message_id,
                        raw_event=event_data
                    )
                )
            else:
                self._logger.warning(f"未找到消息类型处理器: {message_type}")

        except Exception as e:
            self._logger.error(f"处理消息事件失败: {e}")

    def _handle_message_event_p2(self, event: CustomizedEvent) -> None:
        """处理消息事件 (P2)"""
        try:
            self._logger.info("收到P2消息事件")

            # P2格式的event直接从event.event获取（也是个字典）
            event_data = event.event if event.event else {}

            # 输出完整的原始事件数据（便于调试）
            self._logger.info(f"P2事件schema: {event.schema}, header.event_type: {event.header.event_type if event.header else 'None'}")
            self._logger.info(f"P2事件数据: {json.dumps(event_data, ensure_ascii=False, indent=2)}")

            # 获取消息详情 - P2格式的路径
            message_id = ''
            chat_id = ''
            sender_id = ''
            sender_type = ''
            message_type = ''

            # P2格式的message在event内部
            if 'message' in event_data:
                message_field = event_data['message']
                if isinstance(message_field, dict):
                    message_id = message_field.get('message_id', '')
                    chat_id = message_field.get('chat_id', '')
                    message_type = message_field.get('message_type', '')

            # 获取发送者信息
            if 'sender' in event_data:
                sender_field = event_data['sender']
                if isinstance(sender_field, dict) and 'sender_id' in sender_field:
                    sid = sender_field['sender_id']
                    if isinstance(sid, dict):
                        sender_id = sid.get('user_id', '')
                        sender_type = sid.get('sender_type', '')

            self._logger.info(f"P2消息详情 - 类型: {message_type}, 发送者ID: {sender_id}, 消息ID: {message_id}, 聊天ID: {chat_id}")

            # 用户权限检查
            self._logger.info(f"P2检查用户权限: {sender_id}")
            permission = self._security.check_user_permission(sender_id)
            if not permission.allowed:
                self._logger.warning(f"权限被拒绝: {permission.reason}")
                asyncio.create_task(self.send_text_message(
                    chat_id,
                    f"抱歉，您没有使用权限: {permission.reason}"
                ))
                return
            self._logger.info("权限检查通过")

            # 速率限制检查
            self._logger.info(f"P2检查速率限制: {sender_id}")
            allowed, reason = self._security.check_rate_limit(sender_id)
            if not allowed:
                self._logger.warning(f"速率限制触发: {reason}")
                asyncio.create_task(self.send_text_message(
                    chat_id,
                    f"请求过于频繁，请稍后再试: {reason}"
                ))
                return
            self._logger.info("速率限制检查通过")

            # 获取消息内容
            self._logger.info(f"P2解析消息内容, message_type: {message_type}")
            content = self._get_message_content_p2(event_data)
            self._logger.info(f"P2消息内容: {content[:200] if content else '(空)'}")

            # 调用处理器
            handler = self._message_handlers.get(message_type, self._default_handler)
            self._logger.info(f"P2查找处理器 - 消息类型: {message_type}, 使用处理器: {'default' if handler == self._default_handler else message_type}")

            if handler:
                self._logger.info("P2异步调用消息处理器")
                asyncio.create_task(
                    handler(
                        message_type=message_type,
                        content=content,
                        chat_id=chat_id,
                        sender_id=sender_id,
                        message_id=message_id,
                        raw_event=event_data
                    )
                )
            else:
                self._logger.warning(f"P2未找到消息类型处理器: {message_type}")

        except Exception as e:
            self._logger.error(f"处理P2消息事件失败: {e}", exc_info=True)

    def _get_message_content_p2(self, event_dict: Dict[str, Any]) -> str:
        """获取P2格式消息内容"""
        try:
            # P2格式: event_dict 直接包含 message 和 sender
            if 'message' not in event_dict:
                self._logger.warning(f"P2事件数据中没有message字段: {list(event_dict.keys())}")
                return ""

            message = event_dict['message']
            if not isinstance(message, dict):
                return ""

            # 获取content字段 - P2中content是JSON字符串
            content_str = message.get('content', '')
            if not content_str:
                return ""

            # 解析JSON格式的content
            if isinstance(content_str, str):
                try:
                    content_data = json.loads(content_str)
                except json.JSONDecodeError:
                    # 如果不是JSON，直接返回
                    return content_str
            else:
                content_data = content_str

            # 获取message_type
            message_type = message.get('message_type', '')

            self._logger.debug(f"P2内容解析 - message_type: {message_type}, content_data: {content_data}")

            # 根据消息类型提取文本
            if message_type == 'text':
                return content_data.get('text', '')
            elif message_type == 'post':
                content_list = content_data.get('post', {}).get('zh_cn', {}).get('content', [])
                text_parts = []
                for item in content_list:
                    for segment in item.get('text', {}).get('elements', []):
                        text_parts.append(segment.get('text_run', {}).get('content', ''))
                return ''.join(text_parts)
            else:
                # 其他类型尝试直接返回text字段或转为字符串
                if 'text' in content_data:
                    return content_data.get('text', '')
                return json.dumps(content_data, ensure_ascii=False)

        except Exception as e:
            self._logger.error(f"P2解析消息内容失败: {e}")
            return ""

    def _get_message_content(self, event: Dict[str, Any]) -> str:
        """获取消息内容"""
        try:
            content_str = event.get('message', {}).get('content', '')

            if isinstance(content_str, str):
                content_data = json.loads(content_str)
            else:
                content_data = content_str if isinstance(content_str, dict) else {}

            # 根据消息类型提取文本
            message_type = event.get('message', {}).get('message_type', '')

            if message_type == 'text':
                return content_data.get('text', '')
            elif message_type == 'post':
                content_list = content_data.get('post', {}).get('zh_cn', {}).get('content', [])
                text_parts = []
                for item in content_list:
                    for segment in item.get('text', '').get('elements', []):
                        text_parts.append(segment.get('text_run', {}).get('content', ''))
                return ''.join(text_parts)
            else:
                return str(content_data)

        except Exception as e:
            self._logger.error(f"解析消息内容失败: {e}")
            return ""

    def register_handler(self, message_type: str, handler: Callable):
        """注册消息处理器"""
        self._message_handlers[message_type] = handler
        self._logger.info(f"注册处理器: {message_type}")

    def set_default_handler(self, handler: Callable):
        """设置默认处理器"""
        self._default_handler = handler
        self._logger.info("设置默认消息处理器")

    async def send_text_message(
        self,
        chat_id: str,
        text: str,
        reply_message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """发送文本消息"""
        try:
            from lark_oapi.api.im.v1.model.create_message_request import CreateMessageRequest
            from lark_oapi.api.im.v1.model.create_message_request_body import CreateMessageRequestBody

            # 清理文本内容
            # 移除控制字符，保留换行符
            import re
            # 保留可打印字符、中文、换行符
            cleaned_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
            # 限制长度（飞书文本消息限制是20000字符）
            if len(cleaned_text) > 20000:
                cleaned_text = cleaned_text[:19997] + '...'
                self._logger.warning(f"消息内容过长，已截断到20000字符")

            if not cleaned_text:
                cleaned_text = "(无内容)"

            self._logger.info(f"准备发送消息，长度: {len(cleaned_text)}, 内容预览: {cleaned_text[:50]}")

            # 构建消息体
            req_body_content = {
                "text": cleaned_text
            }

            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("text") \
                .content(json.dumps(req_body_content, ensure_ascii=False)) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            response = self._client.im.v1.message.create(request)

            if response.code == 0:
                self._logger.info(f"消息发送成功: chat_id={chat_id}")
                return {
                    'success': True,
                    'message_id': response.data.message_id,
                    'chat_id': chat_id
                }
            else:
                self._logger.error(f"消息发送失败: code={response.code}, msg={response.msg}")
                return {
                    'success': False,
                    'error': response.msg,
                    'code': response.code
                }

        except Exception as e:
            self._logger.error(f"发送消息异常: {e}")
            return {'success': False, 'error': str(e)}

    async def send_card_message(
        self,
        chat_id: str,
        card_content: Dict[str, Any],
        reply_message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """发送卡片消息"""
        try:
            from lark_oapi.api.im.v1.model.create_message_request import CreateMessageRequest
            from lark_oapi.api.im.v1.model.create_message_request_body import CreateMessageRequestBody

            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("interactive") \
                .content(json.dumps(card_content, ensure_ascii=False)) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            response = self._client.im.v1.message.create(request)

            if response.code == 0:
                self._logger.info(f"卡片消息发送成功: chat_id={chat_id}")
                return {
                    'success': True,
                    'message_id': response.data.message_id,
                    'chat_id': chat_id
                }
            else:
                self._logger.error(f"卡片消息发送失败: {response.msg}")
                return {
                    'success': False,
                    'error': response.msg,
                    'code': response.code
                }

        except Exception as e:
            self._logger.error(f"发送卡片消息异常: {e}")
            return {'success': False, 'error': str(e)}

    async def send_rich_text_message(
        self,
        chat_id: str,
        elements: list,
        reply_message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """发送富文本消息"""
        try:
            from lark_oapi.api.im.v1.model.create_message_request import CreateMessageRequest
            from lark_oapi.api.im.v1.model.create_message_request_body import CreateMessageRequestBody

            # 使用post消息类型，构建飞书富文本格式
            post_content = {
                "post": {
                    "zh_cn": {
                        "title": [],
                        "content": elements
                    },
                    "zh_cn_v2": {
                        "title": [],
                        "content": elements
                    }
                }
            }

            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("post") \
                .content(json.dumps(post_content, ensure_ascii=False)) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            response = self._client.im.v1.message.create(request)

            if response.code == 0:
                self._logger.info(f"富文本消息发送成功: chat_id={chat_id}")
                return {
                    'success': True,
                    'message_id': response.data.message_id,
                    'chat_id': chat_id
                }
            else:
                self._logger.error(f"富文本消息发送失败: code={response.code}, msg={response.msg}")
                return {
                    'success': False,
                    'error': response.msg,
                    'code': response.code
                }

        except Exception as e:
            self._logger.error(f"发送富文本消息异常: {e}")
            return {'success': False, 'error': str(e)}

    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """获取用户信息"""
        try:
            from lark_oapi.api.contact.v3.model.get_user_request import GetUserRequest

            request = GetUserRequest.builder() \
                .user_id(user_id) \
                .build()

            response = self._client.contact.v3.user.get(request)

            if response.code == 0 and response.data:
                return {
                    'success': True,
                    'user_name': response.data.name,
                    'user_id': user_id,
                    'avatar': {}
                }
            else:
                return {
                    'success': False,
                    'error': response.msg
                }

        except Exception as e:
            self._logger.error(f"获取用户信息失败: {e}")
            return {'success': False, 'error': str(e)}

    async def _run_ws_client(self):
        """运行WebSocket客户端（异步版本）"""
        self._event_handler = self._setup_event_handler()

        self._ws_client = WSClient(
            app_id=self._app_id,
            app_secret=self._app_secret,
            log_level=LogLevel.INFO,
            event_handler=self._event_handler,
            auto_reconnect=True
        )

        self._logger.info(f"启动飞书WebSocket客户端: {self._bot_name}")

        # 使用nest_asyncio处理嵌套事件循环问题
        # lark-oapi的WSClient内部有自己的事件循环，需要特殊处理
        try:
            # 检查是否已有事件循环在运行
            try:
                loop = asyncio.get_running_loop()
                self._logger.info("检测到已有事件循环在运行")
            except RuntimeError:
                loop = None

            if loop is not None:
                # 已有事件循环，尝试导入nest_asyncio
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    self._logger.info("已应用nest_asyncio")
                except ImportError:
                    self._logger.warning("nest_asyncio未安装，尝试同步启动WebSocket")

                # 使用线程在独立的事件循环中运行WebSocket客户端
                def run_ws():
                    try:
                        self._ws_client.start()
                    except Exception as e:
                        self._logger.error(f"WebSocket线程运行异常: {e}")

                import threading
                ws_thread = threading.Thread(target=run_ws, daemon=True)
                ws_thread.start()
                self._logger.info("WebSocket客户端已在线程中启动")

                # 等待连接建立或失败
                await asyncio.sleep(2)

                # 保持主线程运行
                while self._running:
                    await asyncio.sleep(60)

            else:
                # 没有事件循环，直接启动
                self._ws_client.start()

        except asyncio.CancelledError:
            self._logger.info("WebSocket客户端被取消")
        except Exception as e:
            self._logger.error(f"WebSocket运行异常: {e}")
            raise

    async def start(self):
        """启动飞书机器人（WebSocket长连接模式）"""
        if self._running:
            self._logger.warning("WebSocket客户端已在运行")
            return

        self._running = True
        self._logger.info("=" * 50)
        self._logger.info("启动飞书机器人 (WebSocket长连接模式)")
        self._logger.info(f"Bot名称: {self._bot_name}")
        self._logger.info(f"App ID: {self._app_id}")
        self._logger.info("=" * 50)

        await self._run_ws_client()

    async def stop(self):
        """停止飞书机器人"""
        self._running = False
        if self._ws_client:
            self._logger.info("停止飞书WebSocket客户端")
            try:
                if hasattr(self._ws_client, '_disconnect'):
                    await self._ws_client._disconnect()
            except:
                pass
