# TUI Agents & Workspace Views (Phase 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill in two of the three remaining tabs — the **Agents** view (per-agent stats + selective per-agent revert with a preview confirmation) and the **Workspace** view (workspace/db/commit/snapshot summary) — porting the two backing SQL queries into Python and reusing the Phase-1 `revert_agent`/`preview_revert_agent` controller methods.

**Architecture:** Same layering as Phases 1-2. Two new pure SQL methods on `Repository` (`list_agents`, `workspace_summary`), thin `{ok}`-wrapped `TraceController` accessors, and two `Widget` views that only render controller output. The Agents view's revert action reuses the existing two-step `preview_revert_agent` → confirm → `revert_agent` flow through a `RevertConfirmModal` that shows how many files will change before touching anything.

**Tech Stack:** Python 3.13, Textual 8.2.8 (`DataTable`, `ListView`, `ModalScreen`, `Button`, `Static`), `unittest` + Textual `Pilot`.

**Prerequisite:** Phase 2 complete on branch `feat/tui-foundation` (commit `ddd009d`). This plan continues on that same branch.

**Scope note:** Phase 3 of the migration (spec: `docs/superpowers/specs/2026-07-06-electron-to-tui-migration-design.md`). It builds ONLY the Agents and Workspace views. The **MCP view is deferred to Phase 4** — its install logic (~590 lines writing `~/.codex/config.toml`, `~/.codex/hooks.json`, `.mcp.json`, etc.) currently lives only in Electron's `main.js` and needs a separate Python port. Electron/packaging teardown is a later phase; do not delete anything Electron here.

---

## Reference: real backend facts (verified against the code)

- `agents` table columns: `name, category, match_rules, display_name, color`.
- Agent-stats query (ported verbatim from `electron_app/main.js` `list-agents`): agents LEFT JOIN a per-`author_agent` commit aggregate, ordered by `commit_count DESC, name ASC`.
- Workspace summary (ported from `main.js` `get-workspace-summary`): `COUNT(*)` of `commits`, `snapshots`, `agents`, plus `workspace` and `db_path`.
- `Repository.preview_revert_agent(agent) -> {"changed_paths": list[str], "target_manifest": dict, "head_commit_id": int|None}`. Empty repo → `{"changed_paths": [], "target_manifest": {}}` (no `head_commit_id` key).
- `Repository.revert_agent(agent, *, backup_current=True) -> int` (returns the new backup/revert commit id). Already wrapped by `TraceController.revert_agent` (Phase 1) and `TraceController.preview_revert_agent` (Phase 1), both returning `{ok}`.
- Test helper: every new test file defines its own local `make_change(path, kind="upsert", agent="human")` (see Phase 2's plan §"how to create commits in tests" for the exact shape) and creates commits via `repo.commit("human", [make_change(p)])`.

---

## File Structure

- `code/core/repository.py` — add `list_agents`, `workspace_summary`.
- `code/tui/controller.py` — add `list_agents`, `get_workspace_summary`.
- `code/tui/views/workspace.py` — `WorkspaceView`.
- `code/tui/views/agents.py` — `AgentsView` + `RevertConfirmModal`.
- `code/tui/app.py` — mount both views; refresh them on `new_commit`.
- `tests/test_repository_agents_workspace.py` — repository tests.
- `tests/test_tui_controller.py` — extend with agents/workspace accessor tests.
- `tests/test_tui_workspace_view.py` — Pilot tests.
- `tests/test_tui_agents_view.py` — Pilot tests.

Run all tests with: `uv run python -m unittest discover -s tests`

---

## Task 1: `Repository.list_agents` and `Repository.workspace_summary`

**Files:**
- Modify: `code/core/repository.py`
- Test: `tests/test_repository_agents_workspace.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_repository_agents_workspace.py`:

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


class RepositoryAgentsWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_agents_includes_presets_with_zero_counts(self):
        agents = self.repo.list_agents()
        by_name = {a["name"]: a for a in agents}
        self.assertIn("claude", by_name)
        self.assertIn("codex", by_name)
        self.assertEqual(by_name["claude"]["commit_count"], 0)
        self.assertEqual(by_name["claude"]["display_name"], "Claude Code")

    def test_list_agents_counts_commits_and_orders_by_count_desc(self):
        a = self.ws / "a.txt"
        a.write_text("1", encoding="utf-8")
        self.repo.commit("claude", [make_change(a, agent="claude")])
        a.write_text("2", encoding="utf-8")
        self.repo.commit("claude", [make_change(a, agent="claude")])

        agents = self.repo.list_agents()
        self.assertEqual(agents[0]["name"], "claude")
        self.assertEqual(agents[0]["commit_count"], 2)
        self.assertIsNotNone(agents[0]["last_time"])

    def test_workspace_summary_reports_counts_and_paths(self):
        a = self.ws / "a.txt"
        a.write_text("1", encoding="utf-8")
        self.repo.commit("human", [make_change(a)])

        summary = self.repo.workspace_summary()
        self.assertEqual(summary["workspace"], str(self.ws))
        self.assertTrue(summary["db_path"].endswith("trace.db"))
        self.assertEqual(summary["commit_count"], 1)
        self.assertGreaterEqual(summary["snapshot_count"], 1)
        self.assertGreaterEqual(summary["agent_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_repository_agents_workspace -v`
Expected: FAIL/ERROR — `AttributeError: 'Repository' object has no attribute 'list_agents'`.

- [ ] **Step 3: Implement the two methods**

In `code/core/repository.py`, add these to the `Repository` class (after `get_prev_commit_id` from Phase 2):

```python
    def list_agents(self) -> list[dict]:
        """每个 agent 的注册信息 + commit 统计（按 commit 数降序）。"""
        conn = get_connection(self.db_path)
        rows = conn.execute(
            """
            SELECT a.name, a.category, a.display_name, a.color,
                   COALESCE(stats.commit_count, 0) AS commit_count,
                   stats.last_time
            FROM agents a
            LEFT JOIN (
                SELECT author_agent, COUNT(*) AS commit_count, MAX(time) AS last_time
                FROM commits GROUP BY author_agent
            ) stats ON stats.author_agent = a.name
            ORDER BY commit_count DESC, a.name ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def workspace_summary(self) -> dict:
        """当前工作区概览：路径、db、commit/snapshot/agent 计数。"""
        conn = get_connection(self.db_path)
        commit_count = conn.execute("SELECT COUNT(*) AS n FROM commits").fetchone()["n"]
        snapshot_count = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        agent_count = conn.execute("SELECT COUNT(*) AS n FROM agents").fetchone()["n"]
        return {
            "workspace": str(self.workspace),
            "db_path": str(self.db_path),
            "commit_count": commit_count,
            "snapshot_count": snapshot_count,
            "agent_count": agent_count,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_repository_agents_workspace -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/core/repository.py tests/test_repository_agents_workspace.py
git commit -m "feat(repo): add list_agents and workspace_summary queries"
```

---

## Task 2: `TraceController.list_agents` and `get_workspace_summary`

**Files:**
- Modify: `code/tui/controller.py`
- Test: `tests/test_tui_controller.py`

- [ ] **Step 1: Write the failing tests (append a class to `tests/test_tui_controller.py`)**

```python
class TraceControllerAgentsWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_agents_ok(self):
        result = self.controller.list_agents()
        self.assertTrue(result["ok"])
        self.assertTrue(any(a["name"] == "claude" for a in result["agents"]))

    def test_get_workspace_summary_ok(self):
        result = self.controller.get_workspace_summary()
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["workspace"], str(self.ws))

    def test_list_agents_wraps_error(self):
        controller = TraceController(_BoomRepo(), Path("/tmp"))
        result = controller.list_agents()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")
```

Add `list_agents` and `workspace_summary` (raising) to the existing `_BoomRepo` class in that file:

```python
    def list_agents(self):
        raise RuntimeError("boom")

    def workspace_summary(self):
        raise RuntimeError("boom")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_tui_controller -v`
Expected: FAIL/ERROR — `AttributeError: 'TraceController' object has no attribute 'list_agents'`.

- [ ] **Step 3: Implement the two accessors**

Add to `TraceController` in `code/tui/controller.py`:

```python
    def list_agents(self) -> dict[str, Any]:
        try:
            return {"ok": True, "agents": self._repo.list_agents()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def get_workspace_summary(self) -> dict[str, Any]:
        try:
            return {"ok": True, "summary": self._repo.workspace_summary()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_tui_controller -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/controller.py tests/test_tui_controller.py
git commit -m "feat(tui): add controller accessors for agents and workspace summary"
```

---

## Task 3: `WorkspaceView`

**Files:**
- Create: `code/tui/views/workspace.py`
- Test: `tests/test_tui_workspace_view.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_workspace_view.py`:

```python
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from core.repository import Repository
from models.agent import AgentAttribution
from models.change import Change
from tui.controller import TraceController
from tui.views.workspace import WorkspaceView


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(path, time.time(), AgentAttribution(agent=agent, confidence=0.95), kind)


class _Harness(App):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        yield WorkspaceView(self._controller)


class WorkspaceViewBehavior(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_shows_workspace_path_and_counts(self):
        a = self.ws / "a.txt"
        a.write_text("1", encoding="utf-8")
        self.repo.commit("human", [make_change(a)])

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(WorkspaceView)
            await view.refresh_summary()
            await pilot.pause()
            table = app.query_one(DataTable)
            rendered = str(list(table.rows))  # row keys exist
            self.assertGreaterEqual(table.row_count, 5)
            # the workspace path value must appear somewhere in the table cells
            all_cells = [
                str(table.get_cell_at((r, c)))
                for r in range(table.row_count)
                for c in range(len(table.columns))
            ]
            self.assertTrue(any(str(self.ws) in cell for cell in all_cells))
            self.assertTrue(any(cell == "1" for cell in all_cells))  # commit_count


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_tui_workspace_view -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'tui.views.workspace'`.

- [ ] **Step 3: Implement `WorkspaceView`**

Create `code/tui/views/workspace.py`:

```python
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
```

> Note: `DataTable.clear()` in this Textual version keeps columns by default (it clears rows). Verify with `uv run python -c "import inspect, textual.widgets as w; print(inspect.signature(w.DataTable.clear))"` — if it has a `columns=` param defaulting to False, the code above is correct. `add_columns`/`add_row`/`get_cell_at`/`row_count`/`columns` are the stable DataTable API; adapt only if the installed version differs, keeping the test intent (workspace path + counts appear as cells).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_tui_workspace_view -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/views/workspace.py tests/test_tui_workspace_view.py
git commit -m "feat(tui): add WorkspaceView summary table"
```

---

## Task 4: `AgentsView` — stats + agent list

**Files:**
- Create: `code/tui/views/agents.py`
- Test: `tests/test_tui_agents_view.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_agents_view.py`:

```python
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.app import App, ComposeResult

from core.repository import Repository
from models.agent import AgentAttribution
from models.change import Change
from tui.controller import TraceController
from tui.views.agents import AgentsView


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(path, time.time(), AgentAttribution(agent=agent, confidence=0.95), kind)


class _Harness(App):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        yield AgentsView(self._controller)


class AgentsViewBehavior(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_lists_agents_and_reports_active_count(self):
        a = self.ws / "a.txt"
        a.write_text("1", encoding="utf-8")
        self.repo.commit("claude", [make_change(a, agent="claude")])

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(AgentsView)
            await view.refresh_agents()
            await pilot.pause()
            # one active agent (claude, 1 commit), several registered
            self.assertEqual(view.active_count, 1)
            self.assertGreaterEqual(len(view.agent_list.children), 5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_tui_agents_view -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'tui.views.agents'`.

- [ ] **Step 3: Implement `AgentsView`**

Create `code/tui/views/agents.py`:

```python
"""AgentsView — per-agent stats and a list of registered agents."""
from __future__ import annotations

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static


class AgentsView(Widget):
    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self._agents: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="agents-stats")
            yield ListView(id="agent-list")

    @property
    def agent_list(self) -> ListView:
        return self.query_one("#agent-list", ListView)

    @property
    def active_count(self) -> int:
        return sum(1 for a in self._agents if a.get("commit_count", 0) > 0)

    async def on_mount(self) -> None:
        await self.refresh_agents()

    async def refresh_agents(self) -> None:
        result = self._controller.list_agents()
        self._agents = result.get("agents", []) if result.get("ok") else []

        total_commits = sum(a.get("commit_count", 0) for a in self._agents)
        self.query_one("#agents-stats", Static).update(
            Text(
                f"commits: {total_commits}   active: {self.active_count}   "
                f"registered: {len(self._agents)}"
            )
        )

        list_view = self.agent_list
        await list_view.clear()
        for agent in self._agents:
            name = agent.get("name", "unknown")
            display = agent.get("display_name", name)
            count = agent.get("commit_count", 0)
            last = agent.get("last_time") or "never"
            label = f"{display} ({name})  ·  {count} commits  ·  last {last}"
            await list_view.append(ListItem(Label(Text(label)), id=f"agentrow-{name}"))
```

> Note: keep all data-derived text wrapped in `rich.text.Text(...)` — same markup-injection lesson from Phase 2 (agent display names / summaries could contain brackets). Verify `ListView.append`/`clear` need `await` in this Textual version (they return awaitables even though they aren't coroutine functions — Phase 2 confirmed you MUST await them).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_tui_agents_view -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/views/agents.py tests/test_tui_agents_view.py
git commit -m "feat(tui): add AgentsView with stats and agent list"
```

---

## Task 5: Per-agent revert with preview confirmation

**Files:**
- Modify: `code/tui/views/agents.py`
- Test: `tests/test_tui_agents_view.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_tui_agents_view.py`)**

```python
    async def test_revert_key_previews_file_count_then_reverts_on_confirm(self):
        a = self.ws / "a.txt"
        a.write_text("human-1\n", encoding="utf-8")
        self.repo.commit("human", [make_change(a)])
        a.write_text("claude changed this\n", encoding="utf-8")
        self.repo.commit("claude", [make_change(a, agent="claude")])

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(AgentsView)
            await view.refresh_agents()
            await pilot.pause()

            await view.action_revert_agent("claude")
            await pilot.pause()
            from tui.views.agents import RevertConfirmModal
            modal = app.screen
            self.assertIsInstance(modal, RevertConfirmModal)
            self.assertEqual(modal.changed_count, 1)  # only a.txt affected

            await modal.confirm()
            await pilot.pause()

            # claude's change is reverted: a.txt goes back to the human version
            self.assertEqual((self.ws / "a.txt").read_text(encoding="utf-8"), "human-1\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_tui_agents_view.AgentsViewBehavior.test_revert_key_previews_file_count_then_reverts_on_confirm -v`
Expected: FAIL/ERROR — `AttributeError: 'AgentsView' object has no attribute 'action_revert_agent'`.

- [ ] **Step 3: Implement `RevertConfirmModal` and the revert action**

Add to `code/tui/views/agents.py` — new imports:

```python
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button
```

Add the modal class (before `AgentsView`):

```python
class RevertConfirmModal(ModalScreen[bool]):
    """Shows how many files an agent-revert will change before applying it."""

    def __init__(self, agent: str, changed_count: int, controller) -> None:
        super().__init__()
        self._agent = agent
        self.changed_count = changed_count
        self._controller = controller

    def compose(self) -> ComposeResult:
        with Vertical(id="revert-modal"):
            yield Label(
                Text(f"Revert all changes by '{self._agent}'? "
                     f"{self.changed_count} file(s) will change.")
            )
            with Horizontal():
                yield Button("Revert", id="confirm", variant="error")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.run_worker(self.confirm())
        else:
            self.dismiss(False)

    async def confirm(self) -> None:
        result = self._controller.revert_agent(self._agent)
        self.dismiss(bool(result.get("ok")))
```

Add a keybinding and action to `AgentsView` (add `BINDINGS` as a class attribute, and the two methods). The `r` key reverts whichever agent row is highlighted; `action_revert_agent(agent)` is also directly callable (used by the test):

```python
    BINDINGS = [("r", "revert_highlighted_agent", "Revert agent")]

    async def action_revert_highlighted_agent(self) -> None:
        item = self.agent_list.highlighted_child
        if item is None or item.id is None:
            return
        agent = item.id.removeprefix("agentrow-")
        await self.action_revert_agent(agent)

    async def action_revert_agent(self, agent: str) -> None:
        preview = self._controller.preview_revert_agent(agent)
        if not preview.get("ok"):
            return
        changed_count = len(preview["preview"].get("changed_paths", []))
        modal = RevertConfirmModal(agent, changed_count, self._controller)
        await self.app.push_screen(modal)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests.test_tui_agents_view -v`
Expected: PASS (both tests).

> If `ListView.highlighted_child` is named differently in the installed Textual version, check `uv run python -c "import textual.widgets as w; print([a for a in dir(w.ListView) if 'high' in a.lower()])"` and use the right attribute — the test calls `action_revert_agent("claude")` directly so it does not depend on `highlighted_child`, but the `r` keybinding path does.

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/views/agents.py tests/test_tui_agents_view.py
git commit -m "feat(tui): add per-agent revert with preview confirmation modal"
```

---

## Task 6: Wire both views into `TraceApp` and refresh on new commits

**Files:**
- Modify: `code/tui/app.py`
- Test: `tests/test_tui_app.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_tui_app.py`)**

```python
    async def test_agents_and_workspace_tabs_are_populated(self):
        import tempfile
        from pathlib import Path as _Path
        from core.repository import Repository
        from tui.views.agents import AgentsView
        from tui.views.workspace import WorkspaceView

        with tempfile.TemporaryDirectory() as tmp:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_tui_app -v`
Expected: FAIL — the Agents/Workspace tabs still hold bare `Static` placeholders, so `query_one(AgentsView)` raises `NoMatches`.

- [ ] **Step 3: Mount the two views in `code/tui/app.py`**

Add imports:

```python
from tui.views.agents import AgentsView
from tui.views.workspace import WorkspaceView
```

Replace the Agents and Workspace `TabPane` bodies in `compose` (leave the MCP tab's placeholder `Static` — that's Phase 4):

```python
            with TabPane("Agents", id="tab-agents"):
                yield AgentsView(self._controller)
            with TabPane("Workspace", id="tab-workspace"):
                yield WorkspaceView(self._controller)
```

Extend `_drain_ipc` so a `new_commit` also refreshes these two views (they hold live counts). Update the `new_commit` branch to also run:

```python
                self.run_worker(self.query_one(AgentsView).refresh_agents())
                self.run_worker(self.query_one(WorkspaceView).refresh_summary())
```

(placed right after the existing `self.run_worker(self.query_one(CommitsView).refresh_commits())` line).

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run python -m unittest tests.test_tui_app -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
cd ~/trace
git add code/tui/app.py tests/test_tui_app.py
git commit -m "feat(tui): mount Agents and Workspace views and refresh them on new_commit"
```

---

## Task 7: Full-suite check + manual smoke

- [ ] **Step 1: Run the whole suite**

Run: `uv run python -m unittest discover -s tests`
Expected: all pass (baseline was 378 after Phase 2; this phase adds roughly 3 + 3 + 1 + 2 + 1 = 10 tests → ~388; exact count doesn't matter, zero failures does).

- [ ] **Step 2: Manual smoke (human-run, optional in CI)**

Run: `uv run python code/main.py --workspace test_workspace`
Expected: the Agents tab shows a stats line (commits / active / registered) and a list of agents with per-agent commit counts; highlighting an agent and pressing `r` opens the revert-confirmation modal reporting how many files will change, and confirming reverts that agent's contributions. The Workspace tab shows a table with the workspace path, database path, and commit/snapshot/agent counts. Editing files updates the counts live. Press `q` to exit; daemon stops cleanly.

- [ ] **Step 3: Commit any smoke-driven fixes**

```bash
cd ~/trace
git commit -am "fix(tui): agents/workspace smoke-test adjustments" || echo "nothing to fix"
```

---

## Self-Review notes

- **Spec coverage (this phase):** design spec §4.2 `agents.py`/`workspace.py` views (Tasks 3-5), §4.3 read + realtime refresh (Tasks 1-2, 6), full-functionality-parity for per-agent revert with preview confirm (Task 5), §5 error contract (Task 2). MCP view explicitly deferred to Phase 4 (Scope note) because its install logic needs a Python port.
- **Type consistency:** `list_agents` → `{"ok", "agents": [...]}`; `get_workspace_summary` → `{"ok", "summary": {...}}`; `preview_revert_agent` (Phase 1) → `{"ok", "preview": {"changed_paths": [...]}}` consumed by `action_revert_agent`. `TraceApp(daemon, controller=None)` unchanged from Phase 2.
- **Known API-verification points (flagged inline):** `DataTable.clear(columns=...)` default (Task 3), `ListView.highlighted_child` name (Task 5), `ListView.append`/`clear` awaiting (Tasks 4-5, already settled in Phase 2). The implementer adapts mechanically to the installed Textual version, keeping test intent unchanged.
- **Markup-injection guard:** all data-derived text in the new views is wrapped in `rich.text.Text(...)`, carrying forward the Phase 2 fix so agent names / summaries with brackets render literally.
