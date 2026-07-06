"""WorkspaceView — a key/value summary of the current workspace."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable

_ROW_ORDER = [
    ("workspace", "workspace"),
    ("db_path", "database"),
    ("commit_count", "commits"),
    ("snapshot_count", "snapshots"),
    ("agent_count", "agents"),
]


class WorkspaceView(Widget):
    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        table = DataTable(id="workspace-table", show_cursor=False)
        table.add_columns("key", "value")
        yield table

    async def on_mount(self) -> None:
        await self.refresh_summary()

    async def refresh_summary(self) -> None:
        table = self.query_one("#workspace-table", DataTable)
        table.clear()
        result = self._controller.get_workspace_summary()
        if not result.get("ok"):
            table.add_row("error", str(result.get("error")))
            return
        summary = result["summary"]
        for key, label in _ROW_ORDER:
            table.add_row(label, str(summary.get(key, "—")))
