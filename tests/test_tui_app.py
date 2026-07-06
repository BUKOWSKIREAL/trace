import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.widgets import Static

from core.repository import Repository
from daemon import ipc
from models.agent import AgentAttribution
from models.change import Change
from tui.app import TraceApp
from tui.controller import TraceController
from tui.views.commits import CommitsView


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

    async def test_drains_new_commit_event_into_status(self):
        daemon = _FakeDaemon()
        app = TraceApp(daemon=daemon)
        async with app.run_test() as pilot:
            await pilot.pause()
            ipc.emit("new_commit", commit_id=7, agent="claude")
            await pilot.pause(0.6)  # let the drain interval fire
            status = app.query_one("#status-line", Static)
            self.assertIn("7", str(status.render()))

    async def test_commits_tab_hosts_commits_view_and_refreshes_on_new_commit(self):
        from daemon import ipc as _ipc

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            repo = Repository(ws)
            repo.init_if_needed()
            controller = TraceController(repo, ws)

            daemon = _FakeDaemon()
            daemon.repo = repo
            daemon.workspace = ws

            app = TraceApp(daemon=daemon, controller=controller)
            async with app.run_test() as pilot:
                await pilot.pause()
                view = app.query_one(CommitsView)
                self.assertEqual(len(view.commit_list.children), 0)

                a = ws / "a.txt"
                a.write_text("hi", encoding="utf-8")
                change = Change(
                    file_path=a,
                    event_time=0.0,
                    attribution=AgentAttribution(agent="human", confidence=0.95),
                    kind="upsert",
                )
                repo.commit("human", [change])
                _ipc.emit("new_commit", commit_id=1, agent="human")
                await pilot.pause(0.6)

                self.assertEqual(len(view.commit_list.children), 1)

    async def test_agents_and_workspace_tabs_are_populated(self):
        import tempfile
        from pathlib import Path as _Path
        from core.repository import Repository
        from tui.views.agents import AgentsView
        from tui.views.workspace import WorkspaceView

        with tempfile.TemporaryDirectory() as tmp:
            ws = _Path(tmp)
            repo = Repository(ws)
            repo.init_if_needed()
            controller = TraceController(repo, ws)

            daemon = _FakeDaemon()
            daemon.repo = repo
            daemon.workspace = ws

            app = TraceApp(daemon=daemon, controller=controller)
            async with app.run_test() as pilot:
                await pilot.pause()
                self.assertIsInstance(app.query_one(AgentsView), AgentsView)
                self.assertIsInstance(app.query_one(WorkspaceView), WorkspaceView)
                # agents view is populated from the preset agents
                self.assertGreaterEqual(len(app.query_one(AgentsView).agent_list.children), 5)


if __name__ == "__main__":
    unittest.main()
