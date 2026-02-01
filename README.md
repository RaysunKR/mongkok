# Mongkok AI Agent

一个全能AI Agent，用户可以通过飞书与这个AI Agent沟通，该Agent通过调用本地安装的Claude Code SDK满足用户的需求。

## 功能特性

- **文档生成**: 支持Markdown、HTML、Word、PDF等多种格式文档生成
- **网络浏览和信息收集**: 支持多个搜索引擎，自动收集和整理信息
- **程序开发**: 支持代码生成、执行、测试和分析
- **自动整理结果**: 结构化组织和呈现信息
- **安全性**: 用户权限控制、速率限制、内容过滤、命令安全检查
- **自动安装扩展**: 根据需要自动安装Python依赖包
- **在线搜索方法**: 可以在网上搜索满足用户需要的方法并自动执行
- **本地Claude Code**: 调用本地安装的Claude Code CLI，无需API密钥

## 前置要求

### 安装 Claude Code CLI

在使用本Agent之前，需要先安装Claude Code CLI：

```bash
# 安装 Claude Code
npm install -g @anthropic-ai/claude-code

# 验证安装
claude --version
```

详细安装说明请参考：https://docs.anthropic.com/en/docs/build-with-claude/claude-for-developers

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/mongkok/mongkok-agent.git
cd mongkok-agent/mongkok_agent
```

### 2. 安装Python依赖

```bash
pip install -r requirements.txt
```

或者使用自动安装:

```bash
python -m mongkok_agent.main --install-deps
```

### 3. 配置

编辑 `config/config.json` 文件，配置以下信息:

```json
{
  "feishu": {
    "app_id": "你的飞书应用ID",
    "app_secret": "你的飞书应用密钥",
    "encrypt_key": "加密密钥 (可选)",
    "verification_token": "验证令牌 (可选)"
  },
  "claude": {
    "cli_path": "",  // 留空自动查找，或指定Claude CLI路径
    "model": "claude-sonnet-4-20250514",
    "timeout_seconds": 120
  }
}
```

检查配置:

```bash
python -m mongkok_agent.main --check-config
```

## 使用

### 启动Agent

```bash
python -m mongkok_agent.main
```

或使用调试模式:

```bash
python -m mongkok_agent.main --debug
```

## 配置说明

完整配置说明请参考 `config/config.json` 文件。

### 飞书配置

- `app_id`: 飞书应用ID
- `app_secret`: 飞书应用密钥
- `encrypt_key`: 加密密钥 (设置_EVENT_v2加签时需要)
- `verification_token`: 验证令牌
- `server_port`: Webhook服务器端口 (默认8080)
- `host`: 服务器监听地址 (默认0.0.0.0)

### Claude配置

- `cli_path`: Claude CLI路径（留空则自动搜索常见路径）
- `model`: 使用的模型名称
- `timeout_seconds`: 执行超时时间（秒）

### 安全配置

- `allowed_users`: 允许访问的用户ID列表
- `rate_limit`: 速率限制配置
- `content_filter`: 内容过滤配置
- `command_whitelist`: 命令白名单
- `command_blacklist`: 命令黑名单

### 能力配置

- `document_generation`: 是否启用文档生成
- `web_browsing`: 是否启用网络浏览
- `program_development`: 是否启用程序开发
- `auto_install`: 是否启用自动安装扩展

## 使用示例

### 文档生成

在飞书中发送:
```
帮我写一份关于Python异步编程的文档
```

### 网络搜索

在飞书中发送:
```
搜索最新的人工智能发展趋势
```

### 代码开发

在飞书中发送:
```
帮我写一个Python脚本来批量重命名文件
```

### 综合查询

在飞书中发送任意问题，Agent会自动分析并选择合适的方式处理。

## 项目结构

```
mongkok_agent/
├── config/
│   └── config.json          # 配置文件
├── modules/
│   ├── agent.py             # Agent编排器
│   ├── claude_client.py     # Claude客户端（调用本地CLI）
│   ├── feishu_bot.py        # 飞书机器人
│   ├── document_generator.py # 文档生成模块
│   ├── web_browser.py       # 网络浏览模块
│   └── code_developer.py    # 代码开发模块
├── utils/
│   ├── config_loader.py     # 配置加载器
│   ├── logger.py            # 日志管理器
│   ├── security.py          # 安全管理器
│   └── package_installer.py # 包安装器
├── main.py                  # 主入口文件
├── requirements.txt         # 依赖列表
├── setup.py                 # 安装脚本
└── README.md               # 说明文档
```

## 依赖

### 必需依赖

- Python 3.8+
- Claude Code CLI (通过npm安装: `npm install -g @anthropic-ai/claude-code`)

### Python依赖

- lark-oapi (飞书SDK)
- fastapi (Web框架)
- uvicorn[standard] (ASGI服务器)
- aiohttp (异步HTTP)
- requests (同步HTTP)
- beautifulsoup4 (HTML解析)
- lxml (HTML解析引擎)
- markdown (Markdown支持)
- python-docx (Word文档)
- reportlab (PDF文档)
- jinja2 (模板引擎)
- python-dotenv (环境变量管理)

## 许可证

MIT License

## 联系方式

如有问题，请提交Issue。
