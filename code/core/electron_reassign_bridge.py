"""Bridge for Electron to reassign ambiguous commit metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from core.repository import Repository


def reassign_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        workspace = Path(str(payload["workspace"])).expanduser().resolve()
        commit_id = int(payload["commit_id"])
        new_agent = str(payload["new_agent"])
        repo = Repository(workspace)
        repo.reassign_commit(commit_id, new_agent)
        return {"ok": True, "commit_id": commit_id, "new_agent": new_agent}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    result = reassign_payload(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
