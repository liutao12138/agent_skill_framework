# Agent Framework

一个生产级的 AI Agent 框架，支持 Skills 机制、工具系统、子Agent、会话管理和事件通知。

## 特性

### 1. Skills 机制
- 外部化、可编辑的领域知识
- 渐进式披露 (Progressive Disclosure)
- YAML frontmatter + Markdown 格式
- 支持资源文件 (scripts, references, assets)

### 2. 工具系统
- 安全、受限的文件操作
- 工作空间限制
- 危险命令检测
- 超时控制

### 3. 子Agent
- 任务分解和专注执行
- 三种默认类型 (explore, code, plan)
- 工具访问控制

### 4. 会话管理
- 消息历史管理
- 元数据共享
- Token 统计
- 持久化支持

### 5. 事件通知
- 实时状态反馈
- 多种事件类型
- 可扩展的事件处理器

### 6. 多模型支持
- OpenAI 格式兼容
- MindIE 格式兼容
- 流式/非流式调用
- 自动重试机制

## 安装

```bash
# 克隆仓库
git clone https://github.com/your-repo/agent-framework.git
cd agent-framework

# 安装依赖
pip install -r requirements.txt
```

## 快速开始

### 1. 基础使用

```python
from agent_framework import Agent

# 创建 Agent
agent = Agent()

# 发送消息
result = agent.chat("Hello! How are you?")
print(result["content"])
```

### 2. 使用配置文件

```python
from agent_framework import create_agent

# 使用默认配置
agent = create_agent()

# 或使用自定义配置
from agent_framework import FrameworkConfig, Agent

config = FrameworkConfig()
config.model.base_url = "http://localhost:8000/v1"
config.model.model = "gpt-4"

agent = Agent(config=config)
```

## 配置文件

支持 YAML 和 JSON 格式:

```yaml
# config.yaml
version: "1.0.0"

model:
  provider: "openai"
  base_url: "http://localhost:8000/v1"
  api_key: "sk-your-key"
  model: "gpt-4"
  max_tokens: 4096
  temperature: 0.7
  stream: true

workspace:
  root_path: "./workspace"
  allow_outside: false

agent:
  name: "Assistant"
  description: "A powerful AI agent"
  max_iterations: 100

session:
  max_history_messages: 100
  session_ttl: 3600
  persist_sessions: true
```

## Skills

### 创建 Skill

在 `skills/` 目录下创建:

```
skills/
├── pdf/
│   └── SKILL.md
├── mcp-builder/
│   └── SKILL.md
└── code-review/
    └── SKILL.md
```

### SKILL.md 格式

```markdown
---
name: pdf
description: Process PDF files. Use when reading, creating, or merging PDFs.
version: 1.0.0
author: Agent Team
tags: [pdf, document, processing]
---

# PDF Processing Skill

This skill provides comprehensive PDF processing...

## Reading PDFs

Use `pdftotext` for quick extraction:

```bash
pdftotext input.pdf -
```
```

### 使用 Skill

```python
agent = Agent()

# 获取 Skill 内容
skill_content = agent.run_skill("pdf")
```

## 工具

### 内置工具

- `read_file`: 读取文件
- `write_file`: 写入文件
- `edit_file`: 编辑文件
- `bash`: 执行 Shell 命令
- `list_dir`: 列出目录
- `grep`: 搜索文件

### 自定义工具

```python
from agent_framework import BaseTool

class MyTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="my_tool",
            description="My custom tool"
        )
    
    def execute(self, param: str) -> str:
        # 实现逻辑
        return f"Result: {param}"

# 注册工具
agent.tool_registry.register(MyTool())
```

## 子Agent

### 使用子Agent

```python
from agent_framework import Agent, AgentType

agent = Agent()

# 使用探索者子Agent
result = agent.run_subagent(
    task="Explore the codebase and find Python files",
    agent_type=AgentType.EXPLORE
)

# 使用规划者子Agent
result = agent.run_subagent(
    task="Create a plan for implementing feature X",
    agent_type=AgentType.PLAN
)
```

### 子Agent 类型

| 类型 | 描述 | 工具 |
|------|------|------|
| explore | 探索代码库 | read_file, bash, grep |
| code | 代码实现 | 所有工具 |
| plan | 任务规划 | read_file, bash, grep |

## 事件系统

### 事件类型

```python
from agent_framework import EventType

# 模型事件
EventType.MODEL_START
EventType.MODEL_STOP

# 工具事件
EventType.TOOL_CALL_START
EventType.TOOL_RESULT
EventType.TOOL_CALL_STOP

# 子Agent事件
EventType.SUBAGENT_START
EventType.SUBAGENT_STOP

# 技能事件
EventType.SKILL_LOADED
```

### 自定义事件处理器

```python
from agent_framework import EventHandler, get_event_emitter

class MyHandler(EventHandler):
    def handle(self, event):
        print(f"Event: {event.type.value}")
        print(f"Data: {event.data}")

get_event_emitter().add_handler(MyHandler())
```

## 高级配置

### 环境变量

```bash
export AGENT_MODEL_BASE_URL="http://localhost:8000/v1"
export AGENT_MODEL_API_KEY="sk-your-key"
export AGENT_MODEL_MODEL="gpt-4"
export AGENT_WORKSPACE_ROOT_PATH="./workspace"
export AGENT_LOGGING_LEVEL="DEBUG"
```

### 自定义工作空间

```python
from agent_framework import ToolRegistry

registry = ToolRegistry(workspace_path="/custom/path")
```

## 目录结构

```
agent_framework/
├── __init__.py           # 主入口
├── config.py             # 配置管理
├── logger.py             # 日志系统
├── model_client.py       # 模型客户端
├── tools.py              # 工具系统
├── skill_loader.py       # Skills加载
├── sub_agent.py          # 子Agent
├── session.py            # 会话管理
├── events.py             # 事件系统
├── examples/             # 示例
│   └── example.py
├── skills/               # Skills
│   ├── pdf/
│   ├── mcp-builder/
│   ├── code-review/
│   └── python-dev/
└── config.yaml           # 配置文件
```

## 依赖

- Python 3.8+
- requests
- pyyaml
- dataclasses (Python 3.7+)

## 许可证

MIT License
