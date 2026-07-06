"""Windows-safe temporary directories that release SQLite before cleanup."""

from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).parent.parent / "code"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.db import close_all_connections  # noqa: E402


@contextmanager
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        try:
            yield Path(td)
        finally:
            close_all_connections()


@contextmanager
def temp_repository():
    from core.repository import Repository  # noqa: E402

    with temp_dir() as ws:
        yield Repository(ws), ws
