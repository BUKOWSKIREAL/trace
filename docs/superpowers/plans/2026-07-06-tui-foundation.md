# TUI Foundation (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a running Textual TUI that starts the existing Trace daemon in-process, drains its IPC event queue live, and exposes a tested `TraceController` data facade over the existing backend — the foundation every later view builds on.

**Architecture:** Single process. Main thread runs the Textual `TraceApp`; the existing `DaemonManager` runs its watcher/batcher on a background thread (unchanged). They communicate through the existing `code/daemon/ipc.py` `ui_queue`. A `TraceController` wraps the existing `Repository` (shared via `daemon.repo`) and `render_file_diff`, returning a uniform `{"ok": ...}` / `{"ok": False, "error": ...}` result so the UI never crashes on a backend error.

**Tech Stack:** Python 3.13, Textual, `unittest` (`IsolatedAsyncioTestCase` + Textual `run_test()` Pilot), `uv`.

**Scope note:** This is Phase 1 of the Electron→TUI migration (spec: `docs/superpowers/specs/2026-07-06-electron-to-tui-migration-design.md`). It ADDS the TUI and makes it the default entry; it does NOT yet delete Electron/menubar/packaging (that is the later teardown phase). Agents/Workspace/MCP view internals and controller methods for them are their own later phases.

---

## File Structure

- `pyproject.toml` — add `textual` runtime dependency.
- `code/tui/__init__.py` — new package marker.
- `code/tui/controller.py` — `TraceController` data facade (this phase: commits, diff, restore, reassign, revert).
- `code/tui/app.py` — `TraceApp` (Textual App): 4 empty tabs, daemon lifecycle, IPC drain, status line.
- `code/main.py` — add `_run_with_tui(...)`; make TUI the default run mode.
- `tests/test_tui_controller.py` — controller unit tests.
- `tests/test_tui_app.py` — app tests via Textual Pilot.

Run all tests with: `uv run python -m unittest discover -s tests`

---

## Task 1: Scaffold — add Textual and the `tui` package

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Create: `code/tui/__init__.py`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"textual>=0.60"` to the `dependencies` array (alongside the existing runtime deps such as `watchdog`).

- [ ] **Step 2: Sync the environment**

Run: `uv sync`
Expected: resolves and installs `textual` (and its deps `rich`, etc.) with no errors.

- [ ] **Step 3: Create the package marker**

Create `code/tui/__init__.py` with a single line:

```python
"""Trace terminal UI (Textual)."""
```

- [ ] **Step 4: Verify Textual imports under the project interpreter**

Run: `uv run python -c "import textual, textual.app; print(textual.__version__)"`
Expected: prints a version string, no ImportError.

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add pyproject.toml uv.lock code/tui/__init__.py
git commit -m "chore(tui): add textual dependency and tui package scaffold"
```

---

## Task 2: `TraceController` data facade

The controller is the ONLY place that translates UI intent into backend calls. It shares the daemon's `Repository` instance (no second SQLite connection) and wraps every call in a uniform result dict.

**Files:**
- Create: `code/tui/controller.py`
- Test: `tests/test_tui_controller.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_controller.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from core.repository import Repository
from tui.controller import TraceController


class _BoomRepo:
    """Every method raises, to exercise the error-wrapping contract."""

    def list_commits(self, limit=50):
        raise RuntimeError("boom")

    def restore_file(self, commit_id, file_path, backup_current=True):
        raise RuntimeError("boom")

    def reassign_commit(self, commit_id, new_agent):
        raise RuntimeError("boom")

    def preview_revert_agent(self, agent):
        raise RuntimeError("boom")

    def revert_agent(self, agent, backup_current=True):
        raise RuntimeError("boom")


class TraceControllerHappyPath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_commits_ok_on_fresh_repo(self):
        result = self.controller.list_commits()
        self.assertTrue(result["ok"])
        self.assertEqual(result["commits"], [])

    def test_get_diff_returns_line_list(self):
        result = self.controller.get_diff("hello.txt", None, None)
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["lines"], list)


class TraceControllerErrorContract(unittest.TestCase):
    def setUp(self):
        self.controller = TraceController(_BoomRepo(), Path("/tmp"))

    def test_list_commits_wraps_error(self):
        result = self.controller.list_commits()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")

    def test_restore_file_wraps_error(self):
        result = self.controller.restore_file(1, "x.txt")
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_tui_controller -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'tui.controller'`.

- [ ] **Step 3: Write the controller**

Create `code/tui/controller.py`:

```python
"""In-process data facade the TUI calls instead of touching the backend directly.

Every method returns {"ok": True, ...} or {"ok": False, "error": <str>} so the
UI can render failures without crashing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.electron_diff_bridge import render_file_diff


class TraceController:
    def __init__(self, repo, workspace: Path) -> None:
        self._repo = repo
        self._workspace = workspace

    def list_commits(self, limit: int = 50) -> dict[str, Any]:
        try:
            return {"ok": True, "commits": self._repo.list_commits(limit)}
        except Exception as exc:  # noqa: BLE001 - deliberate boundary
            return {"ok": False, "error": str(exc)}

    def get_diff(self, file_path: str, prev_hash: str | None, cur_hash: str | None) -> dict[str, Any]:
        try:
            lines = render_file_diff(self._workspace, file_path, prev_hash, cur_hash)
            return {"ok": True, "lines": lines}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def restore_file(self, commit_id: int, file_path: str) -> dict[str, Any]:
        try:
            backup_id = self._repo.restore_file(commit_id, file_path)
            return {"ok": True, "backup_id": backup_id}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def reassign_commit(self, commit_id: int, new_agent: str) -> dict[str, Any]:
        try:
            self._repo.reassign_commit(commit_id, new_agent)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def preview_revert_agent(self, agent: str) -> dict[str, Any]:
        try:
            return {"ok": True, "preview": self._repo.preview_revert_agent(agent)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def revert_agent(self, agent: str) -> dict[str, Any]:
        try:
            return {"ok": True, "commit_id": self._repo.revert_agent(agent)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_tui_controller -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/controller.py tests/test_tui_controller.py
git commit -m "feat(tui): add TraceController data facade with ok/error contract"
```

---

## Task 3: `TraceApp` shell with four empty tabs

**Files:**
- Create: `code/tui/app.py`
- Test: `tests/test_tui_app.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tui_app.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from tui.app import TraceApp


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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_tui_app -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'tui.app'`.

- [ ] **Step 3: Write the app shell**

Create `code/tui/app.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests.test_tui_app -v`
Expected: PASS (1 test).

> If `query("TabPane")` selector or `TabPane`/`TabbedContent` import path differs in the installed Textual version, adjust to that version's API (check `uv run python -c "import textual.widgets as w; print([n for n in dir(w) if 'Tab' in n])"`). Keep the four ids identical.

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/app.py tests/test_tui_app.py
git commit -m "feat(tui): add TraceApp shell with four empty tabs"
```

---

## Task 4: Daemon lifecycle + live IPC drain

**Files:**
- Modify: `code/tui/app.py`
- Test: `tests/test_tui_app.py`

- [ ] **Step 1: Write the failing tests (append to `tests/test_tui_app.py`)**

Add these methods to the `TraceAppShell` class, and add the import at the top of the file (`from daemon import ipc`):

```python
    async def test_starts_and_stops_daemon(self):
        daemon = _FakeDaemon()
        app = TraceApp(daemon=daemon)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertTrue(daemon.started)
        self.assertTrue(daemon.stopped)

    async def test_drains_new_commit_event_into_status(self):
        from daemon import ipc

        daemon = _FakeDaemon()
        app = TraceApp(daemon=daemon)
        async with app.run_test() as pilot:
            await pilot.pause()
            ipc.emit("new_commit", commit_id=7, agent="claude")
            await pilot.pause(0.6)  # let the drain interval fire
            status = app.query_one("#status-line", expect_type=None)
            self.assertIn("7", str(status.renderable))
```

Also add at the top of the file, after the existing imports:

```python
from daemon import ipc
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run python -m unittest tests.test_tui_app -v`
Expected: the two new tests FAIL (daemon never started; status never updates).

- [ ] **Step 3: Implement lifecycle + drain in `code/tui/app.py`**

Add these imports and methods to `TraceApp` (keep the existing `compose`):

```python
from daemon import ipc

    def on_mount(self) -> None:
        self._daemon.start(self._daemon.workspace)
        self.set_interval(0.5, self._drain_ipc)

    def _drain_ipc(self) -> None:
        for event in ipc.drain():
            if event.type == "new_commit":
                cid = event.payload.get("commit_id")
                agent = event.payload.get("agent", "?")
                self.query_one("#status-line", Static).update(
                    f"new commit #{cid} by {agent}"
                )
            elif event.type == "error":
                self.query_one("#status-line", Static).update(
                    f"[red]{event.payload.get('message', 'error')}[/red]"
                )

    def on_unmount(self) -> None:
        self._daemon.stop()
```

> Note: `_FakeDaemon.start(workspace)` in the test accepts the workspace arg to match the real `DaemonManager.start(workspace: Path)`. Fix the test's `test_drains...` assertion helper: replace `expect_type=None` with `Static` and import `Static` in the test (`from textual.widgets import Static`).

- [ ] **Step 4: Fix the test helper and run**

In `tests/test_tui_app.py` add `from textual.widgets import Static` at the top, and change the drain assertion to:

```python
            status = app.query_one("#status-line", Static)
            self.assertIn("7", str(status.renderable))
```

Run: `uv run python -m unittest tests.test_tui_app -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/app.py tests/test_tui_app.py
git commit -m "feat(tui): start/stop daemon and drain IPC events into the status line"
```

---

## Task 5: Make the TUI the default run mode

**Files:**
- Modify: `code/main.py`

- [ ] **Step 1: Add `_run_with_tui` next to `_run_with_menubar`**

In `code/main.py`, add:

```python
def _run_with_tui(daemon, log: logging.Logger) -> int:
    """Default mode: TraceApp (Textual TUI) owns the main thread."""
    from tui.app import TraceApp

    app = TraceApp(daemon=daemon)
    try:
        app.run()
    finally:
        daemon.stop()
        log.info("Trace已退出。")
    return 0
```

- [ ] **Step 2: Switch the default dispatch to the TUI**

Find where `main()` chooses between headless and menubar (the `--headless` branch calling `_run_headless` vs the default calling `_run_with_menubar`). Change the non-headless default to call `_run_with_tui(daemon, log)` instead of `_run_with_menubar(daemon, log)`. Leave `_run_with_menubar` in place for now (deleted in the teardown phase).

- [ ] **Step 3: Write a smoke test**

Create `tests/test_tui_entry.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))


class TuiEntry(unittest.TestCase):
    def test_run_with_tui_is_importable_and_builds_app(self):
        import main
        from tui.app import TraceApp

        class _D:
            workspace = Path("/tmp")
            def start(self, ws): pass
            def stop(self): pass

        self.assertTrue(hasattr(main, "_run_with_tui"))
        app = TraceApp(daemon=_D())
        self.assertIsInstance(app, TraceApp)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run it**

Run: `uv run python -m unittest tests.test_tui_entry -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/main.py tests/test_tui_entry.py
git commit -m "feat(tui): make the Textual TUI the default run mode"
```

---

## Task 6: Full-suite check + manual smoke

- [ ] **Step 1: Run the whole suite**

Run: `uv run python -m unittest discover -s tests`
Expected: all pass (existing backend tests + the 3 new TUI test modules). Electron tests still present and passing — untouched this phase.

- [ ] **Step 2: Manual smoke (human-run, optional in CI)**

Run: `uv run python code/main.py --workspace test_workspace`
Expected: a terminal UI appears with four tabs (Commits/Agents/Workspace/MCP) and a Header/Footer; editing a file in `test_workspace/` makes the status line show a "new commit" message within ~2-3s; pressing `q` exits and the daemon stops cleanly (no leftover process).

- [ ] **Step 3: Commit any smoke-driven fixes**

```bash
cd ~/trace
git commit -am "fix(tui): foundation smoke-test adjustments" || echo "nothing to fix"
```

---

## Self-Review notes

- **Spec coverage (this phase):** §4.1 process/thread model (Tasks 4-5), §4.2 `app.py`+`controller.py` boundaries (Tasks 2-3), §4.3 read + realtime data flow (Tasks 2,4), §5 error contract (Task 2). Views' internals, teardown (§7), packaging (§6), and CI (§8) are explicitly deferred to later phases.
- **Type consistency:** controller returns `{"ok": bool, ...}` everywhere; `TraceApp(daemon=...)` constructor and `daemon.start(workspace)/stop()/workspace/repo` surface are used identically in app, tests, and `main.py`.
- **Known API-verification points:** Textual `TabbedContent`/`TabPane` import paths and the `query("TabPane")` selector should be verified against the installed Textual version at Task 3 Step 4 (noted inline).
