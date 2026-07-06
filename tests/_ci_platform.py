"""Helpers for platform-specific CI behavior in unittest modules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def skip_on_windows_ci() -> None:
  """Skip an entire test module on Windows CI runners."""
  if sys.platform == "win32":
    raise unittest.SkipTest("skipped on Windows CI")


def path_in_text(text: str, path: Path) -> bool:
  """Match a filesystem path inside serialized config/log text."""
  candidates = {path.name, str(path)}
  if sys.platform == "win32":
    try:
      import os

      candidates.add(os.path.normpath(str(path)))
    except OSError:
      pass
  haystack = text.replace("\\\\", "\\")
  return any(candidate and (candidate in text or candidate in haystack) for candidate in candidates)
