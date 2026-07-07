"""WorkspaceView — a key/value summary of the current workspace."""
from __future__ import annotations

from pathlib import Path

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, DirectoryTree, Label, Static
from textual.widgets._directory_tree import DirectoryTree as _DT


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
        if self._controller is None:
            return
        await self.refresh_summary()

    async def refresh_summary(self) -> None:
        if self._controller is None:
            return
        table = self.query_one("#workspace-table", DataTable)
        table.clear()
        result = self._controller.get_workspace_summary()
        if not result.get("ok"):
            table.add_row("error", str(result.get("error")))
            return
        summary = result["summary"]
        for key, label in _ROW_ORDER:
            table.add_row(label, str(summary.get(key, "—")))


class WorkspacePickerScreen(ModalScreen[Path | None]):
    """A Textual-native directory picker used when no workspace is resolvable."""

    BINDINGS = [
        ("enter", "open", "Open"),
        ("o", "open", "Open"),
        ("escape", "cancel", "Cancel"),
        ("c", "cancel", "Cancel"),
    ]

    def __init__(self, initial: Path | None = None) -> None:
        super().__init__()
        self._initial = initial
        self.selected: Path | None = None

    @property
    def root_path(self) -> Path:
        return self._initial or Path.home()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text("Trace — 选择要追踪的工作目录"))
            yield Label(Text(f"打开: {self.root_path}"), id="picker-current")
            yield DirectoryTree(self.root_path, id="picker-tree")
            with Horizontal():
                yield Button("Open", id="open", variant="success")
                yield Button("Cancel", id="cancel", variant="default")

    def on_directory_tree_directory_selected(
        self, event: _DT.DirectorySelected
    ) -> None:
        self.selected = Path(event.path)
        self.query_one("#picker-current", Label).update(Text(f"打开: {self.selected}"))

    def on_directory_tree_file_selected(self, event: _DT.FileSelected) -> None:
        # Files are not valid workspace selections; clear the current selection.
        self.selected = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open":
            self.action_open()
        elif event.button.id == "cancel":
            self.action_cancel()

    def action_open(self) -> None:
        if self.selected is None or not self.selected.is_dir():
            self.app.notify("请选择一个目录", severity="warning")
            return
        self.dismiss(self.selected)

    def action_cancel(self) -> None:
        self.dismiss(None)
