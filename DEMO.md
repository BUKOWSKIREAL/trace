# Trace — Demo

> **多 CLI Agent 协作版本追踪器**：在 macOS 后台运行守护进程，
> 自动识别工作目录里活跃的 Claude Code / Codex / OpenClaw，
> 按 agent 颗粒度记录文件变化，并在 Tk 或 Electron 操作台里查看时间线和 diff。

## 5 分钟跑通演示

```bash
# 1. 进项目目录
cd /path/to/final_project

# 2. 安装 Python 依赖（本项目默认用 uv 管理）
uv sync

# 3. 安装 Electron 操作台依赖（可选；不装也能用 Tk 操作台）
cd electron_app && npm install && cd ..

# 4. 一键演示：启动 daemon、模拟文件变化、验证 SQLite 落库
bash scripts/demo.sh
```

手动演示：

```bash
# 终端 1：启动菜单栏 + 守护进程
uv run python code/main.py --workspace test_workspace

# 终端 2：进入工作区，跑 Claude Code 或直接改文件
cd test_workspace
echo "print('hello')" > demo.py
echo "print('hello, world')" > demo.py

# 屏幕右上角菜单栏出现Trace图标后，点击：
# 打开操作台 (Electron) ⚡
# 或打开操作台 (Tk)
```

退出：菜单栏点“退出”，或终端 1 按 Ctrl+C。

## 界面

| 界面 | 启动 | 用途 | 风格 |
|------|------|------|------|
| 菜单栏 | `uv run python code/main.py` | 日常常驻，控制 daemon | macOS 状态栏图标 + 下拉菜单 |
| Electron 操作台 | 菜单栏点“打开操作台 (Electron) ⚡” | 唯一操作台 | Vue + 版本图 + ambiguous 修正 / agent 撤销 |
| Electron 操作台 | 菜单栏点“打开操作台 (Electron) ⚡” 或 `cd electron_app && npm start` | 演示主推 | Vue 3 + Vite renderer，scottjg.com 风格：磷光绿、L 形角、终端 prompt header |
| Headless CLI | `uv run python code/main.py --headless` | SSH / E2E / 调试 | 纯日志输出 |

## 发布与打包

| 形态 | 命令 | 状态 |
|------|------|------|
| macOS `.app` | `bash scripts/build_macos_app.sh` | 已提供 `setup.py` + py2app 构建脚本 |
| macOS `.dmg` | `bash scripts/build_macos_app.sh` | 本机有 `create-dmg` 时自动生成 |
| 源码安装 fallback | `./install.sh` | py2app 或 create-dmg 不可用时创建 `dist/Trace.command` |
| Windows `.exe` | PyInstaller 依赖已声明 | 代码层兼容，仍需 Windows 真机验证 |
| CLI | `uv run python code/main.py --headless` | 跨平台 |

## 演示卖点

| 卖点 | 演示动作 |
|------|----------|
| 真识别 CLI agent | 在 workspace 里运行 `claude` / `codex` 改文件，daemon 自动归属 agent |
| 多 agent 场景 | 同时用不同 CLI agent 改不同文件，时间线按 agent 着色 |
| 强制 agent 覆盖 | 菜单栏 radio 切到 “Claude Code”，后续变化按 Claude Code 归属 |
| 暂停跟踪 | 菜单栏点“暂停跟踪”，文件变化不再进入 batcher |
| 工作区热切 | 菜单栏“更换工作区...”选新目录，daemon 不重启进程直接切换 |
| 全文件类型存储 | `.py` / `.md` / `.docx` / `.png` 都进入 blob；文本显示 diff，二进制显示大小和 hash |
| 历史可查 | 操作台时间线选 commit 后显示对应 diff |

## 工程亮点

| 亮点 | 文件位置 |
|------|---------|
| 全量 manifest commit 模型 | `code/core/repository.py` |
| 内容寻址 blob 存储 | `code/core/storage.py` |
| 文件类型策略模式 | `code/core/handlers/` |
| 每 agent 独立 timer 防抖 | `code/daemon/batcher.py` |
| watchdog 噪声过滤 | `code/daemon/watcher.py` |
| psutil 会话级 agent 归属 | `code/daemon/detectors/cli_detector.py` |
| Tray 跨平台抽象 | `code/menubar/tray_base.py` |
| DaemonManager 工作区热切 | `code/daemon/manager.py` |
| Electron 操作台 | `electron_app/` |
| macOS 打包 | `setup.py` + `scripts/build_macos_app.sh` |

## 测试

```bash
uv run python -m unittest discover -s tests
# 期望：Ran N tests OK
```

测试分布：

| 文件 | 项数 | 覆盖 |
|------|------|------|
| `test_handlers.py` | 15 | FileHandler / TextHandler / BinaryHandler / Registry |
| `test_detectors_cli.py` | 10 | psutil + cwd 过滤 + Windows .exe + 异常吞掉 |
| `test_repository.py` | 15 | manifest 模型 / 并发 commit / 连接缓存 / 构造副作用 |
| `test_e2e_smoke.py` | 1 | subprocess 起 main.py 真改文件验 SQLite |
| `test_path_deduper.py` | 7 | `(path, kind)` 联合 key 含红绿对照 |
| `test_workspace_resolution.py` | 10 | state 持久化 + resolve_workspace 四段优先级 |
| `test_tray.py` | 29 | Tray ABC + RumpsTray + 菜单图标 + PystrayTray stub + schedule_periodic |
| `test_menubar_app.py` | 36 | TraceApp / 菜单 / 图标 / callback / 热切 / Tk pump / Electron 启动 |
| `test_electron_renderer.py` | 5 | Electron Vue/Vite renderer 导航 / chip / IPC 点击契约 |
| `test_console_window.py` | 18 | ConsoleWindow 生命周期 + Timeline / Diff 集成 |
| `test_diff_view.py` | 9 | DiffView 渲染 / 新增/删除/修改 / handler 异常容错 |
| `test_timeline_view.py` | 10 | TimelineView 行渲染 / 选中回调 / agent 着色 |
| `test_daemon_manager.py` | 7 | DaemonManager start / stop / restart 生命周期 |
| `test_watcher_handler.py` | 8 | paused / override_agent 状态字段 |
| `test_demo_and_packaging.py` | 5 | DEMO 文档 + py2app / fallback 打包交付物 |
| `test_docx_handler.py` | 16 | Word 文档提取 / diff / 注册 / 坏包容错 |
| `test_pptx_handler.py` | 17 | PowerPoint 文本提取 / 备注 / diff / 注册 |
| `test_xlsx_handler.py` | 18 | Excel 单元格 / 多 sheet / 公式 / diff / 注册 |
| `test_pdf_handler.py` | 14 | PDF 文本提取 / diff / 注册 / 坏文件容错 |
| `test_image_handler.py` | 19 | 图片元数据 / hash / diff / 注册 |
| **合计** | **以本地 unittest 输出为准** | - |

## 已知限制

| 项 | 状态 |
|----|------|
| Windows 真机验证 | 代码层兼容，PystrayTray 仍是 stub，需要 Windows 机器补实测 |
| Windows `.exe` | PyInstaller 依赖已声明，未在 Windows 环境实际产出 |
| 选择性按 agent 撤销 | 需要 3-way merge 策略，本期不做 |
| 离线变化补偿 | 守护进程退出期间的变化不补扫，本期不做 |
| 文件权限位 | 当前按字节 blob 存储内容，不保存 `+x` 等权限位；恢复脚本后需手动确认 |

## 截图

`screenshots/` 目录包含：

- `week13_phase4_scottjg_theme.png`：Tk 操作台 darkly 主题
- `week13_electron_first.png`：Electron 操作台
- `week13_console_diff.png`：Tk 操作台 timeline + diff
- `week13_claude_headless_evidence.txt`：Claude Code daemon 归属证据

---
