"""
Restore/writeback sentinel
==========================

Repository restore/checkout operations write files into the workspace. A daemon
watcher running in another process would otherwise see those writes and attribute
them to whichever CLI agent is currently active. This module provides a small
TTL-based sentinel in .trace/ so Repository can mark those self-writes and the
watcher can suppress or classify them as human restore activity.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("trace.restore_sentinel")

SENTINEL_FILENAME = "restore_sentinel.json"
DEFAULT_RESTORE_WINDOW_SECONDS = 10.0


def restore_sentinel_path(workspace: Path) -> Path:
    return workspace.expanduser().resolve(strict=False) / ".trace" / SENTINEL_FILENAME


def mark_restore_window(
    workspace: Path,
    operation: str,
    *,
    detection_method: str | None = None,
    ttl_seconds: float = DEFAULT_RESTORE_WINDOW_SECONDS,
) -> None:
    """Mark a short window during which watcher events are restore self-writes."""
    path = restore_sentinel_path(workspace)
    payload = {
        "operation": operation,
        "detection_method": detection_method or operation or "restore",
        "agent": "human",
        "created_at": time.time(),
        "until": time.time() + max(ttl_seconds, 0.1),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        # The sentinel is a safety mechanism; restore itself should not fail just
        # because this best-effort marker could not be written.
        logger.debug("写入 restore sentinel 失败: %s", exc)


def active_restore_window(
    workspace: Path, *, now: float | None = None
) -> dict[str, Any] | None:
    """Return sentinel payload if the restore window is currently active."""
    path = restore_sentinel_path(workspace)
    now = time.time() if now is None else now
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    try:
        until = float(payload.get("until", 0.0))
    except (TypeError, ValueError):
        until = 0.0

    if until < now:
        try:
            path.unlink()
        except OSError:
            pass
        return None

    if not isinstance(payload.get("detection_method"), str):
        payload["detection_method"] = "restore"
    if not isinstance(payload.get("operation"), str):
        payload["operation"] = payload["detection_method"]
    return payload
