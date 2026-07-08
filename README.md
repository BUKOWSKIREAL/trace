# Trace

> **中文** · [English](README.en.md)

Trace 是一个面向 AI 编程协作场景的本地版本追踪工具。它不替代 Git，而是补充 Git：当你同时使用 Claude Code、Codex CLI、Cursor、OpenCode 等工具修改同一个项目时，Trace 会在本地记录“哪个 agent 在什么时候改了哪些文件”，并把每次变化保存成可以查看 diff、恢复文件、撤销某个 agent 修改的快照。

Trace 现在是一个纯 Python + Textual TUI 产品：一个命令同时启动后台 watcher 和终端界面，退出 TUI 即停止追踪。

## 核心目标

- **看得清来源**：区分人类手动修改、Claude、Codex、Cursor 等不同来源的文件变化。
- **找得到过程**：把短时间内连续发生的文件变化合并成一次版本记录，方便回看每一步。
- **能安全恢复**：在 Textual TUI 中查看 diff，并把单个文件或某个 agent 的修改恢复到之前状态。

## 架构

![Trace 架构图](assets/architecture.svg)

捕获文件变化 → 过滤噪声 → 等待文件稳定 → 通过 MCP/活动/transcript/进程证据归因 → 按 agent 防抖批量提交 → 持久化到 SQLite 与内容寻址 blob → Textual TUI 进程内读取展示。

## 快速开始

```bash
uv sync
uv run python code/main.py --workspace test_workspace
```

如果不传 `--workspace`，Trace 会优先使用上次记录的工作区；没有记录时会打开 Textual 内置目录选择器。

常用命令：

```bash
# 跑完整测试
uv run python -m unittest discover -s tests

# 一键演示：生成 test_workspace/.trace 数据
bash scripts/demo.sh

# 只跑后台守护进程，不打开 TUI
uv run python code/main.py --workspace test_workspace --headless

# 强制重新选择工作区
uv run python code/main.py --choose
```

安装为命令行入口后也可以运行：

```bash
trace --workspace /path/to/workspace
```

## TUI 功能

Textual TUI 提供四个视图：

- **Commits**：查看时间线、每次提交的文件 diff、恢复单个文件、修正低置信归因。
- **Agents**：查看 agent 活动统计，预览并撤销某个 agent 的文件级贡献。
- **Workspace**：查看当前工作区、数据库路径、commit/snapshot/agent 计数。
- **MCP**：检查 Codex、Claude Code、OpenCode 等配置状态，并执行一键安装。

Trace 支持文本、Office 文档、PDF、图片和未知二进制文件的版本记录；常见文本和文档格式会显示更友好的 diff 摘要。

## Trace MCP 接口

Trace 提供一个本地 stdio MCP server，供 Codex、Claude Code、Cursor、OpenCode 等 agent 主动申报自己改过的文件。Codex 还可以配套安装 Trace hooks，在 PreToolUse / PostToolUse 阶段自动记录 `apply_patch`、`Write`、`Edit` 和 `Bash` 产生的文件变化，避免多个 agent 同时运行时只能被动猜测归属。

申报记录会写入 workspace 的 `.trace/trace_activity.jsonl`，归因器会优先使用这些记录；没有申报时才回退到 transcript / 进程扫描。

### 快速配置

**Claude Code CLI**：项目根目录的 `.mcp.json` 会被自动读取，无需额外配置。

**Cursor**：一键自动配置（推荐）

```bash
python scripts/setup_cursor_mcp.py
```

详细配置请参考 [CURSOR_SETUP.md](CURSOR_SETUP.md)。

或手动配置，在全局 MCP 配置文件中添加；Windows 可把 `command` 改成 `py`：

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

**Codex CLI**：在 `~/.codex/config.toml` 添加：

```toml
[mcp_servers.trace]
command = "/path/to/project/.venv/bin/python"
args = ["-m", "mcp.trace_server", "--workspace", "/path/to/workspace"]

[mcp_servers.trace.env]
PYTHONPATH = "/path/to/project/code"
```

也可以在 TUI 的 **MCP** 视图中使用一键安装，它会替换旧的 `trace` section，避免 workspace 指向旧路径。详细配置和故障排除请参考 [MCP_SETUP.md](MCP_SETUP.md)。

### MCP Tool

- `trace_record_files(agent, files, operation="write", confidence=1.0)`

agent 每次写文件前后调用一次即可，例如把 `agent` 设为 `codex`、`claude`、`cursor`，`files` 传 workspace 相对路径或绝对路径列表。

### Codex Hooks

Codex hook 模块（自动调用 MCP）：

- `hooks.trace_codex_hook --workspace /path/to/workspace --phase pre`
- `hooks.trace_codex_hook --workspace /path/to/workspace --phase post`

TUI 的 MCP 视图会一键写入 `~/.codex/config.toml` 和 `~/.codex/hooks.json`。重启 Codex 后，在 Codex 中运行 `/hooks` 并信任 Trace hook 一次即可生效。

## 项目布局

```text
code/             Python source（daemon / repository / handlers / TUI / MCP）
tests/            unittest 测试
scripts/          demo、自测与 MCP 辅助脚本
prompts/          开发提示词记录
screenshots/      历史演示截图
assets/           架构图等静态资源
dist/             本地构建输出（gitignored）
test_workspace/   本地演示工作区（gitignored）
```

## 测试

```bash
uv run python -m unittest discover -s tests
```

测试覆盖 repository、watcher、batcher、activity recorder、agent detector、handler、MCP、TUI controller/views、工作区选择和多文件类型 diff。

## 已知限制

- 旧版 `.ppt` 可以按二进制追踪与恢复，但没有 `.pptx` 的语义 diff。
- 文件权限位暂不保存；例如脚本的 `+x` 恢复后需要手动确认。
- 复杂的多人/多 agent 冲突解决仍建议配合 Git 使用。

## License

[MIT](LICENSE)
