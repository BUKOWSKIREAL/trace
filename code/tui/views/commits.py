"""CommitsView — timeline list (left) + diff pane (right)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Label, ListItem, ListView, RichLog

_STATUS_MARK = {"new": "[+ new]", "modified": "[~ mod]", "deleted": "[- del]"}
_TAG_STYLE = {"added": "green", "removed": "red", "meta": "dim"}


class RestoreConfirmModal(ModalScreen[bool]):
    """Confirms restoring one file from one commit before touching the workspace."""

    def __init__(self, commit_id: int, file_path: str, controller) -> None:
        super().__init__()
        self._commit_id = commit_id
        self._file_path = file_path
        self._controller = controller

    def compose(self) -> ComposeResult:
        with Vertical(id="restore-modal"):
            yield Label(f"Restore {self._file_path} to commit #{self._commit_id}?")
            with Horizontal():
                yield Button("Restore", id="confirm", variant="error")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.run_worker(self.confirm())
        else:
            self.dismiss(False)

    async def confirm(self) -> None:
        result = self._controller.restore_file(self._commit_id, self._file_path)
        self.dismiss(bool(result.get("ok")))


class CommitsView(Widget):
    """Shows the commit timeline and the diff for whichever commit is selected."""

    BINDINGS = [("r", "restore_selected_file", "Restore file")]

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self._commit_ids: list[int] = []
        self._commits_by_id: dict[int, dict] = {}
        self._selected_commit_id: int | None = None
        self._selected_files: list[dict] = []

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield ListView(id="commit-list")
            with VerticalScroll(id="diff-pane"):
                yield RichLog(id="diff-log", wrap=False, markup=True)

    @property
    def commit_list(self) -> ListView:
        return self.query_one("#commit-list", ListView)

    async def on_mount(self) -> None:
        await self.refresh_commits()

    async def refresh_commits(self) -> None:
        result = self._controller.list_commits()
        commits = result.get("commits", []) if result.get("ok") else []
        self._commits_by_id = {c["id"]: c for c in commits}
        self._commit_ids = [c["id"] for c in commits]

        list_view = self.commit_list
        await list_view.clear()
        for commit in commits:
            summary = commit.get("summary") or ""
            agent = commit.get("author_agent") or "unknown"
            label = f"#{commit['id']} [{agent}] {summary}"
            await list_view.append(ListItem(Label(label), id=f"commit-{commit['id']}"))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "commit-list":
            return
        commit_id = int(event.item.id.removeprefix("commit-"))
        await self.select_commit(commit_id)

    async def select_commit(self, commit_id: int) -> None:
        log = self.query_one("#diff-log", RichLog)
        log.clear()
        result = self._controller.get_commit_diff(commit_id)
        self._selected_commit_id = commit_id
        self._selected_files = result.get("files", []) if result.get("ok") else []
        if not result.get("ok"):
            log.write(f"[red]diff failed: {result.get('error')}[/red]")
            return
        for file in result["files"]:
            mark = _STATUS_MARK.get(file["status"], file["status"])
            log.write(f"[bold]{mark} {file['path']}[/bold]")
            for line in file["lines"]:
                style = _TAG_STYLE.get(line.get("tag"), "")
                text = line.get("text", "")
                log.write(f"[{style}]{text}[/{style}]" if style else text)

    async def action_restore_selected_file(self) -> None:
        if self._selected_commit_id is None:
            return
        restorable = [f for f in self._selected_files if f["can_restore"]]
        if not restorable:
            return
        # v1: act on the first restorable file in the current diff view.
        target = restorable[0]
        modal = RestoreConfirmModal(self._selected_commit_id, target["path"], self._controller)
        await self.app.push_screen(modal)
