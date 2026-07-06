"""
Local script agent detector — category 4.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psutil

from daemon.detectors.cli_detector import _get_process_snapshot, _is_within
from models.agent import AgentInstance

logger = logging.getLogger("trace.detector.script")

SCRIPT_RUNNERS = {"python", "python3", "node", "nodejs"}
SCRIPT_MARKERS = (
    "anthropic",
    "openai",
    "cursor-sdk",
    "cursor_sdk",
    "claude",
    "codex",
    "agent",
    "llm",
)


def _cmdline_text(proc: psutil.Process) -> str:
    try:
        parts = proc.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return ""
    return " ".join(parts).lower()


def scan_local_ai_scripts(workspace: Path) -> list[AgentInstance]:
    workspace = workspace.expanduser().resolve(strict=False)
    workspace_text = str(workspace).lower()
    found: list[AgentInstance] = []

    for info in _get_process_snapshot():
        try:
            name = (info.get("name") or "").lower()
            base = name.rsplit("/", 1)[-1]
            if base.endswith(".exe"):
                base = base[:-4]
            if base not in SCRIPT_RUNNERS:
                continue

            cmd = _cmdline_text(psutil.Process(info["pid"]))
            if workspace_text not in cmd:
                continue
            if not any(marker in cmd for marker in SCRIPT_MARKERS):
                continue

            cwd_str = info.get("cwd") or workspace_text
            cwd = Path(cwd_str).expanduser().resolve(strict=False)
            if cwd_str and not _is_within(cwd, workspace):
                continue

            script_name = "local-script"
            if "claude" in cmd:
                script_name = "claude-script"
            elif "codex" in cmd:
                script_name = "codex-script"

            found.append(
                AgentInstance(
                    name=script_name,
                    display_name="Local AI Script",
                    category="local_script",
                    pid=int(info["pid"] or 0),
                    cwd=str(cwd),
                    started_at=float(info.get("create_time") or 0.0),
                )
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except Exception as exc:
            logger.debug("script detector skipped process: %s", exc)

    dedup: dict[int, AgentInstance] = {}
    for item in found:
        dedup[item.pid] = item
    return list(dedup.values())
