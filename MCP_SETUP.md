# Trace MCP Server 配置指南

Trace 项目通过 MCP (Model Context Protocol) 允许各种 AI coding agents 主动报告文件修改，从而提高归因准确性。

## 快速开始

### 在 Claude Code CLI 中使用

Claude Code 会自动读取项目根目录的 `.mcp.json` 配置文件。无需额外配置。

### Cursor 配置

推荐运行配置助手：

```bash
python scripts/setup_cursor_mcp.py
```

脚本默认把 workspace 设置为项目根目录；Windows 会写入 `py` 启动器。
也可以手动打开 Cursor 的 MCP 配置文件：
   - macOS: `~/Library/Application Support/Cursor/User/mcp.json`
   - Linux: `~/.config/Cursor/User/mcp.json`
   - Windows: `%APPDATA%\Cursor\User\mcp.json`

然后添加以下配置（替换路径为实际路径；Windows 可把 `command` 改成 `py`）：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "/path/to/project/.venv/bin/python",
      "args": ["/path/to/project/run_mcp_server.py", "--workspace", "/path/to/your/workspace"],
      "cwd": "/path/to/project"
    }
  }
}
```

### Codex CLI 配置

推荐使用 Electron 操作台的 MCP 页面一键写入 `~/.codex/config.toml` 和
`~/.codex/hooks.json`；它会替换旧的 `trace` section，避免 workspace 指向旧路径。

手动配置时，在 `~/.codex/config.toml` 添加：

```toml
[mcp_servers.trace]
command = "/path/to/project/.venv/bin/python"
args = ["-m", "mcp.trace_server", "--workspace", "/path/to/workspace"]

[mcp_servers.trace.env]
PYTHONPATH = "/path/to/project/code"
```

### 在其他 Agent 环境中使用

对于支持 MCP 的其他 agent 环境：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "/path/to/project/.venv/bin/python",
      "args": ["-m", "mcp.trace_server", "--workspace", "/path/to/workspace"],
      "env": {
        "PYTHONPATH": "/path/to/project/code"
      }
    }
  }
}
```

或者使用包装脚本（推荐）：

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "/path/to/project/.venv/bin/python",
      "args": ["/path/to/project/run_mcp_server.py", "--workspace", "/path/to/workspace"]
    }
  }
}
```

## 工作原理

1. **Agent 调用 MCP 工具**：当 AI agent 修改文件时，它调用 `trace_record_files` 工具。
2. **记录活动**：MCP 服务器将活动记录到 `workspace/.trace/trace_activity.jsonl`。
3. **归因解析**：Trace 的 `AttributionResolver` 读取这些记录，优先使用 MCP 报告而非被动进程扫描。

## 可用工具

### trace_record_files

报告 agent 修改的文件，以便 Trace 准确归因。

**参数：**
- `agent` (string, 必需): Agent 标识符，例如 "codex", "claude", "cursor"
- `files` (array, 必需): 相对或绝对文件路径列表
- `operation` (string, 可选): 操作类型，如 "write", "create", "delete", "rename"，默认 "write"
- `confidence` (number, 可选): 0-1 之间的置信度分数，默认 1.0

**示例：**
```json
{
  "agent": "cursor",
  "files": ["src/main.py", "tests/test_main.py"],
  "operation": "write",
  "confidence": 0.95
}
```

## 测试

测试 MCP 服务器是否正常工作：

```bash
# 方法 1: 使用包装脚本
uv run python run_mcp_server.py --workspace test_workspace

# 方法 2: 使用 bash 脚本
bash scripts/start_mcp_server.sh --workspace test_workspace

# 方法 3: 直接使用 Python 模块
PYTHONPATH=code uv run python -m mcp.trace_server --workspace test_workspace
```

## 故障排除

### 问题：ModuleNotFoundError: No module named 'mcp'

**解决方案：** 确保 `PYTHONPATH` 包含项目的 `code` 目录，或使用提供的包装脚本。

### 问题：ModuleNotFoundError: No module named 'daemon'

**解决方案：** 确保从项目根目录运行，并且 `code` 目录在 Python 路径中。

### 问题：Agent 无法连接到 MCP 服务器

**解决方案：**
1. 检查 `.mcp.json` 配置文件路径是否正确
2. 确保 `command` 和 `args` 使用绝对路径
3. Codex 配置中必须给 `mcp.trace_server` 设置 `PYTHONPATH=/path/to/project/code`
4. 如果旧配置指向了旧 workspace，使用 Electron 操作台 MCP 页面重新一键添加
5. 查看 agent 的日志文件获取详细错误信息

### 问题：工作区路径错误

**解决方案：** 确保 `--workspace` 参数指向正确的工作区目录，该目录应包含或将要包含 `.trace` 子目录。

## 技术细节

- **协议版本**: MCP 2024-11-05
- **传输方式**: stdio (标准输入/输出)
- **存储格式**: JSONL (每行一个 JSON 对象)
- **活动记录寿命**: 默认 10 分钟 (600 秒)
- **存储位置**: `workspace/.trace/trace_activity.jsonl`

## 相关文件

- `code/mcp/trace_server.py` - MCP 服务器实现
- `code/daemon/trace_activity.py` - 活动存储逻辑
- `code/daemon/attribution_resolver.py` - 归因解析器
- `run_mcp_server.py` - Python 包装脚本
- `scripts/start_mcp_server.sh` - Bash 包装脚本
- `.mcp.json` - Claude Code MCP 配置
- `tests/test_trace_mcp_server.py` - 单元测试
