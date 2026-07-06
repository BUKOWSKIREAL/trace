# Trace — 打包说明

## 打包产物（已完成 ✅）

| 产物 | 路径 | 大小 | 用途 |
|------|------|------|------|
| **macOS .app** | `dist/Trace.app` | 118 MB | 双击启动的原生应用 |
| **macOS .dmg** | `dist/Trace-macOS.dmg` | 51 MB | 分发安装包（压缩） |
| **Windows portable** | `dist/Trace/Trace.exe` | Windows 构建后生成 | 系统托盘主程序 |
| **Windows bridge** | `dist/Trace/TraceBridge.exe` | Windows 构建后生成 | Electron 调 Python diff/restore 和 MCP 的桥接程序 |
| **源码启动器** | `dist/Trace.command` | 81 B | fallback：双击启动源码版 |

## 构建方式

### 方式 1：macOS 完整打包

```bash
bash scripts/build_macos_app.sh
```

**流程**：
1. `uv sync` 同步 Python 依赖
2. Vite 构建 Vue renderer，随后 `electron-builder` 构建 Electron 操作台
3. `python setup.py py2app` 构建菜单栏 .app
4. 把 `Trace Console.app` 嵌入 `Trace.app/Contents/Resources/electron/`
5. 用 ad-hoc `codesign` 重新封装外层 `Trace.app`
6. `create-dmg` 生成 .dmg（需提前 `brew install create-dmg`）
7. 失败时自动 fallback 到 `install.sh`

**产物**：
- ✅ `dist/Trace.app` — 原生 macOS 应用
- ✅ `dist/Trace-macOS.dmg` — 分发安装包

### 方式 2：Windows 完整打包（需 Windows）

```powershell
pwsh .\scripts\build_windows_app.ps1
```

**流程**：
1. `uv sync --frozen` 同步 Python 依赖
2. Vite 构建 Vue renderer，随后 `electron-builder --win --dir` 构建 Electron 操作台
3. `PyInstaller` 读取 `Trace-windows.spec` 构建 `Trace.exe` 和 `TraceBridge.exe`
4. 把 `Trace Console.exe` 所在的 `win-unpacked` 目录嵌入 `dist\Trace\electron\`
5. 校验 `Trace.exe`、`TraceBridge.exe`、`electron\Trace Console.exe` 都存在，并用 `TraceBridge.exe mcp.trace_server` 做一次 TraceBridge MCP 握手

**产物**：
- ✅ `dist\Trace\Trace.exe` — Windows 系统托盘主程序
- ✅ `dist\Trace\TraceBridge.exe` — Electron diff/restore/MCP Python bridge
- ✅ `dist\Trace\electron\Trace Console.exe` — 内嵌 Electron 操作台

### 方式 3：源码安装 fallback

```bash
bash install.sh
```

**流程**：
1. `uv sync` 同步 Python 依赖
2. `cd electron_app && npm install` 安装 Electron / Vue / Vite 依赖（可选）
3. 创建 `dist/Trace.command` 启动器

**产物**：
- ✅ `dist/Trace.command` — 双击启动源码版

## 使用方式

### 使用 .dmg 安装（推荐）

1. 双击 `dist/Trace-macOS.dmg`
2. 拖动 `Trace.app` 到 `Applications` 文件夹
3. 从 Launchpad 或 Applications 启动

### 直接使用 .app

```bash
open dist/Trace.app
```

或双击 `dist/Trace.app`

### 使用源码启动器

```bash
./dist/Trace.command
```

或双击 `dist/Trace.command`

### 命令行启动（开发/调试）

```bash
uv run python code/main.py --workspace test_workspace
```

## 技术细节

### py2app 配置（setup.py）

**关键配置**：
- `LSUIElement: True` — 无 Dock 图标（菜单栏应用）
- `argv_emulation: False` — 禁用参数模拟（避免冲突）
- 显式包含：`watchdog`, `psutil`, `rumps`, `ttkbootstrap`, `PIL`, `docx`, `fitz`, `openpyxl`, `pptx`
- 显式框架：`libffi`, `libsqlite3`, `libtcl`, `libtk`（Tkinter 依赖）

**自定义 py2app 命令**（`TracePy2AppCommand`）：
- 清空 `install_requires` 避免 py2app 0.28 的 PEP 621 元数据冲突
- 依赖管理由 `pyproject.toml` + `uv.lock` 负责

### create-dmg 配置

```bash
create-dmg \
    --volname "Trace" \
    --window-size 520 320 \
    --app-drop-link 360 160 \
    "dist/Trace-macOS.dmg" \
    "dist/Trace.app"
```

**参数说明**：
- `--volname` — 卷标名称（Finder 侧边栏显示）
- `--window-size` — 安装窗口大小
- `--app-drop-link` — 自动创建 Applications 快捷方式

## 验证清单

- [x] `.app` 可双击启动
- [x] Electron 操作台已嵌入主 `Trace.app`
- [x] 外层 `.app` 在嵌入 Electron 后重新 ad-hoc 签名
- [x] 菜单栏图标正常显示
- [x] 可选择工作区
- [x] 可打开 Tk 操作台
- [x] 可打开 Electron 操作台
- [x] `.dmg` 可正常挂载
- [x] 从 `.dmg` 拖动到 Applications 后可启动
- [x] `Trace.command` fallback 可用

## 已知限制

| 项 | 状态 |
|----|------|
| Windows `.exe` | PyInstaller spec 和构建脚本已补齐，需 Windows 真机执行与验收 |
| Linux 打包 | pystray 托盘菜单已实现，需 Linux 真机验证 |
| 代码签名 | 本地 ad-hoc 签名；正式分发需 Apple Developer ID |
| 公证 | 未公证（需 Apple Developer ID + notarytool） |

## 故障排查

### py2app 构建失败

**症状**：`python setup.py py2app` 报错

**解决**：
1. 检查 `uv sync` 是否成功
2. 检查 Python 版本（推荐 3.13）
3. 查看完整日志：`python setup.py py2app 2>&1 | tee build.log`
4. 使用 fallback：`bash install.sh`

### create-dmg 失败

**症状**：`create-dmg` 命令不存在或报错

**解决**：
1. 安装：`brew install create-dmg`
2. 检查 `.app` 是否存在：`ls -la dist/Trace.app`
3. 手动删除旧 DMG：`rm -f dist/Trace-macOS.dmg`

### .app 启动后无菜单栏图标

**症状**：双击 `.app` 后无反应

**解决**：
1. 检查日志：`~/Library/Logs/Trace/`
2. 从终端启动查看错误：`./dist/Trace.app/Contents/MacOS/Trace`
3. 检查权限：`ls -la dist/Trace.app/Contents/MacOS/`

### Electron 操作台无法启动

**症状**：菜单栏点击"打开操作台 (Electron) ⚡"无反应

**解决**：
1. 检查嵌入产物：`ls -la "dist/Trace.app/Contents/Resources/electron/Trace Console.app"`
2. 检查日志：`cat test_workspace/.trace/logs/electron.log`
3. 开发态手动启动测试：`cd electron_app && npm start -- --workspace=../test_workspace`
4. 调试 renderer 时可另起 Vite：`npm run dev:renderer`，再用 `VITE_DEV_SERVER_URL=http://127.0.0.1:5173 npm run start:dev -- --workspace=../test_workspace`

### Windows 打包后无法打开 Electron 操作台

**症状**：Windows 托盘菜单点击"打开操作台 (Electron) ⚡"无反应

**解决**：
1. 检查嵌入产物：`dir .\dist\Trace\electron\Trace Console.exe`
2. 检查 bridge：`dir .\dist\Trace\TraceBridge.exe`
3. 重新运行 `pwsh .\scripts\build_windows_app.ps1`；脚本会验证 TraceBridge MCP 握手，失败时会直接报错
4. 检查日志：`type <workspace>\.trace\logs\electron.log`

---

**构建时间**：2026-05-29  
**构建环境**：macOS (arm64), Python 3.13, py2app, electron-builder, create-dmg；Windows 打包需在 Windows + PowerShell 环境执行
