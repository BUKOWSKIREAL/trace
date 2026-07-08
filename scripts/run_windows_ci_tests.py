#!/usr/bin/env python3
"""Run the full unittest suite in a Windows-friendly way.

The Phase 6 product is pure Python/Textual, so Windows CI no longer builds a
PyInstaller/Electron artifact. This helper remains for local Windows shells that
want the same unittest discovery command as CI.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
