# CLAUDE.md

本项目是 Trace，一个 Python + SQLite + watchdog 的多 CLI Agent 协作版本追踪器。

## 常用命令

```bash
uv sync
uv run python -m unittest discover -s tests
uv run python code/main.py --workspace test_workspace
cd electron_app && npm start -- --workspace=../test_workspace
bash scripts/demo.sh
bash scripts/build_macos_app.sh
```

Electron 操作台：

```bash
cd electron_app
npm install
npm start -- --workspace=../test_workspace
```

MCP 服务器测试：

```bash
python run_mcp_server.py --workspace test_workspace
uv run python -m unittest tests.test_trace_mcp_server
```

## 项目约定

- Python 依赖通过 `uv` 管理，不要手动创建新的 venv 方案。
- `test_workspace/` 是本地演示目录，不进入版本控制。
- `.trace/` 是运行时仓库目录，不进入版本控制。
- `dist/` 和 `build/` 是打包产物目录，不进入版本控制。
- 文件版本存储以字节 blob 为准，handler 只负责 UI diff 展示。
- `.docx/.pptx/.xlsx/.pdf/image` 等格式有专门 handler；未知格式走 `BinaryHandler`。
- 修改 watcher、repository、batcher 时要跑完整测试。

## MCP 功能

- MCP 服务器位于 `code/mcp/trace_server.py`，提供 `trace_record_files` 工具。
- 项目根目录的 `.mcp.json` 为 Claude Code CLI 提供配置。
- `run_mcp_server.py` 是通用的 Python 包装脚本，自动设置 PYTHONPATH。
- `scripts/start_mcp_server.sh` 是 Bash 启动脚本。
- MCP 配置详见 `MCP_SETUP.md`。
- 修改 MCP 相关代码后必须运行 `tests/test_trace_mcp_server.py` 验证。

## 验证重点

- `Repository.commit()` 必须保持全量 manifest 语义。
- `checkout_commit()` 必须删除目标 manifest 中不存在的已跟踪文件。
- watcher 删除事件必须走 `kind="delete"`，不能被 modify 事件去重吞掉。
- 多 agent 防抖必须保持每个 agent 独立 timer。
- MCP 服务器必须能在不同 agent 环境（Claude、Codex、Cursor 等）中正常运行。
