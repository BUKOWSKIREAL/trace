import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.widgets import Static

from daemon import ipc
from tui.app import TraceApp


class _FakeDaemon:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.workspace = Path("/tmp")
        self.repo = None

    def start(self, workspace):
        self.started = True

    def stop(self):
        self.stopped = True


class TraceAppShell(unittest.IsolatedAsyncioTestCase):
    async def test_has_four_named_tabs(self):
        app = TraceApp(daemon=_FakeDaemon())
        async with app.run_test() as pilot:
            await pilot.pause()
            ids = {pane.id for pane in app.query("TabPane")}
        self.assertEqual(ids, {"tab-commits", "tab-agents", "tab-workspace", "tab-mcp"})


if __name__ == "__main__":
    unittest.main()
