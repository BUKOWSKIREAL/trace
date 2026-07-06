"""
Bridge used by Electron to restore files through Repository.

The Electron main process delegates versioned filesystem writes to Python so
the existing Repository semantics stay in one place.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from core.repository import Repository


def restore_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        workspace = Path(str(payload["workspace"])).expanduser().resolve()
        commit_id = int(payload["commit_id"])
        file_path = str(payload["file_path"])
        backup_current = bool(payload.get("backup_current", True))

        repo = Repository(workspace)
        backup_id = repo.restore_file(
            commit_id,
            file_path,
            backup_current=backup_current,
        )
        return {
            "ok": True,
            "commit_id": commit_id,
            "file_path": file_path,
            "backup_id": backup_id,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    result = restore_payload(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
