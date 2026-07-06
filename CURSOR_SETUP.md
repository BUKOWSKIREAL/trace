# Cursor 完整配置指南

本文档提供 Cursor 编辑器中配置 Trace MCP 服务器的详细步骤和使用说明。

## 快速配置

### 方法 1：自动配置（推荐）

使用配置助手脚本自动设置：

```bash
python scripts/setup_cursor_mcp.py
```

脚本会：
1. 自动检测你的操作系统
2. 找到 Cursor 配置文件位置
3. 提示你输入工作区路径（默认项目根目录）
4. 写入正确的 MCP 配置

非交互式使用（用于自动化）：

```bash
python scripts/setup_cursor_mcp.py --workspace /path/to/workspace --auto-confirm
```

### 方法 2：手动配置

#### 1. 找到 Cursor 配置文件

根据你的操作系统，打开对应的配置文件：

- **macOS**: `~/Library/Application Support/Cursor/User/mcp.json`
- **Linux**: `~/.config/Cursor/User/mcp.json`
- **Windows**: `%APPDATA%\Cursor\User\mcp.json`

如果文件不存在，创建一个新文件。

#### 2. 添加 Trace MCP 配置

在 `mcp.json` 中添加以下内容（替换路径为实际路径）：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "/absolute/path/to/project/.venv/bin/python",
      "args": [
        "/absolute/path/to/project/run_mcp_server.py",
        "--workspace",
        "/absolute/path/to/workspace"
      ]
    }
  }
}
```

**注意**：必须使用绝对路径。Windows 用户可把 `command` 写成 `py`，这也是自动配置脚本在 Windows 上的默认值。

示例（macOS）：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "/Users/username/projects/trace/.venv/bin/python",
      "args": [
        "/Users/username/projects/trace/run_mcp_server.py",
        "--workspace",
        "/Users/username/projects/my-workspace"
      ]
    }
  }
}
```

示例（Windows）：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "py",
      "args": [
        "C:\\Users\\username\\projects\\trace\\run_mcp_server.py",
        "--workspace",
        "C:\\Users\\username\\projects\\my-workspace"
      ]
    }
  }
}
```

#### 3. 重启 Cursor

保存配置文件后，完全退出并重新启动 Cursor。

## 验证配置

### 检查 MCP 工具是否可用

在 Cursor 的 AI 聊天中，你可以要求 AI 使用 MCP 工具：

```
请使用 trace_record_files 工具报告你修改的文件
```

如果配置正确，AI 应该能够调用该工具。

### 查看 Trace 活动日志

修改文件后，检查工作区的活动日志：

```bash
cat /path/to/workspace/.trace/trace_activity.jsonl
```

你应该看到类似这样的记录：

```json
{"timestamp": 1718123456.789, "agent": "cursor", "files": ["src/main.py"], "operation": "write", "source": "mcp", "confidence": 1.0}
```

### 使用 Electron 操作台验证

启动 Electron 操作台：

```bash
cd electron_app
npm start -- --workspace=/path/to/workspace
```

在"Timeline"页面中，你应该能看到标记为 "cursor" 的提交记录。

## 在 Cursor 中使用

### AI 自动调用

如果 Cursor 支持主动调用 MCP 工具，AI 会在修改文件后自动调用 `trace_record_files`。

### 手动提示 AI

如果需要，你可以在提示中明确要求：

```
修改这个文件，并使用 trace_record_files 工具报告变更
```

### 工具参数说明

`trace_record_files` 工具接受以下参数：

- **agent** (必需): 设为 `"cursor"`
- **files** (必需): 修改的文件路径列表（相对或绝对路径）
- **operation** (可选): 操作类型，如 `"write"`, `"create"`, `"delete"`, `"rename"`
- **confidence** (可选): 置信度 0-1，默认 1.0

示例调用：

```json
{
  "agent": "cursor",
  "files": ["src/main.py", "tests/test_main.py"],
  "operation": "write",
  "confidence": 0.95
}
```

## 工作原理

1. **Cursor AI 修改文件** → 触发文件系统变更
2. **AI 调用 MCP 工具** → `trace_record_files(agent="cursor", files=[...])`
3. **MCP 服务器记录** → 写入 `workspace/.trace/trace_activity.jsonl`
4. **Trace Watcher 检测** → 文件系统事件触发
5. **归因解析器查询** → 优先使用 MCP 记录
6. **创建提交** → 标记为 "cursor" 的变更

## 高级配置

### 使用特定 Python 解释器

如果你有多个 Python 版本，可以指定完整路径：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "/usr/local/bin/python3.11",
      "args": [
        "/path/to/project/run_mcp_server.py",
        "--workspace",
        "/path/to/workspace"
      ]
    }
  }
}
```

### 使用虚拟环境

如果项目使用虚拟环境：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "/path/to/project/.venv/bin/python",
      "args": [
        "/path/to/project/run_mcp_server.py",
        "--workspace",
        "/path/to/workspace"
      ]
    }
  }
}
```

### 传统配置方式（手动设置 PYTHONPATH）

如果包装脚本不工作，可以使用传统方式：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp.trace_server", "--workspace", "/path/to/workspace"],
      "env": {
        "PYTHONPATH": "/path/to/project/code"
      },
      "cwd": "/path/to/project"
    }
  }
}
```

## 故障排除

### 问题：Cursor 找不到 MCP 工具

**可能原因**：
1. 配置文件路径错误
2. JSON 格式错误
3. 未重启 Cursor

**解决方案**：
1. 检查配置文件位置是否正确
2. 使用 JSON 验证器检查语法
3. 完全退出并重启 Cursor

### 问题：MCP 服务器启动失败

**可能原因**：
1. Python 路径错误
2. run_mcp_server.py 路径错误
3. 缺少依赖

**解决方案**：
1. 测试命令是否能手动运行：
   ```bash
   /path/to/project/.venv/bin/python /path/to/project/run_mcp_server.py --workspace /path/to/workspace
   ```
   Windows 可用：
   ```powershell
   py C:\path\to\project\run_mcp_server.py --workspace C:\path\to\workspace
   ```
2. 检查项目依赖：
   ```bash
   uv sync
   ```

### 问题：trace_record_files 调用成功但没有记录

**可能原因**：
1. 工作区路径错误
2. .trace 目录权限问题

**解决方案**：
1. 确认工作区路径与 Trace 监控的路径一致
2. 检查 .trace 目录是否存在且可写：
   ```bash
   ls -la /path/to/workspace/.trace/
   ```

### 问题：文件变更被归因为 "human" 而非 "cursor"

**可能原因**：
1. MCP 记录未生效
2. 时间窗口错误（记录过期）

**解决方案**：
1. 检查 trace_activity.jsonl 是否有记录
2. 确保 AI 在修改文件后立即调用工具
3. 检查系统时间是否正确

### 问题：多个 Agent 同时运行时归因错误

**解决方案**：
1. 确保每个 agent 都配置了 MCP
2. 使用不同的 agent 名称（cursor, claude, codex）
3. 检查 MCP 记录的时间戳是否正确

## 查看调试信息

### 检查 MCP 服务器日志

MCP 服务器通过 stdio 通信，日志可能在 Cursor 的开发者工具中：

1. 在 Cursor 中按 `Cmd+Shift+P` (macOS) 或 `Ctrl+Shift+P` (Windows/Linux)
2. 输入 "Developer: Toggle Developer Tools"
3. 查看 Console 标签页

### 检查活动记录

```bash
# 查看最近的 MCP 记录
tail -20 /path/to/workspace/.trace/trace_activity.jsonl

# 实时监控
tail -f /path/to/workspace/.trace/trace_activity.jsonl
```

### 测试 MCP 服务器

直接测试服务器是否能启动：

```bash
uv run python run_mcp_server.py --workspace test_workspace
```

服务器应该持续运行，等待 stdio 输入。按 Ctrl+C 退出。

## 性能优化

### MCP 记录有效期

默认情况下，MCP 记录在 10 分钟（600 秒）后过期。如果需要调整：

修改 `code/daemon/trace_activity.py` 中的 `max_age` 参数：

```python
TraceActivityStore(workspace, max_age=300.0)  # 5 分钟
```

### 减少不必要的调用

只在实际修改文件时调用 `trace_record_files`，不要在每次查询或读取时调用。

## 与其他工具集成

### 同时使用 Cursor 和 Claude Code

两个 agent 可以同时配置 MCP，使用不同的 agent 名称：

- Cursor: `agent="cursor"`
- Claude Code: `agent="claude"`

Trace 会正确区分它们的文件变更。

### 与 Git 集成

Trace 的提交独立于 Git。你可以：
1. 使用 Trace 查看详细的 agent 活动历史
2. 定期创建 Git 提交保存重要里程碑

## 最佳实践

1. **明确的文件路径**：传递绝对路径或工作区相对路径，避免歧义
2. **及时报告**：修改文件后立即调用 MCP 工具，不要延迟
3. **正确的 operation**：使用合适的操作类型（write/create/delete/rename）
4. **合理的 confidence**：如果不确定是否修改了文件，降低置信度
5. **批量报告**：一次调用报告多个文件，而非多次调用

## 参考资料

- [MCP_SETUP.md](../MCP_SETUP.md) - 通用 MCP 配置指南
- [README.md](../README.md) - 项目概览
- [Cursor 官方文档](https://cursor.sh/docs) - Cursor 编辑器文档

## 技术支持

如有问题：
1. 查看 [MCP_SETUP.md](../MCP_SETUP.md) 的故障排除章节
2. 运行测试：`uv run python -m unittest tests.test_trace_mcp_server`
3. 检查项目 issues: https://github.com/your-repo/issues
