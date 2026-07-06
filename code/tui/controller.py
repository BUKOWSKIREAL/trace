"""In-process data facade the TUI calls instead of touching the backend directly.

Every method returns {"ok": True, ...} or {"ok": False, "error": <str>} so the
UI can render failures without crashing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.electron_diff_bridge import render_file_diff


class TraceController:
    def __init__(self, repo, workspace: Path) -> None:
        self._repo = repo
        self._workspace = workspace

    def list_commits(self, limit: int = 50) -> dict[str, Any]:
        try:
            return {"ok": True, "commits": self._repo.list_commits(limit)}
        except Exception as exc:  # noqa: BLE001 - deliberate boundary
            return {"ok": False, "error": str(exc)}

    def get_diff(self, file_path: str, prev_hash: str | None, cur_hash: str | None) -> dict[str, Any]:
        try:
            lines = render_file_diff(self._workspace, file_path, prev_hash, cur_hash)
            return {"ok": True, "lines": lines}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def restore_file(self, commit_id: int, file_path: str) -> dict[str, Any]:
        try:
            backup_id = self._repo.restore_file(commit_id, file_path)
            return {"ok": True, "backup_id": backup_id}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def reassign_commit(self, commit_id: int, new_agent: str) -> dict[str, Any]:
        try:
            self._repo.reassign_commit(commit_id, new_agent)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def preview_revert_agent(self, agent: str) -> dict[str, Any]:
        try:
            return {"ok": True, "preview": self._repo.preview_revert_agent(agent)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def revert_agent(self, agent: str) -> dict[str, Any]:
        try:
            return {"ok": True, "commit_id": self._repo.revert_agent(agent)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
