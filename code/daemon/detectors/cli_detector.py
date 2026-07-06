"""
CLI Agent 检测器 — 类别 1
================================
枚举当前在工作目录里活跃的 CLI agent 进程。

# AI 辅助生成（Claude 4.7 协助）
# 人工修正：
#   - 第 78-82 行：补 ZombieProcess 异常（psutil v5+ macOS 上偶尔抛）
#   - 第 95-100 行：补 _is_within() 工具函数，AI 原版用了 Path.is_relative_to
#     但 Python 3.9 没有这 API，改成对 .parents 做检查更兼容
#   - 第 65 行：把 logger 名从 AI 默认的 "agent_detector" 改为约定的 "trace.detector.cli"
"""

import logging
import threading
import time
from pathlib import Path

import psutil
from models.agent import AgentInstance

logger = logging.getLogger("trace.detector.cli")

_PROCESS_SNAPSHOT_TTL = 2.5
_process_snapshot_lock = threading.Lock()
_process_snapshot: tuple[float, list[dict]] | None = None


def clear_process_snapshot_cache() -> None:
    """测试或工作区切换时清空进程快照缓存。"""
    global _process_snapshot
    with _process_snapshot_lock:
        _process_snapshot = None


def _get_process_snapshot() -> list[dict]:
    """缓存一次 psutil.process_iter 结果，供 CLI/GUI/Script 检测器共享。"""
    global _process_snapshot
    now = time.time()
    with _process_snapshot_lock:
        if (
            _process_snapshot is not None
            and (now - _process_snapshot[0]) < _PROCESS_SNAPSHOT_TTL
        ):
            return _process_snapshot[1]

    snapshot: list[dict] = []
    for proc in psutil.process_iter(["pid", "name", "cwd", "create_time"]):
        try:
            snapshot.append(proc.info)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess) as e:
            logger.debug("跳过进程 (访问被拒/已退出): %s", e)
            continue
        except Exception as e:
            logger.warning("枚举进程时出现未预期异常: %s", e)
            continue

    with _process_snapshot_lock:
        _process_snapshot = (now, snapshot)
    return snapshot


# 已知的 CLI agent 进程名清单（小写、不带路径）
KNOWN_CLI_AGENTS: dict[str, dict[str, str]] = {
    "claude": {"display_name": "Claude Code", "color": "#D97757"},
    "codex": {"display_name": "Codex CLI", "color": "#10A37F"},
    "cursor": {"display_name": "Cursor", "color": "#000000"},
    "openclaw": {"display_name": "OpenClaw", "color": "#5E6AD2"},
    "opencode": {"display_name": "OpenCode", "color": "#2F80ED"},
    "hermes": {"display_name": "Hermes", "color": "#C89211"},
    "kimi": {"display_name": "Kimi Code", "color": "#8B5CF6", "canonical": "kimi"},
    "kimi-code": {"display_name": "Kimi Code", "color": "#8B5CF6", "canonical": "kimi"},
    "kimi code": {"display_name": "Kimi Code", "color": "#8B5CF6", "canonical": "kimi"},
}


def _normalize_process_name(name: str | None) -> str:
    """把 psutil 返回的进程名规范化成内部 agent key。"""
    if not name:
        return ""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base


def _is_within(child: Path, parent: Path) -> bool:
    """
    判断 child 是否在 parent 内（或等于 parent）。
    兼容 Python 3.9（无 is_relative_to）。
    # 人工补充：AI 原版直接用 child.is_relative_to(parent)，3.10+ 才有
    """
    if child == parent:
        return True
    return parent in child.parents


def _iter_known_cli_agents() -> list[AgentInstance]:
    """Scan all known CLI agent processes, regardless of their cwd."""
    """
    Global fallback: if the agent changed a file through an absolute path from
    another cwd, the workspace-scoped scan will miss it. This still only returns
    known agent process names; attribution confidence is decided by caller.
    """
    found: list[AgentInstance] = []

    for info in _get_process_snapshot():
        try:
            name = _normalize_process_name(info.get("name"))
            if name not in KNOWN_CLI_AGENTS:
                continue

            cwd_str = info.get("cwd")
            if not cwd_str:
                # 拿到了进程但 cwd 是 None/空字符串：跳过
                continue
            cwd = Path(cwd_str).expanduser().resolve(strict=False)

            meta = KNOWN_CLI_AGENTS[name]
            canonical_name = meta.get("canonical", name)
            found.append(
                AgentInstance(
                    name=canonical_name,
                    display_name=meta["display_name"],
                    category="cli",
                    pid=info["pid"],
                    cwd=str(cwd),
                    started_at=float(info.get("create_time") or 0.0),
                )
            )

        except Exception as e:
            # 兜底：未知异常记日志但不中断扫描
            logger.warning("枚举进程时出现未预期异常: %s", e)
            continue

    return found


def scan_cli_agents(workspace: Path) -> list[AgentInstance]:
    """
    枚举工作目录内正在运行的所有已知 CLI agent 进程。

    设计要点：
    - 使用 psutil.process_iter 一次性取 pid/name/cwd/create_time，避免循环里二次查询
    - cwd 必须在 workspace 内（嵌套子目录也算），否则不算"在这个项目里活动"
    - 系统进程的 cwd 可能 AccessDenied，必须 try/except 静默跳过

    参数：
        workspace: 工作目录的绝对路径

    返回：
        AgentInstance 列表，**可能为空**（表示当前无 agent 活跃，应归为 human）
    """
    workspace = workspace.expanduser().resolve(strict=False)
    return [
        agent
        for agent in _iter_known_cli_agents()
        if agent.cwd and _is_within(Path(agent.cwd), workspace)
    ]


def scan_global_cli_agents() -> list[AgentInstance]:
    """Return known active CLI agents without restricting cwd to a workspace."""
    return _iter_known_cli_agents()
