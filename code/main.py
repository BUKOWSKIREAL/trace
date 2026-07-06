"""
Trace — 入口
============================
功能：启动多 CLI Agent 协作版本追踪守护进程。

用法：
    python main.py                              # 用上次的工作区；没记忆就弹选择器
    python main.py --workspace /path/to/proj    # 直接指定（也会被记下来）
    python main.py --choose                     # 强制重选（弹 picker，initialdir=上次）
    python main.py --headless                   # 不起菜单栏，仅跑守护进程（用于 E2E / SSH）
    python main.py -v / --verbose               # 输出调试日志

工作区解析优先级：
    1. --workspace X        → 用 X
    2. --choose             → 弹 picker（initialdir=上次记忆，若有）
    3. 上次记忆存在         → 沉默地用上次（最常见路径）
    4. 啥都没              → 弹 picker（initialdir=$HOME）

"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from utils.state import load_last_workspace, save_last_workspace
from views.workspace_picker import pick_workspace


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
        help="要追踪的工作目录的绝对路径。不指定则用上次的，没上次就弹选择器。",
    )
    parser.add_argument(
        "--choose",
        action="store_true",
        help="强制弹文件夹选择器（用来切换工作区）。",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="不起菜单栏图标，只跑守护进程（用于 E2E 测试 / SSH / 调试守护进程本身）。",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="输出调试日志",
    )
    return parser.parse_args()


def _pick_workspace(initial: Path | None) -> Path | None:
    if sys.platform == "darwin":
        from menubar.app import _choose_workspace_for_menubar

        chosen = _choose_workspace_for_menubar(initial or Path.home())
    else:
        chosen = pick_workspace(initial=initial)
    if chosen is None:
        return None
    return chosen.expanduser().resolve()


def resolve_workspace(args: argparse.Namespace, log: logging.Logger) -> Path | None:
    """
    按四段优先级决定工作区，None 表示用户取消、应当退出。
    """
    if args.workspace is not None:
        ws = args.workspace.expanduser().resolve()
        if not ws.is_dir():
            log.error("--workspace 指定的目录不存在: %s", ws)
            return None
        return ws

    last = load_last_workspace()

    if args.choose:
        log.info("--choose 指定，弹出选择器（initialdir=%s）", last or "$HOME")
        return _pick_workspace(last)

    if last is not None:
        log.info("使用上次工作区: %s （--choose 可重选）", last)
        return last

    log.info("无上次记忆，弹出文件夹选择器...")
    return _pick_workspace(None)


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


def _run_with_menubar(daemon, log: logging.Logger) -> int:
    """带菜单栏模式：TraceApp 接管主线程跑系统托盘。"""
    from menubar.app import TraceApp

    app = TraceApp(daemon=daemon)

    def _signal(signum, frame):
        log.info("收到退出信号 %d，请求关闭菜单栏...", signum)
        try:
            app.tray.stop()
        except Exception as e:
            log.warning("tray.stop 失败: %s", e)

    signal.signal(signal.SIGINT, _signal)
    signal.signal(signal.SIGTERM, _signal)

    try:
        app.start()
    finally:
        daemon.stop()
        log.info("Trace已退出。")
    return 0


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    log = logging.getLogger("trace.main")

    workspace = resolve_workspace(args, log)
    if workspace is None:
        log.info("未选择工作区，退出。")
        return 0

    if not workspace.is_dir():
        log.error("工作目录不存在或不是目录: %s", workspace)
        return 1

    save_last_workspace(workspace)
    log.info("Trace启动，工作目录: %s", workspace)

    from daemon.manager import DaemonManager

    daemon = DaemonManager()
    daemon.start(workspace)
    log.info("守护进程运行中。")

    if args.headless:
        return _run_headless(daemon, log)
    return _run_with_menubar(daemon, log)


if __name__ == "__main__":
    sys.exit(main())
