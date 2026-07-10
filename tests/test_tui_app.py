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

    async def test_drains_error_event_with_brackets_as_literal_text(self):
        """error 消息里的 [] 必须按字面量渲染，不能被 Rich markup 解析崩掉。"""
        daemon = _FakeDaemon()
        app = TraceApp(daemon=daemon)
        async with app.run_test() as pilot:
            await pilot.pause()
            ipc.emit("error", message="Flush [claude] 失败: [/bad] not a tag")
            await pilot.pause(0.6)
            status = app.query_one("#status-line", Static)
            self.assertIn("claude", str(status.render()))
            self.assertIn("[/bad]", str(status.render()))

    async def test_commits_tab_hosts_commits_view_and_refreshes_on_new_commit(self):
        from daemon import ipc as _ipc

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
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

    async def test_mcp_tab_hosts_mcp_view(self):
        import tempfile
        from pathlib import Path as _Path
        from core.repository import Repository
        from tui.views.mcp import MCPView

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
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
                view = app.query_one(MCPView)
                self.assertIsInstance(view, MCPView)
                self.assertEqual(len(view.mcp_list.children), 4)

    async def test_pick_workspace_mode_mounts_picker_screen(self):
        from tui.views.workspace import WorkspacePickerScreen

        daemon = _FakeDaemon()
        app = TraceApp(daemon=daemon, pick_workspace=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, WorkspacePickerScreen)

    async def test_pick_workspace_mode_roots_picker_at_picker_initial(self):
        """--choose 时选择屏应该以上次记忆的工作区为 root，而不是 $HOME。"""
        from tui.views.workspace import WorkspacePickerScreen

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp).resolve()
            app = TraceApp(
                daemon=_FakeDaemon(), pick_workspace=True, picker_initial=root
            )
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, WorkspacePickerScreen)
                self.assertEqual(screen.root_path, root)

    async def test_pick_mode_serve_workspace_starts_daemon_and_pops_picker(self):
        import tempfile
        from pathlib import Path as _Path
        from core.repository import Repository
        from tui.views.workspace import WorkspacePickerScreen

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            ws = _Path(tmp)
            repo = Repository(ws)
            repo.init_if_needed()
            daemon = _FakeDaemon()
            daemon.repo = repo

            app = TraceApp(daemon=daemon, pick_workspace=True)
            async with app.run_test() as pilot:
                await pilot.pause()
                self.assertIsInstance(app.screen, WorkspacePickerScreen)
                app.serve_workspace(ws)
                await pilot.pause()
                self.assertTrue(daemon.started)
                self.assertEqual(daemon.workspace, ws)
                # picker is popped; the active screen is now the main app screen
                self.assertNotIsInstance(app.screen, WorkspacePickerScreen)
                # controller got bound
                self.assertIsNotNone(app._controller)

    async def test_pick_mode_cancel_exits_app(self):
        from tui.views.workspace import WorkspacePickerScreen

        daemon = _FakeDaemon()
        app = TraceApp(daemon=daemon, pick_workspace=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            self.assertIsInstance(screen, WorkspacePickerScreen)
            screen.action_cancel()
            await pilot.pause()
            # app.exit was called with 0
            self.assertEqual(app.return_value, 0)


if __name__ == "__main__":
    unittest.main()
