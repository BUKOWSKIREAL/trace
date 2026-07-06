"""
TraceApp — 菜单栏业务层
==========================
把 Tray 抽象层、daemon 各组件粘起来：
- 构建菜单（更换工作区 / 打开操作台 / 暂停跟踪 / 强制 agent radio / 退出）
- 定时拉 daemon 状态（活跃 agent），刷 tray 标题
- 打开操作台时启动独立 Electron 进程
- 处理菜单点击 callback

设计：依赖注入式构造——tray 和 scan_agents 都可在测试里注入 mock，
不依赖真实 NSApplication 或 psutil 进程枚举。

# 人工编写（Task 3 起步；Task 4 加 handler 状态字段；Task 5 加操作台）
# 人工修正（2026-05-27）：操作台改为独立 Electron 进程，避免与菜单栏 run loop 耦合
"""

import logging
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from daemon.detectors import scan_active_agents
from daemon.ipc import drain
from utils.state import save_last_workspace
from views.workspace_picker import pick_workspace

from menubar.tray_base import make_tray

logger = logging.getLogger("trace.menubar.app")


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Agent 名 → 显示名 映射（保持和 cli_detector.KNOWN_CLI_AGENTS 一致；
# 这里只用于"强制 agent" radio 项的标签，所以局部冗余可接受）
_AGENT_DISPLAY = {
    None: "自动检测",
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "openclaw": "OpenClaw",
    "opencode": "OpenCode",
    "hermes": "Hermes",
    "kimi": "Kimi Code",
}

_BUNDLED_CONSOLE_APP_NAME = "Trace Console"
_BUNDLED_CONSOLE_BUNDLE_ID = "cn.edu.shu.trace.electron"


@dataclass(frozen=True)
class ElectronLaunch:
  """子进程启动结果；macOS 打包态经 open 启动时 external=True。"""

  proc: subprocess.Popen | None
  external: bool = False


def _choose_workspace_for_menubar(initial: Path) -> Path | None:
    """
    菜单栏回调里不能可靠地启动 Tk filedialog。
    macOS 下用系统原生 choose folder；其它平台退回 Tk picker。
    """
    if sys.platform != "darwin":
        return pick_workspace(initial=initial)

    default_location = _applescript_string(str(initial))
    script = (
        'tell application "Finder" to activate\n'
        'set chosenFolder to choose folder with prompt "选择Trace要追踪的工作区" '
        f"default location (POSIX file {default_location})\n"
        "POSIX path of chosenFolder"
    )
    completed = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        logger.info("用户取消了工作区选择或选择器失败: %s", completed.stderr.strip())
        return None
    chosen = completed.stdout.strip()
    if not chosen:
        return None
    return Path(chosen).expanduser().resolve()


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _source_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _frozen_app_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _runtime_resource_root() -> Path:
    if not _is_frozen():
        return _source_project_root()
    if sys.platform == "darwin":
        return _frozen_app_dir().parent / "Resources"
    return Path(getattr(sys, "_MEIPASS", _frozen_app_dir()))


def _runtime_project_root() -> Path:
    if not _is_frozen():
        return _source_project_root()
    if sys.platform == "darwin":
        return _runtime_resource_root()
    return _frozen_app_dir()


def _bundled_electron_executable() -> Path | None:
    """返回打包产物内嵌的 Electron Console 可执行文件。"""
    if not _is_frozen():
        return None
    if sys.platform == "darwin":
        candidate = (
            _runtime_resource_root()
            / "electron"
            / "Trace Console.app"
            / "Contents"
            / "MacOS"
            / "Trace Console"
        )
        return candidate if candidate.exists() else None

    candidates = [
        _frozen_app_dir() / "electron" / "Trace Console.exe",
        _frozen_app_dir() / "_internal" / "electron" / "Trace Console.exe",
        _runtime_resource_root() / "electron" / "Trace Console.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _bundled_electron_app_bundle() -> Path | None:
    """返回打包产物内嵌的 Trace Console.app 路径（仅 macOS）。"""
    executable = _bundled_electron_executable()
    if executable is None or sys.platform != "darwin":
        return None
    bundle = executable.parent.parent.parent
    return bundle if bundle.suffix == ".app" and bundle.exists() else None


def _is_bundled_console_running_macos() -> bool:
    completed = subprocess.run(
        [
            "osascript",
            "-e",
            f'tell application "System Events" to (name of processes) contains "{_BUNDLED_CONSOLE_APP_NAME}"',
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    return completed.returncode == 0 and completed.stdout.strip().lower() == "true"


def _quit_external_electron_console(workspace: Path | None = None) -> None:
    """按应用名退出操作台（macOS open 启动或子进程已脱离时使用）。"""
    if sys.platform == "darwin":
        for script in (
            f'tell application "{_BUNDLED_CONSOLE_APP_NAME}" to quit',
            f'tell application id "{_BUNDLED_CONSOLE_BUNDLE_ID}" to quit',
        ):
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                check=False,
                timeout=5,
            )
        if workspace is not None:
            pattern = re.escape(f"--workspace={workspace}")
            subprocess.run(
                ["pkill", "-f", f"electron.*{pattern}"],
                capture_output=True,
                check=False,
            )
    elif sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/IM", f"{_BUNDLED_CONSOLE_APP_NAME}.exe", "/F"],
            capture_output=True,
            check=False,
        )


def _electron_bridge_env(project_root: Path) -> dict[str, str]:
    """Provide Electron with the Python bridge needed for handler-backed diffs."""
    env = os.environ.copy()
    env["TRACE_PROJECT_ROOT"] = str(project_root)
    env["TRACE_PYTHON_EXECUTABLE"] = str(Path(sys.executable).resolve())
    env["TRACE_PYTHON_MODULE"] = "core.electron_diff_bridge"

    if _is_frozen() and sys.platform == "win32":
        env["TRACE_PYTHON_EXECUTABLE"] = str(
            Path(sys.executable).resolve().with_name("TraceBridge.exe")
        )
        env["TRACE_PYTHON_BRIDGE_MODE"] = "bridge-exe"
        return env

    if _is_frozen():
        resources_dir = _runtime_resource_root()
        python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        bridge_root = resources_dir / "lib" / python_version
    else:
        bridge_root = project_root / "code"

    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(bridge_root) if not existing else str(bridge_root) + os.pathsep + existing
    )
    return env


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """终止 Electron 子进程；Unix 下杀整组进程以清理 npx/electron 树。"""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Electron 操作台未及时退出，强制结束: pid=%s", proc.pid)
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            proc.kill()
        proc.wait(timeout=5)


def _launch_electron_process(workspace: Path) -> ElectronLaunch:
    """启动 Electron 操作台子进程。

    打包态 macOS 直接启动内嵌可执行文件，并标记 external=True，退出时按
    应用名 ``Trace Console`` 收尾（避免启动器进程先退出导致无法关停）。
    开发态回退 ``npx electron . --workspace=<path>``。
    """
    project_root = _runtime_project_root()
    electron_dir = project_root / "electron_app"
    log_dir = workspace / ".trace" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "electron.log"
    log_file = log_path.open("a", encoding="utf-8")
    bundled = _bundled_electron_executable()
    env = _electron_bridge_env(project_root)
    external = False
    if bundled is not None:
        argv = [str(bundled), f"--workspace={workspace}"]
        cwd = None
        if sys.platform == "darwin":
            external = True
    else:
        argv = [
            "npx",
            "electron",
            ".",
            f"--workspace={workspace}",
        ]
        cwd = str(electron_dir)
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return ElectronLaunch(proc=proc, external=external)
    finally:
        log_file.close()


class TraceApp:
    """
    Trace的菜单栏入口。把 Tray + DaemonManager + 操作台粘起来。

    用法（main.py 里调）：
        daemon = DaemonManager()
        daemon.start(workspace)
        app = TraceApp(daemon=daemon)
        app.start()  # 阻塞主线程

    重构说明：原来分别注入 workspace/repo/batcher/observer/handler
    五个引用；现在改成单一 daemon: DaemonManager 注入，其余通过
    @property 透传。这样工作区热切（daemon.restart）后所有内部引用
    自动跟着更新，不留半残态。
    """

    POLL_INTERVAL = 2.0  # 秒——拉 daemon IPC 事件、检查 Electron 子进程

    def __init__(
        self,
        daemon,  # DaemonManager（已 start 过）
        *,
        tray=None,  # 测试可注入 mock
        scan_agents: Callable | None = None,  # 测试可注入 mock
        electron_launcher: Callable[[Path], ElectronLaunch] | None = None,
        workspace_picker: Callable[[Path], Path | None] | None = None,
    ):
        self.daemon = daemon

        # 依赖注入：测试传 mock；生产走默认平台分发
        # 菜单栏图标：黑色单色 PNG，macOS 自动做 light/dark 反色
        _icon = Path(__file__).parent / "icon.png"
        self.tray = (
            tray
            if tray is not None
            else make_tray(
                "",
                icon_path=_icon if _icon.exists() else None,
            )
        )
        self._scan_agents = scan_agents or scan_active_agents
        self._electron_launcher = electron_launcher or _launch_electron_process
        self._workspace_picker = workspace_picker or _choose_workspace_for_menubar

        # 内部状态
        self._paused = False
        self._forced_agent: str | None = None
        self._electron_proc: subprocess.Popen | None = None
        self._electron_external = False

        runtime_config = getattr(daemon, "config", None)
        if runtime_config is not None:
            self._paused = not runtime_config.tracking_enabled
            self.handler.paused = self._paused
            forced = runtime_config.forced_agent_override()
            if forced is not None:
                self._forced_agent = forced
                self.handler.override_agent = forced

    # === 透传 daemon 字段（让旧代码 / 测试访问 app.workspace / app.handler 不变）===

    @property
    def workspace(self):
        return self.daemon.workspace

    @property
    def repo(self):
        return self.daemon.repo

    @property
    def batcher(self):
        return self.daemon.batcher

    @property
    def observer(self):
        return self.daemon.observer

    @property
    def handler(self):
        return self.daemon.handler

    # === 启动 ===

    def start(self) -> None:
        """构建初始菜单 + 注册定时器 + 自动打开操作台 + 阻塞跑 tray run loop。"""
        self._rebuild_menu()
        # 1s 拉一次 daemon 状态刷标题
        self.tray.schedule_periodic(self.POLL_INTERVAL, self._poll)
        logger.info("TraceApp 启动，工作目录: %s", self.workspace)
        try:
            self.on_open_electron()
            self.tray.run()
        finally:
            self._stop_electron()

    # === 菜单构造 ===

    def _rebuild_menu(self) -> None:
        """根据当前状态重画菜单。"""
        self.tray.set_menu(self._build_menu())

    def _build_menu(self) -> list[dict]:
        """生成菜单 schema list[dict]。状态变化时重新构造、调 set_menu。"""
        # pause 项的标签按当前状态切换
        pause_label = "继续跟踪" if self._paused else "暂停跟踪"
        pause_icon = "play.circle" if self._paused else "pause.circle"

        menu: list[dict] = [
            {
                "type": "item",
                "label": "更换工作区...",
                "icon": "folder",
                "callback": self.on_change_workspace,
            },
                {
                "type": "item",
                "label": "打开操作台 ⚡",
                "icon": "terminal",
                "callback": self.on_open_electron,
            },
            {"type": "separator"},
            {
                "type": "item",
                "label": pause_label,
                "icon": pause_icon,
                "callback": self.on_toggle_pause,
            },
            {"type": "separator"},
        ]

        # 强制 agent radio：None=自动，其它=对应进程名
        for key in (None, "claude", "codex", "openclaw", "opencode", "hermes", "kimi"):
            menu.append(
                {
                    "type": "radio",
                    "label": _AGENT_DISPLAY[key],
                    "icon": {
                        None: "sparkles",
                        "claude": "brain",
                        "codex": "chevron.left.forwardslash.chevron.right",
                        "openclaw": "wand.and.stars",
                        "opencode": "curlybraces",
                        "hermes": "paperplane",
                        "kimi": "moon.stars",
                    }[key],
                    "group": "agent",
                    "checked": self._forced_agent == key,
                    # 用默认参数绑定 key，避免闭包变量捕获坑
                    "callback": lambda k=key: self._set_forced_agent(k),
                }
            )

        menu.append({"type": "separator"})
        menu.append({"type": "quit", "icon": "power", "callback": self.on_quit})
        return menu

    # === 定时轮询 ===

    def _poll(self) -> None:
        """每 POLL_INTERVAL 秒：检查 Electron 子进程、拉 daemon IPC 事件。"""
        if self._electron_external:
            if sys.platform == "darwin" and not _is_bundled_console_running_macos():
                self._electron_external = False
                self._electron_proc = None
        elif self._electron_proc is not None and self._electron_proc.poll() is not None:
            self._electron_proc = None

        for event in drain():
            if event.type == "ambiguous_commit":
                logger.info(
                    "检测到 ambiguous commit #%s: %s",
                    event.payload.get("commit_id"),
                    event.payload.get("candidates"),
                )
            elif event.type == "new_commit":
                logger.debug(
                    "新 commit #%s by %s",
                    event.payload.get("commit_id"),
                    event.payload.get("agent"),
                )

    # === 菜单回调 ===

    def on_change_workspace(self) -> None:
        """弹文件夹选择器；选完热切 daemon（DaemonManager.restart）。

        - 用户取消 → 啥都不做
        - 选了同一个 workspace → 无变化（避免无意义重启）
        - 选了新 workspace → save_last_workspace + daemon.restart(new_ws)
        - restart 失败 → 尝试用旧 workspace 恢复，不留半残态
        """
        old_ws = self.workspace
        new_ws = self._workspace_picker(old_ws)
        if new_ws is None:
            logger.info("用户取消了工作区选择")
            return
        if new_ws == old_ws:
            logger.info("选择了同一个工作区（%s），无变化", new_ws)
            return

        save_last_workspace(new_ws)
        logger.info("热切工作区: %s → %s", old_ws, new_ws)
        try:
            self.daemon.restart(new_ws)
        except Exception:
            logger.exception("daemon.restart 失败，尝试恢复旧 workspace")
            try:
                self.daemon.start(old_ws)
            except Exception:
                logger.exception("恢复旧 workspace 也失败——daemon 处于停止状态")
            return

        # 切换成功，立刻更新标题；下次 _poll 会按新 workspace 扫 agent
        self.tray.set_title("")
        self._relaunch_electron_if_running(new_ws)

    def _stop_electron(self) -> None:
        """关闭 Electron 操作台子进程（菜单栏退出或工作区切换时调用）。"""
        proc = self._electron_proc
        external = self._electron_external
        self._electron_proc = None
        self._electron_external = False

        if proc is not None and proc.poll() is None:
            logger.info("关闭 Electron 操作台: pid=%s", proc.pid)
            try:
                _terminate_process_tree(proc)
            except Exception:
                logger.exception("关闭 Electron 操作台失败")

        if external or (proc is not None and proc.poll() is not None):
            logger.info("按应用名退出 Trace Console")
            _quit_external_electron_console(self.workspace)

    def on_quit(self) -> None:
        """菜单「退出」：先关操作台，再由 tray 结束 run loop。"""
        self._stop_electron()

    def _relaunch_electron_if_running(self, workspace: Path) -> None:
        """如果 Electron 操作台已打开，重启它以绑定新的 workspace。"""
        if not self._is_electron_running():
            return
        logger.info("工作区已切换，重启 Electron 操作台")
        self._stop_electron()
        try:
            launch = self._electron_launcher(workspace)
            self._electron_proc = launch.proc
            self._electron_external = launch.external
            pid = launch.proc.pid if launch.proc is not None else "external"
            logger.info("Electron 操作台已用新工作区重启，pid=%s", pid)
        except Exception:
            self._electron_proc = None
            self._electron_external = False
            logger.exception("用新工作区重启 Electron 操作台失败")

    def _is_electron_running(self) -> bool:
        if self._electron_external:
            return sys.platform == "darwin" and _is_bundled_console_running_macos()
        return self._electron_proc is not None and self._electron_proc.poll() is None

    def on_open_electron(self) -> None:
        """打开 Electron 操作台。

        打包态启动内嵌 Electron Console；开发态直接 npx electron。
        两种模式都读取当前 workspace 的 .trace/trace.db。
        """
        if self._is_electron_running():
            pid = self._electron_proc.pid if self._electron_proc else "external"
            logger.info("Electron 操作台已在运行，pid=%s", pid)
            return
        try:
            launch = self._electron_launcher(self.workspace)
            self._electron_proc = launch.proc
            self._electron_external = launch.external
            pid = launch.proc.pid if launch.proc is not None else "external"
            logger.info("Electron 进程已启动，pid=%s", pid)
        except FileNotFoundError as e:
            logger.error("Electron 启动失败（缺 npm？）: %s", e)
        except Exception:
            logger.exception("Electron 启动失败")

    def on_toggle_pause(self) -> None:
        """暂停 / 恢复跟踪——切换内部状态，同步写到 handler.paused。

        Task 4.1+4.2：handler.paused 控制 _dispatch 早退，所以 pause 是
        立刻生效的——不需要停 observer，事件到了 handler 入口直接丢弃。
        """
        self._paused = not self._paused
        self.handler.paused = self._paused
        runtime_config = getattr(self.daemon, "config", None)
        if runtime_config is not None:
            runtime_config.set_tracking_enabled(not self._paused)
        logger.info("跟踪状态切换为：%s", "已暂停" if self._paused else "运行中")
        self._rebuild_menu()

    def _set_forced_agent(self, agent: str | None) -> None:
        """强制指定 agent 归属，覆盖自动检测。

        Task 4.2：把 override 写到 handler.override_agent，
        _attribute 会优先看这个字段（confidence=1.0, manual_override）。
        """
        previous = self._forced_agent
        if previous:
            self.batcher.force_flush_agent(previous)
        self._forced_agent = agent
        self.handler.override_agent = agent
        runtime_config = getattr(self.daemon, "config", None)
        if runtime_config is not None:
            runtime_config.set_forced_agent(agent)
        logger.info("强制 agent 设为：%s", _AGENT_DISPLAY.get(agent, agent))
        self._rebuild_menu()
