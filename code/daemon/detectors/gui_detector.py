"""
GUI Agent detector — category 2 (no web browser origins).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path

import psutil

from daemon.detectors.cli_detector import _get_process_snapshot, _is_within
from models.agent import AgentInstance

logger = logging.getLogger("trace.detector.gui")

KNOWN_GUI_APPS: dict[str, dict[str, str]] = {
    "cursor": {
        "display_name": "Cursor",
        "color": "#7C3AED",
        "process_names": ["cursor", "cursor helper"],
        "frontmost_names": ["Cursor"],
    },
    "vscode": {
        "display_name": "VS Code",
        "color": "#007ACC",
        "process_names": ["code", "code helper"],
        "frontmost_names": ["Code", "Visual Studio Code"],
    },
}


_FRONTMOST_CACHE_TTL = 3.0
_frontmost_cache: tuple[float, str | None] | None = None


def _frontmost_app_name() -> str | None:
    global _frontmost_cache
    now = time.time()
    if _frontmost_cache is not None and (now - _frontmost_cache[0]) < _FRONTMOST_CACHE_TTL:
        return _frontmost_cache[1]

    frontmost = _query_frontmost_app_name()
    _frontmost_cache = (now, frontmost)
    return frontmost


def _query_frontmost_app_name() -> str | None:
    if sys.platform == "darwin":
        script = (
            'tell application "System Events" to get name of first '
            "application process whose frontmost is true"
        )
        try:
            completed = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=2.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        name = completed.stdout.strip()
        return name or None

    if sys.platform.startswith("win"):
        try:
            import ctypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = psutil.Process(pid.value)
            return proc.name()
        except Exception:
            return None
    return None


def _match_gui_key(process_name: str | None, frontmost: str | None) -> str | None:
    proc = (process_name or "").lower()
    front = frontmost or ""
    for key, meta in KNOWN_GUI_APPS.items():
        names = [n.lower() for n in meta.get("process_names", [])]
        fronts = meta.get("frontmost_names", [])
        if proc in names:
            return key
        if front in fronts:
            return key
    return None


def scan_gui_agents(workspace: Path) -> list[AgentInstance]:
    workspace = workspace.expanduser().resolve(strict=False)
    frontmost = _frontmost_app_name()
    found: list[AgentInstance] = []

    for info in _get_process_snapshot():
        try:
            key = _match_gui_key(info.get("name"), frontmost)
            if key is None:
                continue
            cwd_str = info.get("cwd") or ""
            if not cwd_str:
                continue
            cwd = Path(cwd_str).expanduser().resolve(strict=False)
            if not _is_within(cwd, workspace):
                continue
            meta = KNOWN_GUI_APPS[key]
            found.append(
                AgentInstance(
                    name=key,
                    display_name=meta["display_name"],
                    category="gui_app",
                    pid=int(info["pid"] or 0),
                    cwd=str(cwd_str or ""),
                    started_at=float(info.get("create_time") or 0.0),
                )
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except Exception as exc:
            logger.debug("gui detector skipped process: %s", exc)

    dedup: dict[str, AgentInstance] = {}
    for item in found:
        dedup[item.name] = item
    return list(dedup.values())
