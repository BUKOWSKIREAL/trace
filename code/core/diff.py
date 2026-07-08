"""Diff rendering helpers shared by the Textual UI.

Storage remains byte-oriented: blobs are read from ``.trace/objects`` by hash,
then rendered through ``HandlerRegistry`` so file-type knowledge stays in the
handler layer.
"""

from __future__ import annotations

import string
from pathlib import Path

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
