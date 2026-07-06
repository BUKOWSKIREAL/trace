import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from core.repository import Repository
from models.agent import AgentAttribution
from models.change import Change
from tui.controller import TraceController
from tui.views.workspace import WorkspaceView


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(path, time.time(), AgentAttribution(agent=agent, confidence=0.95), kind)


class _Harness(App):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        yield WorkspaceView(self._controller)


class WorkspaceViewBehavior(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name).resolve()
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_shows_workspace_path_and_counts(self):
        a = self.ws / "a.txt"
        a.write_text("1", encoding="utf-8")
        self.repo.commit("human", [make_change(a)])

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(WorkspaceView)
            await view.refresh_summary()
            await pilot.pause()
            table = app.query_one(DataTable)
            self.assertGreaterEqual(table.row_count, 5)
            # the workspace path value must appear somewhere in the table cells
            all_cells = [
                str(table.get_cell_at((r, c)))
                for r in range(table.row_count)
                for c in range(len(table.columns))
            ]
            self.assertTrue(any(str(self.ws) in cell for cell in all_cells))
            self.assertTrue(any(cell == "1" for cell in all_cells))  # commit_count


if __name__ == "__main__":
    unittest.main()
