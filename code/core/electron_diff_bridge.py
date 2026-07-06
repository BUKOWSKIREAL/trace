"""
Bridge used by Electron to render file diffs through Python handlers.

The Electron renderer should not decode blob bytes itself. This module keeps
the existing HandlerRegistry as the single place that understands file types.
"""

from __future__ import annotations

import json
import string
import sys
from pathlib import Path
from typing import Any

from core.handlers import HandlerRegistry

_HEX = set(string.hexdigits)


def _read_blob(workspace: Path, blob_hash: str | None) -> bytes:
    if not blob_hash:
        return b""
    if len(blob_hash) != 64 or any(ch not in _HEX for ch in blob_hash):
        raise ValueError(f"invalid blob hash: {blob_hash!r}")
    blob_path = workspace / ".trace" / "objects" / blob_hash[:2] / blob_hash[2:]
    return blob_path.read_bytes()


def render_file_diff(
    workspace: Path,
    file_path: str,
    prev_hash: str | None,
    cur_hash: str | None,
) -> list[dict[str, str]]:
    old_blob = _read_blob(workspace, prev_hash)
    new_blob = _read_blob(workspace, cur_hash)
    handler = HandlerRegistry.for_path(Path(file_path))
    return [
        {"tag": tag, "text": text}
        for tag, text in handler.render_diff(old_blob, new_blob)
    ]


def render_payload(payload: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(str(payload["workspace"])).expanduser().resolve()
    files = payload.get("files")
    if isinstance(files, list):
        rendered: dict[str, dict[str, Any]] = {}
        for item in files:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file_path") or item.get("filePath") or "")
            if not file_path:
                continue
            try:
                rendered[file_path] = {
                    "ok": True,
                    "lines": render_file_diff(
                        workspace=workspace,
                        file_path=file_path,
                        prev_hash=item.get("prev_hash"),
                        cur_hash=item.get("cur_hash"),
                    ),
                }
            except Exception as exc:
                rendered[file_path] = {"ok": False, "error": str(exc)}
        return {"ok": True, "files": rendered}

    rows = render_file_diff(
        workspace=workspace,
        file_path=str(payload["file_path"]),
        prev_hash=payload.get("prev_hash"),
        cur_hash=payload.get("cur_hash"),
    )
    return {"ok": True, "lines": rows}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        result = render_payload(payload)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
