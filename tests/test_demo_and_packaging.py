"""Phase 6 distribution/documentation contract tests.

Trace is now a pure Python/Textual application. These tests ensure the legacy
Electron/menu-bar/desktop-packaging surface does not silently return.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent


class TestDemoDocument(unittest.TestCase):
    def test_demo_uses_uv_and_tui_flow(self):
        text = (ROOT / "DEMO.md").read_text(encoding="utf-8")
        self.assertIn("uv sync", text)
        self.assertIn("uv run python code/main.py", text)
        self.assertIn("Textual TUI", text)
        self.assertNotIn("pip install -r requirements.txt", text)
        self.assertNotIn("cd electron_app", text)
        self.assertNotIn("build_macos_app.sh", text)


class TestPhase6Cleanup(unittest.TestCase):
    def test_legacy_desktop_assets_are_removed(self):
        removed_paths = [
            "electron_app",
            "code/menubar",
            "code/views/workspace_picker.py",
            "code/electron_bridge.py",
            "code/core/electron_diff_bridge.py",
            "setup.py",
            "Trace-windows.spec",
            "install.sh",
            "scripts/build_macos_app.sh",
            "scripts/build_windows_app.ps1",
            "assets/app_icon.icns",
            "assets/app_icon.png",
        ]
        for rel in removed_paths:
            self.assertFalse((ROOT / rel).exists(), rel)

    def test_pyproject_declares_pure_python_tui_entrypoint(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[project.scripts]", text)
        self.assertIn('trace = "main:main"', text)
        self.assertIn("textual", text)
        for forbidden in ("rumps", "pystray", "ttkbootstrap", "py2app", "pyinstaller"):
            self.assertNotIn(forbidden, text.lower())

    def test_ci_runs_unittest_without_node_or_packaging(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("ubuntu-latest", workflow)
        self.assertIn("macos-latest", workflow)
        self.assertIn("windows-latest", workflow)
        self.assertIn("uv run python -m unittest discover -s tests", workflow)
        self.assertNotIn("setup-node", workflow)
        self.assertNotIn("build_windows_app", workflow)
        self.assertNotIn("upload-artifact", workflow)

    def test_readme_documents_trace_mcp_server(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.trace]", text)
        self.assertIn("mcp.trace_server", text)
        self.assertIn("hooks.trace_codex_hook", text)
        self.assertIn("PYTHONPATH", text)
        self.assertIn("trace_record_files", text)
        self.assertIn(".trace/trace_activity.jsonl", text)
        self.assertIn("Textual TUI", text)
        self.assertNotIn("Electron 操作台", text)

    def test_mcp_docs_do_not_publish_stale_setup_instructions(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        mcp_setup = (ROOT / "MCP_SETUP.md").read_text(encoding="utf-8")
        cursor_setup = (ROOT / "CURSOR_SETUP.md").read_text(encoding="utf-8")
        cursor_script = (ROOT / "scripts" / "setup_cursor_mcp.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('command = "/path/to/project/.venv/bin/python"', readme)
        self.assertIn('args = ["-m", "mcp.trace_server"', readme)
        self.assertIn("Cursor 配置", mcp_setup)
        self.assertIn("Codex CLI 配置", mcp_setup)
        self.assertNotIn("Electron 操作台", mcp_setup)
        self.assertIn('"command": "py"', cursor_setup)
        self.assertIn("默认: 项目根目录", cursor_script)
        self.assertNotIn("默认: 项目根目录/test_workspace", cursor_script)

    def test_project_mcp_file_does_not_override_packaged_trace_server(self):
        project_mcp = ROOT / ".mcp.json"
        if not project_mcp.exists():
            return

        config = json.loads(project_mcp.read_text(encoding="utf-8"))
        self.assertNotIn("trace", config.get("mcpServers", {}))


if __name__ == "__main__":
    unittest.main()
