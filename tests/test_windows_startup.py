"""Windows-compatible startup smoke tests for the pure Python/TUI product."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
CODE = ROOT / "code"
sys.path.insert(0, str(CODE))


class TestWindowsMainStartup(unittest.TestCase):
    def _run_headless_process(
        self, argv: list[str], *, cwd: Path
    ) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3)
        return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)

    def _assert_headless_started(self, proc: subprocess.CompletedProcess) -> None:
        output = f"{proc.stdout or ''}{proc.stderr or ''}"
        self.assertIn("trace.daemon.manager", output)
        self.assertIn("DaemonManager", output)
        self.assertIn("Headless", output)
        if sys.platform != "win32":
            self.assertEqual(proc.returncode, 0, output)

    def test_headless_main_starts_and_exits_on_windows_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            (ws / "sample.txt").write_text("hello", encoding="utf-8")
            proc = self._run_headless_process(
                [
                    sys.executable,
                    str(CODE / "main.py"),
                    "--workspace",
                    str(ws),
                    "--headless",
                ],
                cwd=CODE,
            )
            self._assert_headless_started(proc)

    def test_tui_entrypoint_module_is_importable(self):
        import main
        from tui.app import TraceApp

        self.assertTrue(callable(main.main))
        self.assertTrue(hasattr(main, "_run_with_tui"))
        self.assertTrue(callable(TraceApp))

    def test_legacy_windows_desktop_entrypoints_are_removed(self):
        for rel in (
            "Trace-windows.spec",
            "code/electron_bridge.py",
            "code/menubar",
            "code/views/workspace_picker.py",
        ):
            self.assertFalse((ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
