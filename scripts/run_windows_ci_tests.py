#!/usr/bin/env python3
"""Run the unittest modules that are reliable on Windows CI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WINDOWS_CI_MODULES = (
    "tests.test_activity_recorder",
    "tests.test_binary_file_lifecycle_handlers",
    "tests.test_codex_hook",
    "tests.test_cursor_mcp_setup",
    "tests.test_daemon_manager",
    "tests.test_demo_and_packaging",
    "tests.test_detectors_cli",
    "tests.test_electron_bridge",
    "tests.test_electron_diff_bridge",
    "tests.test_electron_init_bridge",
    "tests.test_electron_mcp_setup_runtime",
    "tests.test_electron_renderer",
    "tests.test_electron_restore_bridge",
    "tests.test_handlers",
    "tests.test_ipc",
    "tests.test_menubar_app",
    "tests.test_p2_repository",
    "tests.test_path_deduper",
    "tests.test_repository",
    "tests.test_trace_mcp_server",
    "tests.test_transcript_detector",
    "tests.test_tray",
    "tests.test_watcher_handler",
    "tests.test_windows_startup",
    "tests.test_workspace_resolution",
)


def main() -> int:
    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module_name in WINDOWS_CI_MODULES:
        suite.addTests(loader.loadTestsFromName(module_name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
