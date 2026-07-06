"""Bridge for Electron to preview and execute selective agent revert."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from core.repository import Repository


def revert_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        workspace = Path(str(payload["workspace"])).expanduser().resolve()
        agent = str(payload["agent"])
        repo = Repository(workspace)
        if payload.get("preview"):
            preview = repo.preview_revert_agent(agent)
            return {"ok": True, "preview": True, **preview}
        commit_id = repo.revert_agent(
            agent,
            backup_current=bool(payload.get("backup_current", True)),
        )
        return {"ok": True, "commit_id": commit_id, "agent": agent}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    result = revert_payload(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
