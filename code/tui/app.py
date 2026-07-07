"""TraceApp — the Textual application shell (Phase 1: empty tabs)."""
from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from daemon import ipc
from tui.controller import TraceController
from tui.views.agents import AgentsView
from tui.views.commits import CommitsView
from tui.views.mcp import MCPView
from tui.views.workspace import WorkspacePickerScreen, WorkspaceView


class TraceApp(App):
    TITLE = "Trace"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        daemon,
        controller: TraceController | None = None,
        *,
        pick_workspace: bool = False,
    ) -> None:
        super().__init__()
        self._daemon = daemon
        self._controller = controller
        self._pick_workspace = pick_workspace
        if not pick_workspace and controller is None:
            self._controller = TraceController(
                getattr(daemon, "repo", None), daemon.workspace
            )

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-commits"):
            with TabPane("Commits", id="tab-commits"):
                yield CommitsView(self._controller)
            with TabPane("Agents", id="tab-agents"):
                yield AgentsView(self._controller)
            with TabPane("Workspace", id="tab-workspace"):
                yield WorkspaceView(self._controller)
            with TabPane("MCP", id="tab-mcp"):
                yield MCPView(self._controller)
        yield Static("", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        if self._pick_workspace:
            self.push_screen(WorkspacePickerScreen(initial=None), self._on_workspace_picked)
        self.set_interval(0.5, self._drain_ipc)

    def _on_workspace_picked(self, path: Path | None) -> None:
        if path is None:
            self.exit(0)
            return
        self.serve_workspace(path)

    def serve_workspace(self, path: Path) -> None:
        """Start the daemon for the picked workspace and pop the picker screen."""
        from utils.state import save_last_workspace

        save_last_workspace(path)
        self._daemon.workspace = path
        self._daemon.start(path)
        self._controller = TraceController(
            getattr(self._daemon, "repo", None), path
        )
        # Re-bind the views that were composed with a placeholder controller.
        for view_cls in (CommitsView, AgentsView, WorkspaceView, MCPView):
            try:
                view = self.query_one(view_cls)
                view._controller = self._controller
                refresh = getattr(view, "refresh_commits", None) or getattr(view, "refresh_agents", None) or getattr(view, "refresh_summary", None) or getattr(view, "refresh_setup", None)
                if refresh is not None:
                    self.run_worker(refresh())
            except Exception:
                pass
        if isinstance(self.screen, WorkspacePickerScreen):
            self.pop_screen()

    def _drain_ipc(self) -> None:
        for event in ipc.drain():
            if event.type == "new_commit":
                cid = event.payload.get("commit_id")
                agent = event.payload.get("agent", "?")
                self.query_one("#status-line", Static).update(
                    f"new commit #{cid} by {agent}"
                )
                self.run_worker(self.query_one(CommitsView).refresh_commits())
                self.run_worker(self.query_one(AgentsView).refresh_agents())
                self.run_worker(self.query_one(WorkspaceView).refresh_summary())
            elif event.type == "error":
                self.query_one("#status-line", Static).update(
                    f"[red]{event.payload.get('message', 'error')}[/red]"
                )
