"""CommitsView — timeline list (left) + diff pane (right)."""
from __future__ import annotations

import asyncio

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Label, ListItem, ListView, RichLog

_STATUS_MARK = {"new": "[+ new]", "modified": "[~ mod]", "deleted": "[- del]"}
_TAG_STYLE = {"added": "green", "removed": "red", "meta": "dim"}


class RestoreConfirmModal(ModalScreen[bool | None]):
    """Confirms restoring one file from one commit before touching the workspace.

    Dismisses with True/False for restore success/failure and None on cancel,
    so the caller can tell "user backed out" apart from "restore failed".
    """

    def __init__(self, commit_id: int, file_path: str, controller) -> None:
        super().__init__()
        self._commit_id = commit_id
        self._file_path = file_path
        self._controller = controller

    def compose(self) -> ComposeResult:
        with Vertical(id="restore-modal"):
            yield Label(Text(f"Restore {self._file_path} to commit #{self._commit_id}?"))
            with Horizontal():
                yield Button("Restore", id="confirm", variant="error")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.run_worker(self.confirm())
        else:
            self.dismiss(None)

    async def confirm(self) -> None:
        # restore 会先做全量快照备份，工作区大时不能占住事件循环
        result = await asyncio.to_thread(
            self._controller.restore_file, self._commit_id, self._file_path
        )
        self.dismiss(bool(result.get("ok")))


class ReassignModal(ModalScreen[str | None]):
    """Lets the user pick the correct agent for an ambiguous commit."""

    def __init__(self, commit_id: int, candidates: list[str], controller) -> None:
        super().__init__()
        self._commit_id = commit_id
        self._candidates = candidates if "human" in candidates else candidates + ["human"]
        self._controller = controller

    def compose(self) -> ComposeResult:
        with Vertical(id="reassign-modal"):
            yield Label(f"Who made commit #{self._commit_id}?")
            # id 用序号而不是 agent 名：历史库里可能有 "kimi code" 这种
            # 不满足 Textual identifier 规则的名字
            yield ListView(
                *[
                    ListItem(Label(Text(name)), id=f"agent-{i}")
                    for i, name in enumerate(self._candidates)
                ],
                id="agent-choices",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = int(event.item.id.removeprefix("agent-"))
        self.run_worker(self.choose(self._candidates[index]))

    async def choose(self, agent: str) -> None:
        result = self._controller.reassign_commit(self._commit_id, agent)
        self.dismiss(agent if result.get("ok") else None)


class CommitsView(Widget):
    """Shows the commit timeline and the diff for whichever commit is selected."""

    BINDINGS = [
        ("r", "restore_selected_file", "Restore file"),
        ("a", "reassign_selected_commit", "Reassign agent"),
    ]

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
        if self._controller is None:
            return
        await self.refresh_commits()

    async def refresh_commits(self) -> None:
        if self._controller is None:
            return
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
            await list_view.append(ListItem(Label(Text(label)), id=f"commit-{commit['id']}"))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "commit-list":
            return
        commit_id = int(event.item.id.removeprefix("commit-"))
        await self.select_commit(commit_id)

    async def select_commit(self, commit_id: int) -> None:
        log = self.query_one("#diff-log", RichLog)
        log.clear()
        # diff 组装要读 blob 并跑 handler（docx/pdf 解析可能上秒级），放线程池
        result = await asyncio.to_thread(self._controller.get_commit_diff, commit_id)
        self._selected_commit_id = commit_id
        self._selected_files = result.get("files", []) if result.get("ok") else []
        if not result.get("ok"):
            log.write(Text(f"diff failed: {result.get('error')}", style="red"))
            return
        for file in result["files"]:
            mark = _STATUS_MARK.get(file["status"], file["status"])
            log.write(Text(f"{mark} {file['path']}", style="bold"))
            for line in file["lines"]:
                style = _TAG_STYLE.get(line.get("tag"), "")
                log.write(Text(line.get("text", ""), style=style))

    async def action_restore_selected_file(self) -> None:
        if self._selected_commit_id is None:
            return
        restorable = [f for f in self._selected_files if f["can_restore"]]
        if not restorable:
            return
        # v1: act on the first restorable file in the current diff view.
        target = restorable[0]
        modal = RestoreConfirmModal(self._selected_commit_id, target["path"], self._controller)
        await self.app.push_screen(modal, self._after_restore)

    def _after_restore(self, ok: bool | None) -> None:
        if ok is None:  # cancelled
            return
        if ok:
            self.app.notify("file restored")
        else:
            self.app.notify("restore failed", severity="error")

    async def action_reassign_selected_commit(self) -> None:
        if self._selected_commit_id is None:
            return
        commit = self._commits_by_id.get(self._selected_commit_id)
        if commit is None:
            return
        candidates = commit.get("candidates") or []
        modal = ReassignModal(self._selected_commit_id, list(candidates), self._controller)
        await self.app.push_screen(modal, self._after_reassign)

    def _after_reassign(self, agent: str | None) -> None:
        """Reassignment changes the DB without emitting an IPC event, so the
        timeline must be refreshed here or it keeps showing the old agent."""
        if agent is None:
            return

        async def _refresh() -> None:
            await self.refresh_commits()
            if self._selected_commit_id is not None:
                await self.select_commit(self._selected_commit_id)

        self.run_worker(_refresh(), group="refresh_commits", exclusive=True)
