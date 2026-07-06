import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.app import App, ComposeResult
from textual.widgets import RichLog

from core.repository import Repository
from models.agent import AgentAttribution
from models.change import Change
from tui.controller import TraceController
from tui.views.commits import CommitsView


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(
        file_path=path,
        event_time=time.time(),
        attribution=AgentAttribution(agent=agent, confidence=0.95),
        kind=kind,
    )


class _Harness(App):
    """Minimal host app so CommitsView can be tested standalone."""

    def __init__(self, controller: TraceController) -> None:
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        yield CommitsView(self._controller)


class CommitsViewBehavior(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_shows_commits_and_renders_diff_on_selection(self):
        a = self.ws / "a.txt"
        a.write_text("hello\n", encoding="utf-8")
        self.repo.commit("human", [make_change(a)])

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(CommitsView)
            await view.refresh_commits()
            await pilot.pause()
            self.assertEqual(len(view.commit_list.children), 1)

            await view.select_commit(view._commit_ids[0])
            await pilot.pause()
            diff_text = str(app.query_one(RichLog).lines)
            self.assertIn("a.txt", diff_text)

    async def test_empty_repo_shows_no_commits_without_crashing(self):
        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(CommitsView)
            await view.refresh_commits()
            await pilot.pause()
            self.assertEqual(len(view.commit_list.children), 0)

    async def test_restore_key_opens_modal_listing_restorable_files_and_restores_on_confirm(self):
        a = self.ws / "a.txt"
        a.write_text("one\n", encoding="utf-8")
        self.repo.commit("human", [make_change(a)])
        a.write_text("two\n", encoding="utf-8")
        self.repo.commit("human", [make_change(a)])

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(CommitsView)
            await view.refresh_commits()
            await pilot.pause()
            await view.select_commit(view._commit_ids[-1])  # oldest = first commit
            await pilot.pause()

            await view.action_restore_selected_file()
            await pilot.pause()
            from tui.views.commits import RestoreConfirmModal
            modal = app.screen
            self.assertIsInstance(modal, RestoreConfirmModal)

            await modal.confirm()
            await pilot.pause()

            self.assertEqual(a.read_text(encoding="utf-8"), "one\n")


if __name__ == "__main__":
    unittest.main()
