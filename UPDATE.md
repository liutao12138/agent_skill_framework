# Agent Framework 功能更新说明

## 更新日期: 2026-02-12

本次更新实现了以下四个功能需求：

## 1. BaseTool.execute方法支持async执行

### 改动文件: `agent_framework/tools.py`

**新增功能:**
- `BaseTool._is_async()` 方法 - 检测execute方法是否为异步方法
- `ToolRegistry.execute_async()` 方法 - 异步执行工具
- `execute_tool_async()` 函数 - 异步执行工具的便捷函数
- 同步执行时会自动检测并正确处理异步方法

**使用示例:**
```python
# 异步工具定义
class AsyncFileTool(BaseTool):
    async def execute(self, path: str, **kwargs) -> str:
        # 异步读取文件
        return await async_read_file(path)

# 异步执行
result = await execute_tool_async("async_file_tool", path="test.txt")
```

## 2. 删除events.py中无用的_callbacks

### 改动文件: `agent_framework/events.py`

**删除内容:**
- `EventEmitter._callbacks` 列表属性
- `EventEmitter.add_callback()` 方法

**保留:**
- `_handlers` 列表和 `add_handler()`/`remove_handler()` 方法
- 事件发射和处理的完整功能

## 3. 工具结果截断逻辑

### 改动文件: `agent_framework/tools.py`

**新增功能:**
- `truncate_tool_result()` 函数 - 截断过长的工具结果
- 截断策略:
  - 硬上限: 10K字符
  - 上下文窗口30%: 默认使用硬上限
  - 保留头部50%和尾部50%的内容
  - 截断结果包含标记: `[... 内容被截断 (N 字符) ...]`

**配置常量:**
```python
TOOL_RESULT_HARD_LIMIT = 10 * 1024  # 10K字符
TOOL_RESULT_HEAD_RATIO = 0.5        # 头部保留50%
TOOL_RESULT_TAIL_RATIO = 0.5        # 尾部保留50%
```

**使用示例:**
```python
# 手动截断
truncated = truncate_tool_result(long_result, context_window=8000)
```

## 4. 工具结果占位符+变量替换传递机制

### 改动文件: `agent_framework/tools.py`, `agent_framework/agent.py`

**新增功能:**

#### A. MemoryTool (持久化存储 - 实例级隔离)
```python
# 创建MemoryTool实例 - 每个实例有独立的存储空间
tool1 = MemoryTool()
tool2 = MemoryTool()

# tool1存储的数据不会出现在tool2中
tool1.execute(action="set", key="data", value="value1")
result = tool2.execute(action="get", key="data")  # Not found

# 同一实例内可以正常使用
tool1.execute(action="set", key="search_result", value="/path/to/file.txt")
result = tool1.execute(action="get", key="search_result")  # /path/to/file.txt
```

**存储设计:**
- `MemoryTool` 实例：工具级别的隔离存储（每个实例独立）
- `${memory.KEY}` 引用：使用全局存储（跨工具调用共享）

#### B. 变量替换机制 (Agent._resolve_placeholders)

支持以下占位符格式:

1. **直接引用**: `${tool_result.N}` - 引用第N次工具执行结果
   ```python
   # 引用第0次工具结果
   {"path": "${tool_result.0}"}
   ```

2. **最后结果**: `${tool_result.last}` - 引用最后一次工具结果
   ```python
   {"path": "${tool_result.last}"}
   ```

3. **内存存储**: `${memory.KEY}` - 从MemoryTool获取存储的值
   ```python
   {"path": "${memory.search_result}"}
   ```

4. **自然语言引用**: Agent会自动解析工具参数中的描述并匹配之前的结果
   ```python
   # 例如: "用上一次grep返回的路径"
   ```

#### C. 系统提示更新

Agent的系统提示已更新，包含变量替换功能的使用说明。

**使用示例:**
```python
# 1. 先执行grep搜索
result = await agent.execute_tool("grep", pattern="def.*test")

# 2. 使用变量引用结果读取文件
# 在下一次工具调用中使用:
# {"path": "${tool_result.last}"}
# 或
# {"path": "用上一次grep返回的路径"}

# 3. 或使用MemoryTool持久化
memory_tool.execute(action="set", key="grep_path", value=result)
# 后续调用:
# {"path": "${memory.grep_path}"}
```

## 测试文件

- `tests/test_tools.py` - pytest单元测试
- `tests/manual_test.py` - 手动测试脚本

## 向后兼容性

所有改动均保持向后兼容:
- 同步工具无需修改即可工作
- 现有事件系统完全兼容
- 现有配置无需更改
