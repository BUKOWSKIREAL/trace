"""Windows startup smoke tests — lock tray/menu/import paths used by Trace.exe."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
CODE = ROOT / "code"
sys.path.insert(0, str(CODE))


class TestWindowsTrayStartup(unittest.TestCase):
    def test_make_tray_uses_pystray_on_windows(self):
        with patch.object(sys, "platform", "win32"):
            from menubar.tray_base import make_tray
            from menubar.tray_pystray import PystrayTray

            tray = make_tray("Trace")
            self.assertIsInstance(tray, PystrayTray)

    def test_full_menubar_menu_builds_with_real_pystray(self):
        try:
            pystray = importlib.import_module("pystray")
        except ImportError:
            self.skipTest("pystray not installed")

        from menubar.app import TraceApp
        from menubar.tray_pystray import PystrayTray

        daemon = MagicMock()
        daemon.workspace = Path(tempfile.mkdtemp())
        app = TraceApp(daemon=daemon)
        tray = PystrayTray("Trace")

        with patch.object(sys, "platform", "win32"):
            tray.set_menu(app._build_menu())

        icon = tray._icon
        self.assertIsNotNone(icon)
        self.assertGreater(len(icon.menu._items), 5)

    def test_radio_items_use_callable_checked_with_real_pystray(self):
        try:
            importlib.import_module("pystray")
        except ImportError:
            self.skipTest("pystray not installed")
        from menubar.tray_pystray import PystrayTray

        tray = PystrayTray("Trace")
        tray.set_menu([
            {"type": "radio", "label": "自动检测", "group": "agent",
             "checked": True, "callback": MagicMock()},
            {"type": "radio", "label": "Claude Code", "group": "agent",
             "checked": False, "callback": MagicMock()},
        ])
        items = tray._icon.menu._items
        self.assertTrue(callable(items[0]._checked))
        self.assertTrue(items[0].checked)
        self.assertFalse(items[1].checked)

    def test_bundled_electron_lookup_checks_internal_and_sibling_paths(self):
        from menubar.app import _bundled_electron_executable

        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "Trace"
            internal = app_dir / "_internal" / "electron"
            internal.mkdir(parents=True)
            exe = app_dir / "Trace.exe"
            exe.write_text("", encoding="utf-8")
            console = internal / "Trace Console.exe"
            console.write_text("", encoding="utf-8")
            with (
                patch.object(sys, "platform", "win32"),
                patch.object(sys, "executable", str(exe)),
                patch.object(sys, "frozen", True, create=True),
            ):
                self.assertEqual(_bundled_electron_executable(), console.resolve())


class TestWindowsMainStartup(unittest.TestCase):
    def _run_headless_process(self, argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
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

    def test_workspace_picker_module_imports_on_windows(self):
        with patch.object(sys, "platform", "win32"):
            from views.workspace_picker import pick_workspace

            self.assertTrue(callable(pick_workspace))

    def test_electron_bridge_env_for_frozen_windows(self):
        from menubar.app import _electron_bridge_env

        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "Trace"
            app_dir.mkdir()
            exe = app_dir / "Trace.exe"
            exe.write_text("", encoding="utf-8")
            with (
                patch.object(sys, "platform", "win32"),
                patch.object(sys, "executable", str(exe)),
                patch.object(sys, "frozen", True, create=True),
            ):
                env = _electron_bridge_env(app_dir)
            self.assertEqual(
                env["TRACE_PYTHON_EXECUTABLE"],
                str((app_dir / "TraceBridge.exe").resolve()),
            )
            self.assertEqual(env["TRACE_PYTHON_BRIDGE_MODE"], "bridge-exe")

    def test_trace_windows_spec_references_required_modules(self):
        spec = (ROOT / "Trace-windows.spec").read_text(encoding="utf-8")
        for needle in (
            "main.py",
            "electron_bridge.py",
            "menubar.tray_pystray",
            "Trace Console.exe",
        ):
            self.assertIn(needle, spec)


if __name__ == "__main__":
    unittest.main()
