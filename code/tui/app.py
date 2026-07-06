"""TraceApp — the Textual application shell (Phase 1: empty tabs)."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from daemon import ipc
from tui.controller import TraceController
from tui.views.commits import CommitsView


class TraceApp(App):
    TITLE = "Trace"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, daemon, controller: TraceController | None = None) -> None:
        super().__init__()
        self._daemon = daemon
        self._controller = controller or TraceController(
            getattr(daemon, "repo", None), daemon.workspace
        )

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-commits"):
            with TabPane("Commits", id="tab-commits"):
                yield CommitsView(self._controller)
            with TabPane("Agents", id="tab-agents"):
                yield Static("agents", id="body-agents")
            with TabPane("Workspace", id="tab-workspace"):
                yield Static("workspace", id="body-workspace")
            with TabPane("MCP", id="tab-mcp"):
                yield Static("mcp", id="body-mcp")
        yield Static("", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.5, self._drain_ipc)

    def _drain_ipc(self) -> None:
        for event in ipc.drain():
            if event.type == "new_commit":
                cid = event.payload.get("commit_id")
                agent = event.payload.get("agent", "?")
                self.query_one("#status-line", Static).update(
                    f"new commit #{cid} by {agent}"
                )
                self.run_worker(self.query_one(CommitsView).refresh_commits())
            elif event.type == "error":
                self.query_one("#status-line", Static).update(
                    f"[red]{event.payload.get('message', 'error')}[/red]"
                )
