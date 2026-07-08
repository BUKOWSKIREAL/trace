"""In-process data facade the TUI calls instead of touching the backend directly.

Every method returns {"ok": True, ...} or {"ok": False, "error": <str>} so the
UI can render failures without crashing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.diff import render_file_diff

_MAX_DIFF_LINES = 800


class TraceController:
    def __init__(self, repo, workspace: Path) -> None:
        self._repo = repo
        self._workspace = workspace

    def list_commits(self, limit: int = 50) -> dict[str, Any]:
        try:
            return {"ok": True, "commits": self._repo.list_commits(limit)}
        except Exception as exc:  # noqa: BLE001 - deliberate boundary
            return {"ok": False, "error": str(exc)}

    def get_diff(
        self, file_path: str, prev_hash: str | None, cur_hash: str | None
    ) -> dict[str, Any]:
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

    def get_manifest(self, commit_id: int) -> dict[str, Any]:
        try:
            return {"ok": True, "manifest": self._repo.get_manifest(commit_id)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def get_prev_commit_id(self, commit_id: int) -> dict[str, Any]:
        try:
            return {"ok": True, "prev_id": self._repo.get_prev_commit_id(commit_id)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def get_commit_diff(self, commit_id: int) -> dict[str, Any]:
        """Assemble the full diff view for a commit: changed files + rendered lines.

        The controller unions the current and previous commit manifests,
        classifies each changed path as new/modified/deleted, renders its diff,
        and truncates very long diffs for TUI responsiveness.
        """
        try:
            prev_id = self._repo.get_prev_commit_id(commit_id)
            cur_manifest = self._repo.get_manifest(commit_id)
            prev_manifest = (
                self._repo.get_manifest(prev_id) if prev_id is not None else []
            )

            cur_map = {row["file_path"]: row["blob_hash"] for row in cur_manifest}
            prev_map = {row["file_path"]: row["blob_hash"] for row in prev_manifest}

            files: list[dict[str, Any]] = []
            for file_path in sorted(set(cur_map) | set(prev_map)):
                cur_hash = cur_map.get(file_path)
                prev_hash = prev_map.get(file_path)
                if cur_hash == prev_hash:
                    continue
                if prev_hash is None:
                    status = "new"
                elif cur_hash is None:
                    status = "deleted"
                else:
                    status = "modified"

                lines = render_file_diff(
                    self._workspace, file_path, prev_hash, cur_hash
                )
                if len(lines) > _MAX_DIFF_LINES:
                    omitted = len(lines) - _MAX_DIFF_LINES
                    lines = lines[:_MAX_DIFF_LINES] + [
                        {"tag": "meta", "text": f"... (truncated {omitted} lines)"}
                    ]

                files.append(
                    {
                        "path": file_path,
                        "status": status,
                        "prev_hash": prev_hash,
                        "cur_hash": cur_hash,
                        "can_restore": cur_hash is not None,
                        "lines": lines,
                    }
                )

            return {"ok": True, "files": files}
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

    def list_agents(self) -> dict[str, Any]:
        try:
            return {"ok": True, "agents": self._repo.list_agents()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def get_workspace_summary(self) -> dict[str, Any]:
        try:
            return {"ok": True, "summary": self._repo.workspace_summary()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def list_mcp_setup(self) -> dict[str, Any]:
        try:
            from mcp.setup import McpSetup

            return {"ok": True, "rows": McpSetup(self._workspace).list_rows()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def install_mcp_server(self, server_id: str) -> dict[str, Any]:
        try:
            from mcp.setup import McpSetup

            return McpSetup(self._workspace).install(server_id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "server_id": server_id}
