# Trace: Electron → TUI 迁移设计

**日期**: 2026-07-06
**状态**: 已通过头脑风暴，待写实现计划

## 1. 目标

把 Trace 的前端从 Electron 操作台完全替换为一个基于 **Textual** 的终端 UI (TUI)，让 Trace 从"课程作业形态的桌面应用"变成一个**纯 Python、可 `pipx`/`uvx` 安装的命令行产品**。目标用户是泡在终端里跑 Claude Code / Codex / Cursor 的开发者，TUI 是最贴合的形态。

后端(watcher / batcher / recorder / repository / handlers / SQLite / MCP)**核心逻辑不改**，只替换最外层的呈现与交互层。

## 2. 已定决策

1. **一体化进程**: `trace [--workspace X]` 单命令，启动即内嵌拉起 daemon 并展示 TUI；退出 TUI 即停止追踪。
2. **完全取代 Electron**: TUI 成为唯一前端，删除 `electron_app/`、Electron bridge、py2app/PyInstaller 打包、rumps/pystray 菜单栏、Tkinter workspace picker。
3. **Textual + 4 视图**: 复刻现有 GUI 的 Commits / Agents / Workspace / MCP 四个导航视图。
4. **完整功能平移**: 全部交互动作都搬(看 diff、恢复单文件、按 agent 撤销、模糊归因修正、MCP 一键安装、主题切换)；仅把动画版本图 SVG 降级为普通时间线列表。
5. **Windows 保留为官方支持平台**: 纯 Python + Textual 天生跨平台，watchdog/SQLite 本就跨平台，故不再需要为 Windows 单独打包/托盘。

## 3. 现状(迁移的起点)

- 前端: `electron_app/`(Vue 3 + Vite 渲染层) + `main.js`(~1500 行 Electron 主进程) + `electron_bridge.py`(子进程分发器)。
- 前端通过 spawn `TraceBridge`/python 子进程 + JSON stdin/stdout 调用后端的 `*_payload` 函数。
- 事件总线: `code/daemon/ipc.py` 的 `ui_queue` (queue.Queue) + `emit()` / `drain()`，daemon 线程投递 `new_commit` / `agent_changed` / `error` 事件。
- 入口: `code/main.py`，支持 `--workspace` / `--choose` / `--headless`；工作区选择用 Tkinter picker (`views/workspace_picker.py`)。
- 现有 UI 操作面(来自 App.vue，全部由进程内 Python 函数支撑):
  `list_commits` · `get_manifest(id)` · `get_prev_commit_id(id)` · `render_diff(path, prev, cur)` · `restore_file(commit, path)` · `list_agents` · `reassign_commit(id, agent)` · `preview_revert_agent(agent)` · `revert_agent(agent)` · `get_workspace_summary` · `list_mcp_setup` · `install_mcp_server(id)`。
- 底层实现分布: `core/repository.py`(查询)、`core/electron_diff_bridge.py`(`render_file_diff`)、`core/electron_restore_bridge.py`、`core/electron_reassign_bridge.py`、`core/electron_revert_agent_bridge.py`、`core/electron_init_bridge.py`、MCP 配置模块(`scripts/setup_cursor_mcp.py` 及 Electron MCP 逻辑)。

## 4. 目标架构

### 4.1 进程 / 线程模型

`trace [--workspace X]` 单进程:
- **主线程** = Textual App(事件循环 + 渲染)。
- **后台线程** = 现有 `DaemonManager`(watcher + batcher + recorder)，逻辑不改。
- 通信复用现有 `ipc.ui_queue`: daemon 线程 `emit(...)`，Textual 用 `set_interval(~0.5s)` 调 `drain()` 取事件刷新面板。等于把现在的"rumps.Timer / root.after drain"换成 Textual 定时器。
- 退出(`q` / Ctrl-C)→ 复用现有 signal 处理优雅停 daemon。

### 4.2 组件拆分(各自单一职责)

| 模块 | 职责 | 依赖 |
| --- | --- | --- |
| `code/tui/app.py` | `TraceApp`(Textual App): 挂载 4 Tab、全局快捷键、主题、启停 daemon、定时 drain IPC | Textual, controller, ipc |
| `code/tui/controller.py` | **进程内数据门面**: 把 UI 操作映射到现有后端函数，统一返回 `{ok, ...}`/`{ok:False, error}` | repository, `*_payload`, MCP 模块 |
| `code/tui/views/commits.py` | 左时间线列表 + 右 diff(+/−/meta 着色) + 低置信 commit 的归因修正面板 | controller |
| `code/tui/views/agents.py` | 统计卡 + agent 列表 + 按-agent 撤销(带预览确认) | controller |
| `code/tui/views/workspace.py` | workspace / db / commit / snapshot 概览键值表 | controller |
| `code/tui/views/mcp.py` | 各 agent 配置卡 + 一键安装 + 复制命令 | controller |
| `code/tui/widgets/` | 复用小组件(diff 渲染、agent 徽章配色、确认弹窗) | Textual |

**边界原则**: View 只依赖 `controller`，不直接 import repository / bridge；controller 是唯一把 UI 意图翻译成后端调用的地方，便于独立测试。

### 4.3 数据流

- **读**: View 激活 → `controller.list_commits()` 等 → 填充组件。
- **实时**: daemon `emit("new_commit", ...)` → `set_interval` drain → 若 Commits 面板活跃则刷新时间线 + 顶部状态提示。
- **写**(恢复 / 撤销 / 归因 / MCP 安装): View → `controller.xxx()` → 现有后端函数 → 成功后局部刷新 + 状态行提示。破坏性操作(恢复、按-agent 撤销)先弹 Textual 确认框(对齐现有 `window.confirm`)。

### 4.4 工作区选择

- 优先级复用现有 `utils/state`: `--workspace X` → 上次记忆 → 都没有则 TUI 内置目录选择屏(Textual `DirectoryTree`)。
- 删除 Tkinter picker (`views/workspace_picker.py`)。

## 5. 错误处理

- controller 层统一把后端异常包成 `{ok: False, error: str}`(对齐现有 bridge 返回约定)，View 在状态行/弹窗显示，**不崩 TUI**。
- daemon 线程异常 → `emit("error", ...)` → 状态行红字提示。
- 二进制 / 无 diff handler → 显示摘要行(复用现有 handler 输出)，不报错。

## 6. 打包 / 分发

- `pyproject.toml` 加 `textual` 运行时依赖；声明 `trace` 为 `console_scripts` 入口(指向 `code/main.py` 的 CLI)。
- 分发方式变为 `pipx install` / `uvx trace`(后续可加 brew formula)。
- **删除**: `setup.py`(py2app)、`Trace-windows.spec`(PyInstaller)、`scripts/build_macos_app.sh`、`scripts/build_windows_app.ps1`、`install.sh`、`.github/workflows/build-windows.yml`(改为纯 Python 测试 CI)。

## 7. 需要删除的现有资产

- `electron_app/` 整个目录。
- `code/electron_bridge.py`、`code/core/electron_*_bridge.py` 里**仅供子进程入口的 `main()`**(保留其中的 `*_payload` / `render_file_diff` 纯函数供 controller 直接调用)。
- `code/menubar/`(rumps/pystray 托盘) + `code/views/workspace_picker.py`(Tkinter)。
- Electron/打包相关测试: `test_electron_*.py`、`test_windows_startup.py` 里的 Electron 部分、`test_demo_and_packaging.py` 里针对 Electron 打包的断言。
- 打包脚本/spec(见 §6)。

## 8. 测试策略

- 现有后端测试(repository / watcher / batcher / handlers / detectors / mcp 等)**不动**。
- 新增 TUI 测试用 Textual 的 `Pilot`(`App.run_test()`): tab 切换、选 commit 看 diff、恢复确认流程、按-agent 撤销预览确认、MCP 安装成功/失败提示。
- controller 单测: 每个操作的 `{ok}` / `{ok:False,error}` 两条路径。
- 删除 Electron/打包相关测试(见 §7)。
- CI: 把 `build-windows.yml` 换成一个跨平台(macOS + ubuntu + windows)的纯 `unittest` 工作流。

## 9. 明确不做(YAGNI)

- 动画版本图 SVG → 普通时间线列表。
- "open github" 按钮 → 去掉。
- 脚本化 `--json` 子命令(`trace log/diff/restore`)→ 留 v2。
- daemon/attach 分离模式 → 留 v2(v1 是一体化)。

## 10. 后勤

- 工作目录: `~/trace`(`BUKOWSKIREAL/trace` 的克隆)，git 身份已设为化名 `bukowski <233685554+BUKOWSKIREAL@users.noreply.github.com>`。
- 原 `/Users/zhangruijia/final_project` 与外置盘上的 `trace_public` 不再作为本次迁移的工作目录。

## 11. 执行顺序(概要，细节见实现计划)

1. 脚手架: `pyproject` 加 textual、建 `code/tui/` 骨架、`controller` 门面(先包住现有后端函数)。
2. `TraceApp` + 4 空 Tab + daemon 启停 + IPC drain 打通。
3. 逐视图落地: Commits(含 diff/恢复/归因) → Agents(含撤销) → Workspace → MCP。
4. 工作区选择改造(去 Tkinter)。
5. 删除 Electron/托盘/打包资产 + 清理对应测试。
6. 新增 TUI/controller 测试；重做 CI。
7. 更新 README(中/英)与架构图,反映纯终端产品形态。
