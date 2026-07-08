# TUI Commits View (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the empty "Commits" tab from Phase 1 into the real, primary view: a timeline list on the left, a colorized diff on the right, restore-single-file, and ambiguous-attribution reassignment — porting the full behavior of the existing Electron `onSelectCommit` flow.

**Architecture:** All diff-assembly business logic (union of changed files between a commit and its predecessor, new/modified/deleted classification, 800-line truncation) lives in `TraceController.get_commit_diff()` as a pure, independently-testable method — mirroring what the Vue `onSelectCommit` function currently does client-side. The `CommitsView` widget only renders what the controller returns and forwards user actions (restore, reassign) back through the controller. Two `ModalScreen`s (restore confirm, reassign picker) handle the two destructive/corrective actions.

**Tech Stack:** Python 3.13, Textual 8.2.8 (`ListView`, `RichLog`, `ModalScreen`, `Button`), `unittest` + Textual `Pilot`.

**Prerequisite:** Phase 1 (`docs/superpowers/plans/2026-07-06-tui-foundation.md`) is complete on branch `feat/tui-foundation` (commit `6c8aa30`). This plan continues on that same branch.

**Scope note:** This is Phase 2 of the migration (spec: `docs/superpowers/specs/2026-07-06-electron-to-tui-migration-design.md`). It builds ONLY the Commits view. Per-agent revert (`revert_agent`/`preview_revert_agent` — already in `TraceController` from Phase 1) belongs to the Agents view and is NOT wired into any UI here. Agents/Workspace/MCP views and Electron/packaging teardown are later phases.

---

## Reference: exact algorithm being ported (from `electron_app/src/App.vue`, `onSelectCommit`)

```
prev_id = get_prev_commit_id(commit_id)          # SQL: id < commit_id ORDER BY id DESC LIMIT 1, or None
cur_manifest = get_manifest(commit_id)            # SQL: SELECT file_path, blob_hash FROM snapshots WHERE commit_id = ?
prev_manifest = get_manifest(prev_id) if prev_id else []
cur_map = {file_path: blob_hash for row in cur_manifest}
prev_map = {file_path: blob_hash for row in prev_manifest}
for file_path in sorted(set(cur_map) | set(prev_map)):
    cur, prev = cur_map.get(file_path), prev_map.get(file_path)
    if cur == prev: continue                      # unchanged, skip
    status = "new" if prev is None else "deleted" if cur is None else "modified"
    can_restore = cur is not None                  # nothing to restore forward if file was deleted
    lines = render_file_diff(workspace, file_path, prev, cur)
    lines = lines[:800] + ["... (truncated N lines)"] if len(lines) > 800 else lines
```

`MAX_DIFF_LINES = 800` (from `App.vue:564`). An "uncertain" commit is `commit["author_agent"] == "unknown" and len(commit["candidates"]) > 0`.

## Reference: how to create commits in tests (real `Repository.commit` API)

`Repository.commit(agent: str, changes: list[Change], attribution=None, *, summary=None) -> int | None`. Each `Change` is `models.change.Change(file_path: Path, event_time: float, attribution: AgentAttribution, kind: "upsert"|"delete" = "upsert")` — **not** a dict. This mirrors the existing helper in `tests/test_repository.py`:

```python
def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(
        file_path=path,
        event_time=time.time(),
        attribution=AgentAttribution(agent=agent, confidence=0.95),
        kind=kind,
    )
```

Every new test file in this plan defines its own local copy of this exact helper (same shape, default `agent="human"`) — do not import it from `tests/test_repository.py` (keep test files independent). To create a file and commit it as "new": write the file to disk, then `repo.commit("human", [make_change(path)])`. To commit a modification: overwrite the file, then commit again with a fresh `make_change(path)`. To commit a deletion: delete the file from disk, then commit with `make_change(path, kind="delete")`.

---

## File Structure

- `code/core/repository.py` — add `get_manifest`, `get_prev_commit_id` methods.
- `code/tui/controller.py` — add `get_manifest`, `get_prev_commit_id`, `get_commit_diff` methods.
- `code/tui/views/__init__.py` — new package marker.
- `code/tui/views/commits.py` — `CommitsView` widget (list + diff pane) + `RestoreConfirmModal` + `ReassignModal`.
- `code/tui/app.py` — mount `CommitsView` in the Commits tab; refresh it on `new_commit` IPC events.
- `tests/test_repository_manifest_helpers.py` — repository-level tests.
- `tests/test_tui_controller.py` — extend with diff-assembly tests.
- `tests/test_tui_commits_view.py` — Pilot-driven view tests.

Run all tests with: `uv run python -m unittest discover -s tests`

---

## Task 1: `Repository.get_manifest` and `Repository.get_prev_commit_id`

**Files:**
- Modify: `code/core/repository.py`
- Test: `tests/test_repository_manifest_helpers.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_repository_manifest_helpers.py`:

```python
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from core.repository import Repository
from models.agent import AgentAttribution
from models.change import Change


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(
        file_path=path,
        event_time=time.time(),
        attribution=AgentAttribution(agent=agent, confidence=0.95),
        kind=kind,
    )


class RepositoryManifestHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_prev_commit_id_returns_none_before_any_commit(self):
        self.assertIsNone(self.repo.get_prev_commit_id(1))

    def test_get_manifest_and_prev_commit_id_across_two_commits(self):
        a = self.ws / "a.txt"
        a.write_text("one", encoding="utf-8")
        c1 = self.repo.commit("human", [make_change(a)])

        a.write_text("two", encoding="utf-8")
        c2 = self.repo.commit("human", [make_change(a)])

        self.assertIsNone(self.repo.get_prev_commit_id(c1))
        self.assertEqual(self.repo.get_prev_commit_id(c2), c1)

        manifest1 = self.repo.get_manifest(c1)
        manifest2 = self.repo.get_manifest(c2)
        self.assertEqual({row["file_path"] for row in manifest1}, {"a.txt"})
        self.assertEqual({row["file_path"] for row in manifest2}, {"a.txt"})
        self.assertNotEqual(
            next(r["blob_hash"] for r in manifest1 if r["file_path"] == "a.txt"),
            next(r["blob_hash"] for r in manifest2 if r["file_path"] == "a.txt"),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_repository_manifest_helpers -v`
Expected: FAIL/ERROR — `AttributeError: 'Repository' object has no attribute 'get_prev_commit_id'` (or `get_manifest`).

- [ ] **Step 3: Implement the two methods**

In `code/core/repository.py`, add these methods to the `Repository` class (directly after `list_commits`):

```python
    def get_manifest(self, commit_id: int) -> list[dict]:
        """返回某次 commit 的完整文件清单 [{file_path, blob_hash}, ...]。"""
        conn = get_connection(self.db_path)
        rows = conn.execute(
            "SELECT file_path, blob_hash FROM snapshots WHERE commit_id = ?",
            (commit_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_prev_commit_id(self, commit_id: int) -> int | None:
        """返回给定 commit 之前最近的一次 commit id；不存在则 None。"""
        conn = get_connection(self.db_path)
        row = conn.execute(
            "SELECT id FROM commits WHERE id < ? ORDER BY id DESC LIMIT 1",
            (commit_id,),
        ).fetchone()
        return row["id"] if row is not None else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_repository_manifest_helpers -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/core/repository.py tests/test_repository_manifest_helpers.py
git commit -m "feat(repo): add get_manifest and get_prev_commit_id"
```

---

## Task 2: `TraceController.get_commit_diff` — the diff-assembly algorithm

**Files:**
- Modify: `code/tui/controller.py`
- Test: `tests/test_tui_controller.py`

- [ ] **Step 1: Write the failing tests (append to `tests/test_tui_controller.py`)**

First, add these imports at the top of the existing `tests/test_tui_controller.py` if not already present (check before adding — don't duplicate `sys`/`tempfile`/`unittest`/`Path`/`Repository`/`TraceController` which Phase 1 already added):

```python
import time

from models.agent import AgentAttribution
from models.change import Change


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(
        file_path=path,
        event_time=time.time(),
        attribution=AgentAttribution(agent=agent, confidence=0.95),
        kind=kind,
    )
```

Then append this test class to the file (keep `TraceControllerHappyPath` and `TraceControllerErrorContract` as they are):

```python
class TraceControllerCommitDiff(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_commit_shows_all_files_as_new(self):
        a = self.ws / "a.txt"
        a.write_text("hello\n", encoding="utf-8")
        c1 = self.repo.commit("human", [make_change(a)])

        result = self.controller.get_commit_diff(c1)
        self.assertTrue(result["ok"])
        files = result["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["path"], "a.txt")
        self.assertEqual(files[0]["status"], "new")
        self.assertTrue(files[0]["can_restore"])
        self.assertIsInstance(files[0]["lines"], list)

    def test_second_commit_shows_modified_and_marks_deleted_not_restorable(self):
        a = self.ws / "a.txt"
        b = self.ws / "b.txt"
        a.write_text("one\n", encoding="utf-8")
        b.write_text("keep me\n", encoding="utf-8")
        self.repo.commit("human", [make_change(a), make_change(b)])

        a.write_text("two\n", encoding="utf-8")
        b.unlink()
        c2 = self.repo.commit("human", [make_change(a), make_change(b, kind="delete")])

        result = self.controller.get_commit_diff(c2)
        self.assertTrue(result["ok"])
        by_path = {f["path"]: f for f in result["files"]}
        self.assertEqual(by_path["a.txt"]["status"], "modified")
        self.assertTrue(by_path["a.txt"]["can_restore"])
        self.assertEqual(by_path["b.txt"]["status"], "deleted")
        self.assertFalse(by_path["b.txt"]["can_restore"])

    def test_unchanged_files_are_excluded(self):
        a = self.ws / "a.txt"
        b = self.ws / "b.txt"
        a.write_text("one\n", encoding="utf-8")
        b.write_text("stays the same\n", encoding="utf-8")
        self.repo.commit("human", [make_change(a), make_change(b)])

        a.write_text("two\n", encoding="utf-8")
        c2 = self.repo.commit("human", [make_change(a)])

        result = self.controller.get_commit_diff(c2)
        paths = {f["path"] for f in result["files"]}
        self.assertEqual(paths, {"a.txt"})

    def test_truncates_long_diffs_at_800_lines(self):
        a = self.ws / "a.txt"
        a.write_text("\n".join(str(i) for i in range(5)), encoding="utf-8")
        self.repo.commit("human", [make_change(a)])

        a.write_text("\n".join(str(i) for i in range(2000)), encoding="utf-8")
        c2 = self.repo.commit("human", [make_change(a)])

        result = self.controller.get_commit_diff(c2)
        lines = result["files"][0]["lines"]
        self.assertEqual(len(lines), 801)  # 800 real lines + 1 truncation marker
        self.assertIn("truncated", lines[-1]["text"])

    def test_unknown_commit_id_returns_empty_file_list(self):
        result = self.controller.get_commit_diff(999)
        self.assertTrue(result["ok"])
        self.assertEqual(result["files"], [])


if __name__ == "__main__":
    unittest.main()
```

> If `tests/test_tui_controller.py` already ends with an `if __name__ == "__main__": unittest.main()` block from Phase 1, don't duplicate it — just append the new class above that existing block.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_tui_controller -v`
Expected: FAIL/ERROR — `AttributeError: 'TraceController' object has no attribute 'get_commit_diff'`.

- [ ] **Step 3: Implement `get_commit_diff`**

Add the module-level constant near the top of `code/tui/controller.py` (after the imports):

```python
_MAX_DIFF_LINES = 800
```

Add these methods to `TraceController`:

```python
    def get_manifest(self, commit_id: int) -> dict[str, Any]:
        try:
            return {"ok": True, "manifest": self._repo.get_manifest(commit_id)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def get_prev_commit_id(self, commit_id: int) -> dict[str, Any]:
        try:
            return {"ok": True, "prev_id": self._repo.get_prev_commit_id(commit_id)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def get_commit_diff(self, commit_id: int) -> dict[str, Any]:
        """Assemble the full diff view for a commit: changed files + rendered lines.

        Ports the algorithm from the Electron console's onSelectCommit: union the
        current and previous commit's manifests, classify each changed path as
        new/modified/deleted, render its diff, and truncate long diffs.
        """
        try:
            prev_id = self._repo.get_prev_commit_id(commit_id)
            cur_manifest = self._repo.get_manifest(commit_id)
            prev_manifest = self._repo.get_manifest(prev_id) if prev_id is not None else []

            cur_map = {row["file_path"]: row["blob_hash"] for row in cur_manifest}
            prev_map = {row["file_path"]: row["blob_hash"] for row in prev_manifest}

            files: list[dict[str, Any]] = []
            for file_path in sorted(set(cur_map) | set(prev_map)):
                cur_hash = cur_map.get(file_path)
                prev_hash = prev_map.get(file_path)
                if cur_hash == prev_hash:
                    continue
                if prev_hash is None:
                    status = "new"
                elif cur_hash is None:
                    status = "deleted"
                else:
                    status = "modified"

                lines = render_file_diff(self._workspace, file_path, prev_hash, cur_hash)
                if len(lines) > _MAX_DIFF_LINES:
                    omitted = len(lines) - _MAX_DIFF_LINES
                    lines = lines[:_MAX_DIFF_LINES] + [
                        {"tag": "meta", "text": f"... (truncated {omitted} lines)"}
                    ]

                files.append({
                    "path": file_path,
                    "status": status,
                    "prev_hash": prev_hash,
                    "cur_hash": cur_hash,
                    "can_restore": cur_hash is not None,
                    "lines": lines,
                })

            return {"ok": True, "files": files}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_tui_controller -v`
Expected: PASS (all tests in the file, including the 5 new ones).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/controller.py tests/test_tui_controller.py
git commit -m "feat(tui): add TraceController.get_commit_diff diff-assembly algorithm"
```

---

## Task 3: `CommitsView` — timeline list + diff pane

**Files:**
- Create: `code/tui/views/__init__.py`
- Create: `code/tui/views/commits.py`
- Test: `tests/test_tui_commits_view.py`

- [ ] **Step 1: Create the views package marker**

Create `code/tui/views/__init__.py`:

```python
"""Trace TUI views — one module per tab."""
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_tui_commits_view.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_tui_commits_view -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'tui.views.commits'`.

- [ ] **Step 4: Implement `CommitsView`**

Create `code/tui/views/commits.py`:

```python
"""CommitsView — timeline list (left) + diff pane (right)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, RichLog

_STATUS_MARK = {"new": "[+ new]", "modified": "[~ mod]", "deleted": "[- del]"}
_TAG_STYLE = {"added": "green", "removed": "red", "meta": "dim"}


class CommitsView(Widget):
    """Shows the commit timeline and the diff for whichever commit is selected."""

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
```

> Note: verify `ListView.append()`/`ListView.clear()` are coroutines in the installed Textual version: `uv run python -c "import inspect, textual.widgets as w; print(inspect.iscoroutinefunction(w.ListView.append), inspect.iscoroutinefunction(w.ListView.clear))"`. If either prints `False`, drop the `await` on that specific call only — leave everything else as written.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_tui_commits_view -v`
Expected: PASS (2 tests). If `RichLog.lines` isn't the right attribute to introspect written content, check `uv run python -c "import textual.widgets as w; print([a for a in dir(w.RichLog) if not a.startswith('_')])"` and adjust the test assertion to whatever attribute holds rendered content — keep the test's INTENT (diff text contains "a.txt") unchanged.

- [ ] **Step 6: Commit**

```bash
cd ~/trace
git add code/tui/views/__init__.py code/tui/views/commits.py tests/test_tui_commits_view.py
git commit -m "feat(tui): add CommitsView with timeline list and diff pane"
```

---

## Task 4: Restore-file modal

**Files:**
- Modify: `code/tui/views/commits.py`
- Test: `tests/test_tui_commits_view.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_tui_commits_view.py`, inside `CommitsViewBehavior`)**

```python
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
```

> `view._commit_ids` is ordered newest-first (matches `Repository.list_commits`'s `ORDER BY id DESC`), so `view._commit_ids[-1]` is the OLDEST commit — the one whose file content was `"one\n"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_tui_commits_view.CommitsViewBehavior.test_restore_key_opens_modal_listing_restorable_files_and_restores_on_confirm -v`
Expected: FAIL/ERROR — `AttributeError: 'CommitsView' object has no attribute 'action_restore_selected_file'`.

- [ ] **Step 3: Implement `RestoreConfirmModal` and the restore action**

Add these imports to the top of `code/tui/views/commits.py`:

```python
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button
```

Add the modal class (after the module constants, before `CommitsView`):

```python
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
```

Add the key binding as a class attribute on `CommitsView` (add this line right after the `class CommitsView(Widget):` line, before `__init__`):

```python
    BINDINGS = [("r", "restore_selected_file", "Restore file")]
```

Add the action method to `CommitsView`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests.test_tui_commits_view -v`
Expected: PASS (all tests in the file, including the new one). If `push_screen`'s return value needs to be awaited differently for the modal to actually be pushed synchronously within the test (check by printing `app.screen` right after the call), adjust the test to match — keep the assertions (modal type, file content restored) the same.

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/views/commits.py tests/test_tui_commits_view.py
git commit -m "feat(tui): add restore-file confirmation modal and 'r' keybinding"
```

---

## Task 5: Reassign-commit modal for ambiguous attribution

**Files:**
- Modify: `code/tui/views/commits.py`
- Test: `tests/test_tui_commits_view.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_tui_commits_view.py`, inside `CommitsViewBehavior`)**

```python
    async def test_reassign_key_opens_modal_for_uncertain_commit_and_applies_choice(self):
        a = self.ws / "a.txt"
        a.write_text("one\n", encoding="utf-8")
        c1 = self.repo.commit("human", [make_change(a)])
        self.repo.reassign_commit(c1, "unknown")

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(CommitsView)
            await view.refresh_commits()
            await pilot.pause()
            await view.select_commit(c1)
            await pilot.pause()
            view._commits_by_id[c1]["candidates"] = ["claude", "codex"]

            await view.action_reassign_selected_commit()
            await pilot.pause()
            from tui.views.commits import ReassignModal
            modal = app.screen
            self.assertIsInstance(modal, ReassignModal)

            await modal.choose("codex")
            await pilot.pause()

            updated = self.controller.list_commits()["commits"]
            reassigned = next(c for c in updated if c["id"] == c1)
            self.assertEqual(reassigned["author_agent"], "codex")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_tui_commits_view.CommitsViewBehavior.test_reassign_key_opens_modal_for_uncertain_commit_and_applies_choice -v`
Expected: FAIL/ERROR — `AttributeError: 'CommitsView' object has no attribute 'action_reassign_selected_commit'`.

- [ ] **Step 3: Implement `ReassignModal` and the reassign action**

Add the modal class to `code/tui/views/commits.py` (near `RestoreConfirmModal`):

```python
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
            yield ListView(
                *[ListItem(Label(name), id=f"agent-{name}") for name in self._candidates],
                id="agent-choices",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = event.item.id.removeprefix("agent-")
        self.run_worker(self.choose(name))

    async def choose(self, agent: str) -> None:
        result = self._controller.reassign_commit(self._commit_id, agent)
        self.dismiss(agent if result.get("ok") else None)
```

Add `ListView` to the existing `from textual.widgets import ...` import line at the top of the file if it isn't already imported (it already is, from Task 3 — verify, don't duplicate the import).

Update the `BINDINGS` class attribute on `CommitsView`:

```python
    BINDINGS = [
        ("r", "restore_selected_file", "Restore file"),
        ("a", "reassign_selected_commit", "Reassign agent"),
    ]
```

Add the action method to `CommitsView`:

```python
    async def action_reassign_selected_commit(self) -> None:
        if self._selected_commit_id is None:
            return
        commit = self._commits_by_id.get(self._selected_commit_id)
        if commit is None:
            return
        candidates = commit.get("candidates") or []
        modal = ReassignModal(self._selected_commit_id, list(candidates), self._controller)
        await self.app.push_screen(modal)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests.test_tui_commits_view -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/views/commits.py tests/test_tui_commits_view.py
git commit -m "feat(tui): add reassign-commit modal for ambiguous attribution"
```

---

## Task 6: Wire `CommitsView` into `TraceApp` and refresh it on live commits

**Files:**
- Modify: `code/tui/app.py`
- Test: `tests/test_tui_app.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_tui_app.py`, inside `TraceAppShell`)**

Add these imports at the top of `tests/test_tui_app.py` (check what's already there from Phase 1 before adding — don't duplicate):

```python
import tempfile

from core.repository import Repository
from tui.controller import TraceController
from tui.views.commits import CommitsView
from models.agent import AgentAttribution
from models.change import Change
```

Add this method to `TraceAppShell`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_tui_app -v`
Expected: FAIL — `TypeError: TraceApp.__init__() got an unexpected keyword argument 'controller'`.

- [ ] **Step 3: Wire the controller and `CommitsView` into `TraceApp`**

Modify `code/tui/app.py`. Add to the imports:

```python
from tui.controller import TraceController
from tui.views.commits import CommitsView
```

Change `__init__` to accept an optional controller (falls back to building one from the daemon):

```python
    def __init__(self, daemon, controller: TraceController | None = None) -> None:
        super().__init__()
        self._daemon = daemon
        self._controller = controller or TraceController(daemon.repo, daemon.workspace)
```

Change `compose` to mount `CommitsView` instead of the placeholder `Static` in the Commits tab only (leave the other three tabs' `Static` placeholders untouched — those are later phases):

```python
            with TabPane("Commits", id="tab-commits"):
                yield CommitsView(self._controller)
```

Update `_drain_ipc` so a `new_commit` event also refreshes the Commits view:

```python
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
```

- [ ] **Step 4: Confirm the Phase-1 tests still pass with a bare fake daemon**

The existing `test_has_four_named_tabs` and `test_drains_new_commit_event_into_status` construct `TraceApp(daemon=_FakeDaemon())` where `_FakeDaemon.repo` is `None`. `TraceController(None, Path("/tmp"))` doesn't fail at construction — only when a method touches `self._repo`, and every controller method already catches exceptions and returns `{"ok": False, "error": ...}`. `CommitsView.refresh_commits` already treats a non-ok result as "no commits" (`commits = result.get("commits", []) if result.get("ok") else []` from Task 3), so mounting `CommitsView` should not crash these two tests.

Run: `uv run python -m unittest tests.test_tui_app.TraceAppShell.test_has_four_named_tabs tests.test_tui_app.TraceAppShell.test_drains_new_commit_event_into_status -v`
Expected: PASS. If either fails, the fix belongs in `CommitsView.refresh_commits`'s error handling (make it tolerate an erroring controller), not in the test.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `uv run python -m unittest tests.test_tui_app -v`
Expected: PASS (all tests in the file).

- [ ] **Step 6: Commit**

```bash
cd ~/trace
git add code/tui/app.py tests/test_tui_app.py
git commit -m "feat(tui): mount CommitsView in the Commits tab and refresh it on new_commit"
```

---

## Task 7: Full-suite check + manual smoke

- [ ] **Step 1: Run the whole suite**

Run: `uv run python -m unittest discover -s tests`
Expected: all pass, zero failures. (Baseline was 365 after Phase 1; this phase adds roughly 14 new tests across the four test files — the exact count doesn't matter, zero failures does.)

- [ ] **Step 2: Manual smoke (human-run, optional in CI)**

Run: `uv run python code/main.py --workspace test_workspace`
Expected: the Commits tab shows a real timeline list; selecting a commit (arrow keys + Enter, or click) renders its diff on the right with colored +/-/meta lines; pressing `r` after selecting a commit with a restorable file opens the restore confirmation modal, and confirming restores that file's content in the workspace; for a commit with ambiguous attribution, pressing `a` opens the reassign modal and picking an agent updates the commit's author. Press `q` to exit; daemon stops cleanly.

- [ ] **Step 3: Commit any smoke-driven fixes**

```bash
cd ~/trace
git commit -am "fix(tui): commits-view smoke-test adjustments" || echo "nothing to fix"
```

---

## Self-Review notes

- **Spec coverage (this phase):** design spec §4.2 `commits.py` view (Tasks 3-5), §4.3 read/write/realtime data flow for Commits (Tasks 2,3,6), §4 "restore + reassign" full-functionality-parity decision (Tasks 4-5), §5 error handling via controller `{ok}` contract (Task 2, reused everywhere). Per-agent revert intentionally excluded (belongs to the Agents view, a later phase) — noted in Scope note.
- **Type consistency:** `get_commit_diff` returns `{"ok", "files": [{"path","status","prev_hash","cur_hash","can_restore","lines"}]}` consistently used by `CommitsView.select_commit`, `action_restore_selected_file`, and all tests. `TraceApp(daemon, controller=None)` signature is additive (keeps Phase 1 call sites working). All test `Change` construction now matches the REAL `Repository.commit(agent, list[Change])` signature verified against `code/core/repository.py` and the existing `tests/test_repository.py` convention — fixed a draft-stage error where changes were dict-shaped.
- **Known API-verification points (flagged inline in the tasks):** `ListView.append`/`clear` sync-vs-async (Task 3), `RichLog` content introspection for tests (Task 3), `push_screen` await/timing behavior (Task 4) — the implementer must check these against the installed Textual API and adapt mechanically, keeping test intent unchanged, exactly as Phase 1 did for `Static.renderable` → `.render()`.
