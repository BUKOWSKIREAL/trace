# Trace — 分发说明

Trace Phase 6 后不再维护桌面应用打包链。项目的交付形态是纯 Python + Textual TUI，推荐通过 `uv` 开发运行，并通过 Python entry point 暴露 `trace` 命令。

## 本地开发运行

```bash
uv sync
uv run python code/main.py --workspace test_workspace
```

只运行后台守护进程：

```bash
uv run python code/main.py --workspace test_workspace --headless
```

## 命令行入口

`pyproject.toml` 声明了：

```toml
[project.scripts]
trace = "main:main"
```

安装项目后可运行：

```bash
trace --workspace /path/to/workspace
trace --choose
trace --workspace /path/to/workspace --headless
```

## CI

当前 CI 是纯 Python 跨平台测试：

```bash
uv run python -m unittest discover -s tests
```

`.github/workflows/tests.yml` 在 macOS、Linux、Windows 上运行同一套 unittest，不再构建桌面产物。

## 发布前检查清单

- [ ] `uv sync`
- [ ] `uv run python -m unittest discover -s tests`
- [ ] `bash scripts/demo.sh`
- [ ] `uv run python code/main.py --workspace test_workspace` 手动检查 TUI
- [ ] `uv run python code/main.py --workspace test_workspace --headless` 检查 daemon-only 路径
- [ ] `python run_mcp_server.py --workspace test_workspace` 检查 MCP server 可启动

## 已移除的旧交付形态

Phase 6 已删除旧桌面前端、系统托盘、平台安装器和对应构建脚本。Trace 的后续分发重点是 Python 包、`pipx`/`uvx` 体验和终端内交互。
