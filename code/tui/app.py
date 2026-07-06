"""TraceApp — the Textual application shell (Phase 1: empty tabs)."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane


class TraceApp(App):
    TITLE = "Trace"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, daemon) -> None:
        super().__init__()
        self._daemon = daemon

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-commits"):
            with TabPane("Commits", id="tab-commits"):
                yield Static("commits", id="body-commits")
            with TabPane("Agents", id="tab-agents"):
                yield Static("agents", id="body-agents")
            with TabPane("Workspace", id="tab-workspace"):
                yield Static("workspace", id="body-workspace")
            with TabPane("MCP", id="tab-mcp"):
                yield Static("mcp", id="body-mcp")
        yield Static("", id="status-line")
        yield Footer()
