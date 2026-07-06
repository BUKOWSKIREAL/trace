import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts import setup_cursor_mcp  # noqa: E402


class TestCursorMcpSetup(unittest.TestCase):
    def test_default_workspace_is_project_root_not_test_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "Cursor" / "User" / "mcp.json"
            output = StringIO()
            with (
                patch.object(setup_cursor_mcp, "get_cursor_config_path", return_value=config_path),
                patch("builtins.input", return_value=""),
                redirect_stdout(output),
            ):
                setup_cursor_mcp.setup_trace_mcp(auto_confirm=True)

            config = json.loads(config_path.read_text(encoding="utf-8"))
            trace = config["mcpServers"]["trace"]

        self.assertEqual(Path(trace["args"][-1]), ROOT.resolve())
        self.assertNotIn("test_workspace", trace["args"][-1])

    def test_windows_uses_py_launcher_when_writing_cursor_config(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "Cursor" / "User" / "mcp.json"
            workspace = Path(td) / "workspace"
            workspace.mkdir()
            output = StringIO()
            with (
                patch.object(setup_cursor_mcp, "get_cursor_config_path", return_value=config_path),
                patch.object(setup_cursor_mcp.platform, "system", return_value="Windows"),
                redirect_stdout(output),
            ):
                setup_cursor_mcp.setup_trace_mcp(workspace, auto_confirm=True)

            config = json.loads(config_path.read_text(encoding="utf-8"))
            trace = config["mcpServers"]["trace"]

        self.assertEqual(trace["command"], "py")
        self.assertEqual(Path(trace["args"][-1]), workspace.resolve())


if __name__ == "__main__":
    unittest.main()
