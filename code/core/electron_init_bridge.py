"""Initialize a workspace repository for Electron when .trace/ does not exist yet."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from core.repository import Repository
from utils.db import close_connections


def init_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        workspace = Path(str(payload["workspace"])).expanduser().resolve()
        if not workspace.is_dir():
            return {"ok": False, "error": f"工作区目录不存在: {workspace}"}
        repo = Repository(workspace)
        repo.init_if_needed()
        close_connections(repo.db_path)
        return {
            "ok": True,
            "workspace": str(workspace),
            "db_path": str(repo.db_path),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    result = init_payload(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
