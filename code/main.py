"""
Trace — 入口
============================
功能：启动多 CLI Agent 协作版本追踪守护进程。

用法：
    python main.py                              # 用上次的工作区；没记忆就进 TUI 选择屏
    python main.py --workspace /path/to/proj    # 直接指定（也会被记下来）
    python main.py --choose                     # 强制重选（弹 TUI 选择屏，root=上次记忆）
    python main.py --headless                   # 不起 TUI，仅跑守护进程（用于 E2E / SSH）
    python main.py -v / --verbose               # 输出调试日志

工作区解析优先级：
    1. --workspace X        → 用 X
    2. --choose             → 进 TUI 选择屏（root=上次记忆，若有）
    3. 上次记忆存在         → 沉默地用上次（最常见路径）
    4. 啥都没              → 进 TUI 选择屏（root=$HOME）

"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from utils.state import load_last_workspace, save_last_workspace


def setup_logging(verbose: bool) -> None:
    """配置日志：INFO 默认，--verbose 时升级到 DEBUG。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="trace",
        description="Trace：多 CLI Agent 协作版本追踪器",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="要追踪的工作目录的绝对路径。不指定则用上次的，没上次就进 TUI 选择屏。",
    )
    parser.add_argument(
        "--choose",
        action="store_true",
        help="强制进 TUI 选择屏（用来切换工作区）。",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="不起 TUI，只跑守护进程（用于 E2E 测试 / SSH / 调试守护进程本身）。",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="输出调试日志",
    )
    return parser.parse_args()


def resolve_startup_workspace(
    args: argparse.Namespace, log: logging.Logger
) -> tuple[Path | None, bool]:
    """按四段优先级决定工作区。

    返回 ``(workspace, needs_picker)``：
      * workspace 已知 → ``(workspace, False)``
      * --workspace 指向不存在的目录 → ``(None, False)``（硬错误，main 直接 exit 1）
      * --choose 或无 --workspace 也无记忆 → ``(None, True)``（让 TUI 选择屏接管）
    """
    if args.workspace is not None:
        ws = args.workspace.expanduser().resolve()
        if not ws.is_dir():
            log.error("--workspace 指定的目录不存在: %s", ws)
            return None, False
        return ws, False

    last = load_last_workspace()

    if args.choose:
        log.info("--choose 指定，进入 TUI 选择屏（initialdir=%s）", last or "$HOME")
        return None, True

    if last is not None:
        log.info("使用上次工作区: %s （--choose 可重选）", last)
        return last, False

    log.info("无 --workspace 也无记忆，进入 TUI 选择屏...")
    return None, True


def resolve_workspace(args: argparse.Namespace, log: logging.Logger) -> Path | None:
    """Backward-compat shim for tests: returns just the workspace (None if picker needed)."""
    ws, _needs_picker = resolve_startup_workspace(args, log)
    return ws


def _run_headless(daemon, log: logging.Logger) -> int:
    """
    无菜单栏模式：轮询活跃 agent + 等 SIGINT。
    用于 E2E 测试、SSH 环境、调试守护本身。
    """
    from daemon.detectors import scan_active_agents

    def _signal(signum, frame):
        log.info("收到退出信号，关闭...")
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal)
    signal.signal(signal.SIGTERM, _signal)
    if hasattr(signal, "SIGBREAK"):  # Windows: subprocess.CTRL_BREAK_EVENT
        signal.signal(signal.SIGBREAK, _signal)
    log.info("Headless 模式 — Ctrl+C 退出。")
    try:
        while True:
            active = scan_active_agents(daemon.workspace)
            if active:
                names = ", ".join(a.display_name for a in active)
                log.info("当前活跃 agent: %s", names)
            else:
                log.debug("无 AI agent 活跃；任何文件变化会归为 human")
            time.sleep(5.0)
    except KeyboardInterrupt:
        _signal(None, None)
    return 0


def _run_with_tui(
    daemon,
    log: logging.Logger,
    *,
    pick_workspace: bool = False,
    controller_workspace: Path | None = None,
    picker_initial: Path | None = None,
) -> int:
    """Default mode: TraceApp (Textual TUI) owns the main thread.

    ``pick_workspace=True`` 时进入"先选工作区再启动"流程：TUI 挂一个 DirectoryTree
    选择屏（root=``picker_initial``，通常是上次记忆的工作区），用户确认后才
    ``daemon.start(path)`` 并切到主界面。
    """
    from tui.app import TraceApp

    controller = None
    if not pick_workspace and controller_workspace is not None:
        from tui.controller import TraceController

        controller = TraceController(
            getattr(daemon, "repo", None), controller_workspace
        )

    app = TraceApp(
        daemon=daemon,
        controller=controller,
        pick_workspace=pick_workspace,
        picker_initial=picker_initial,
    )
    try:
        app.run()
    finally:
        daemon.stop()
        log.info("Trace已退出。")
    return 0


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    log = logging.getLogger("trace.main")

    workspace, needs_picker = resolve_startup_workspace(args, log)
    if workspace is None and not needs_picker:
        # --workspace 指向了不存在的目录
        return 1
    if workspace is not None:
        save_last_workspace(workspace)
        log.info("Trace启动，工作目录: %s", workspace)

    from daemon.manager import DaemonManager

    daemon = DaemonManager()
    if workspace is not None:
        daemon.start(workspace)
        log.info("守护进程运行中。")

    if args.headless:
        if workspace is None:
            log.error(
                "headless 模式必须有 --workspace 或上次工作区；TUI 选择屏不可用。"
            )
            return 1
        return _run_headless(daemon, log)
    return _run_with_tui(
        daemon,
        log,
        pick_workspace=needs_picker,
        controller_workspace=workspace,
        picker_initial=load_last_workspace() if needs_picker else None,
    )


if __name__ == "__main__":
    sys.exit(main())
