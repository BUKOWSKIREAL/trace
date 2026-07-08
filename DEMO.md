# Trace — Demo

> **多 CLI Agent 协作版本追踪器**：在本地监听工作区文件变化，自动识别 Claude Code / Codex / Cursor / OpenCode 等来源，按 agent 颗粒度记录版本，并在 **Textual TUI** 中查看时间线、diff、恢复和撤销操作。

## 5 分钟跑通演示

```bash
# 1. 进项目目录
cd /path/to/trace

# 2. 安装 Python 依赖（本项目默认用 uv 管理）
uv sync

# 3. 一键演示：启动 daemon、模拟文件变化、验证 SQLite 落库
bash scripts/demo.sh

# 4. 打开 Textual TUI 查看演示数据
uv run python code/main.py --workspace test_workspace
```

手动演示也可以拆成两个终端：

```bash
# 终端 1：启动 Trace TUI + 守护进程
uv run python code/main.py --workspace test_workspace

# 终端 2：进入工作区，跑 Claude Code / Codex 或直接改文件
cd test_workspace
echo "print('hello')" > demo.py
echo "print('hello, world')" > demo.py
```

TUI 中打开 **Commits** 视图即可看到新增版本和 diff。

## 界面

| 界面 | 启动 | 用途 |
|------|------|------|
| Textual TUI | `uv run python code/main.py --workspace test_workspace` | 时间线、diff、恢复、agent 统计、MCP 配置 |
| Headless CLI | `uv run python code/main.py --workspace test_workspace --headless` | SSH / E2E / 调试，只运行 watcher daemon |
| Workspace Picker | `uv run python code/main.py --choose` | 在终端里重新选择追踪目录 |

## 分发形态

Trace Phase 6 后只保留纯 Python / Textual 路径：

| 形态 | 命令 | 状态 |
|------|------|------|
| 源码运行 | `uv run python code/main.py --workspace <dir>` | 推荐开发方式 |
| 安装入口 | `trace --workspace <dir>` | 由 `pyproject.toml` 的 `project.scripts` 提供 |
| CI | `uv run python -m unittest discover -s tests` | macOS / Linux / Windows 纯 Python 测试 |

## 工程亮点

| 亮点 | 文件位置 |
|------|---------|
| 全量 manifest commit 模型 | `code/core/repository.py` |
| 内容寻址 blob 存储 | `code/core/storage.py` |
| 文件类型策略模式 | `code/core/handlers/` |
| Textual TUI | `code/tui/` |
| 每 agent 独立 timer 防抖 | `code/daemon/batcher.py` |
| watchdog 噪声过滤 | `code/daemon/watcher.py` |
| psutil / transcript / MCP 归因 | `code/daemon/attribution_resolver.py` |
| MCP server | `code/mcp/trace_server.py` |
| MCP 一键配置 | `code/mcp/setup.py` |

## 测试

```bash
uv run python -m unittest discover -s tests
```

测试覆盖 repository、watcher、batcher、activity recorder、detectors、handlers、MCP、TUI controller/views、工作区选择和多格式 diff。

## 已知限制

| 项 | 状态 |
|----|------|
| 旧版 `.ppt` | 可按二进制追踪和恢复，但没有 `.pptx` 的语义 diff |
| 文件权限位 | 当前按字节 blob 存储内容，不保存 `+x` 等权限位 |
| 复杂冲突解决 | Trace 负责本地时间线和恢复；复杂 merge 仍建议配合 Git |

## 截图

`screenshots/` 中保留了历史课程阶段截图；当前主界面以运行时 Textual TUI 为准。
