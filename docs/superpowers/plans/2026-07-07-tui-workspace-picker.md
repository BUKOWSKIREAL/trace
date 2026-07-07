# TUI Workspace Picker (Phase 5) Implementation Plan

**Goal:** Replace the Tkinter workspace picker (`code/views/workspace_picker.py`) with a Textual-native directory picker embedded in `TraceApp`, completing the "pure-Python, `uvx trace`-installable TUI" mandate from the migration spec (§4.4). After Phase 5 the only workspace-selection path is: `--workspace X` → last memory → TUI `DirectoryTree` screen; no Tkinter, no macOS-only AppleScript detour.

**Architecture:** A new `WorkspacePickerScreen(ModalScreen[Path | None])` in `code/tui/views/workspace.py` (re-used file, new class — `WorkspaceView` stays). `main.py` no longer imports Tkinter nor calls `_pick_workspace`; instead, when no workspace is resolvable upfront, it launches `TraceApp` in "pick-only" mode — the app mounts the picker screen as the initial screen. On confirm, the app starts the daemon with the chosen path and switches to the main tabbed layout. On cancel, the app exits 0.

**Tech Stack:** Python 3.13, Textual 8.2.8 `DirectoryTree` + `ModalScreen`, `unittest` + Textual `Pilot`.

**Prerequisite:** Phase 4 complete on branch `feat/tui-foundation` (commit `91fb517`). This plan continues on that branch.

**Scope notes:**
- Phase 5 only removes the Tkinter picker from the **default TUI run path**. The `code/menubar/` AppleScript + Tk fallback (`_choose_workspace_for_menubar`) is left untouched — menubar teardown is Phase 6. Same for `code/views/workspace_picker.py` itself: kept importable so existing tests (`test_windows_startup.py::test_workspace_picker_module_imports_on_windows`) keep passing; it's just never called from `main.py` anymore.
- `--choose` is still honored: it forces `pick_only=True` even when last memory exists.
- The picker screen is reused by a future "switch workspace" action; only the initial-mount path is wired here.

---

## Reference: backend facts (verified against the code)

- `utils.state.load_last_workspace() -> Path | None` — returns `None` if no state file or if the recorded dir no longer exists.
- `utils.state.save_last_workspace(Path)` — already called by `main.py:190` for any resolved path, including picker choices.
- `code/main.py:73-82` `_pick_workspace(initial)` — currently branches on macOS menubar AppleScript vs Tk; **delete this function entirely**.
- `code/main.py:85-107` `resolve_workspace(args, log)` — four-step priority; returns `None` only when the picker was cancelled. **Refactor**: split into `resolve_startup_workspace(args, log) -> (Path | None, needs_picker: bool)` where `None` with `needs_picker=True` means "launch the TUI picker screen". This keeps the four-level priority but moves the "call the picker now" step out of `resolve_workspace` so the TUI owns all interactive UI.
- `code/main.py:201` — `_run_with_tui(daemon, log)` currently assumes daemon is already started; needs to accept a "pick-then-start" flow.
- Textual `DirectoryTree(path)`:
  - Root is the given path; root's `node.data` is a `DirEntry` (so `node.data.path` is the absolute `Path`).
  - Clicking a node toggles its expansion by default (because `auto_select=True` + `auto_expand=True`); `Tree.NodeSelected(node)` message has `.node`.
  - `tree.select_node(node)` programmatically moves the cursor without emitting a selection event.
- `TraceApp(daemon, controller=None)` is already the TUI entry; we extend it with an optional initial `workspace_to_pick` mode instead of adding a second App class.
- Existing `test_workspace_resolution.py::TestResolveWorkspace` mocks `main_mod._pick_workspace`. **Decision**: keep `_pick_workspace` as a thin stub that returns `None` (so `resolve_workspace` still resolves to None without invoking GUI), and have the new resolution flow inspect `args`/state directly. The 5 existing tests all pass `args.workspace` or mock `_pick_workspace`; both should still work.

---

## File Structure

- `code/tui/views/workspace.py` — add `WorkspacePickerScreen`.
- `code/tui/app.py` — `TraceApp.__init__` gains `pick_workspace: bool = False`; when True, mount `WorkspacePickerScreen` as the active screen instead of the tabs; add `serve_workspace(path)` to start daemon + swap to main layout.
- `code/main.py` — remove Tkinter import + `_pick_workspace`; split `resolve_workspace` into `resolve_startup_workspace` (returns `(Path | None, needs_picker: bool)`); pass `pick_workspace=needs_picker` to `TraceApp`.
- `tests/test_tui_workspace_picker.py` — new Pilot tests for `WorkspacePickerScreen`.
- `tests/test_tui_app.py` — extend with a pick-mode test.
- `tests/test_workspace_resolution.py` — extend to cover `needs_picker` semantics.

Run all tests with: `uv run python -m unittest discover -s tests`

---

## Task 1: `WorkspacePickerScreen`

**Files:** Modify `code/tui/views/workspace.py`, create `tests/test_tui_workspace_picker.py`.

### Behavior

- A `ModalScreen[Path | None]` (driving via `app.push_screen(screen, callback)` from `TraceApp`).
- Composes: a header `Static` with prompt text, a `DirectoryTree(initial_path)` where `initial_path = initial or Path.home()`, and an action bar with two buttons (`Open` / `Cancel`).
- Tracks `selected: Path | None = None`, set on `Tree.NodeSelected`. Validation: only directories are selectable (skip file nodes — `DirEntry.data.path.is_dir()`).
- Keybindings:
  - `enter` / `o` → `action_open()` — dismiss with the selected path.
  - `escape` / `c` → `action_cancel()` — dismiss with `None`.
- `Open` button click → `action_open()`; `Cancel` button click → `action_cancel()`.
- `action_open()` only works if `selected` is a directory; otherwise no-op (or a transient notify).

### Public surface

```python
class WorkspacePickerScreen(ModalScreen[Path | None]):
    def __init__(self, initial: Path | None = None) -> None: ...
    selected: Path | None  # read by tests
    BINDINGS = [("enter", "open", "Open"), ("o", "open", "Open"),
                ("escape", "cancel", "Cancel"), ("c", "cancel", "Cancel")]
    def action_open(self) -> None: ...
    def action_cancel(self) -> None: ...
```

### Test cases (`tests/test_tui_workspace_picker.py`)

- `test_open_dismisses_with_selected_directory`: harness with 2 temp dirs inside a parent; `tree.select_node(first_child)`; call `screen.action_open()`; assert the app's modal result is the first child's path. Use `app.push_screen(WorkspacePickerScreen(parent), lambda p: result_holder.append(p))` then `pilot.pause()` to drain.
- `test_cancel_dismisses_with_none`: push the screen, `action_cancel()`, assert callback got `None`.
- `test_selecting_file_does_not_open`: `tree.select_node(file_node)` then `action_open()`; assert screen still mounted (no `dismiss` happened) — verifies the directory-only guard.
- `test_initial_defaults_to_home`: instantiate with `initial=None`; assert the tree root's path equals `Path.home()`. 

---

## Task 2: `TraceApp` pick-then-start flow

**Files:** Modify `code/tui/app.py`, extend `tests/test_tui_app.py`.

### Changes

- `TraceApp.__init__(self, daemon, controller=None, *, pick_workspace: bool = False)`.
- When `pick_workspace=True`:
  - On mount, push `WorkspacePickerScreen(initial=None)` with `self._on_workspace_picked` as the callback.
  - The 4 tabs **are still composed** (matches existing tests that assert `query(TabPane)` exists), but the picker screen sits on top until resolved.
- `_on_workspace_picked(path: Path | None)`:
  - `None` → call `self.exit(0)` (user cancelled).
  - `path` → set `self._daemon.workspace = path` (the daemon already supports late start — verify), call `self._daemon.start(path)`, then `save_last_workspace(path)` and pop the screen back to the main tabbed layout.
- New `serve_workspace(path)` helper method so the menubar path / tests can drive the same flow without re-implementing it.
- `_FakeDaemon` in tests already has `start(workspace)` and `workspace` attribute — perfect.

### Test cases (extend `tests/test_tui_app.py`)

- `test_pick_workspace_mode_mounts_picker_screen`: instantiate `TraceApp(daemon, pick_workspace=True)`; `app.run_test()`; assert `isinstance(app.screen, WorkspacePickerScreen)`.
- `test_pick_mode_serve_workspace_starts_daemon_and_pops_picker`: with a fake daemon, call `app.serve_workspace(ws)` directly; assert `daemon.started is True`, `daemon.workspace == ws`, screen popped.
- `test_pick_mode_cancel_exits_app`: push the picker; call `screen.action_cancel()`; let the worker drain; assert `app._exit` is set (or `app.return_value == 0`).

---

## Task 3: `main.py` resolution refactor

**Files:** Modify `code/main.py`, extend `tests/test_workspace_resolution.py`.

### Changes

- Remove `from views.workspace_picker import pick_workspace` import.
- Remove the `_pick_workspace` function (the `_run_with_menubar` path keeps its own AppleScript fallback via `menubar.app._choose_workspace_for_menubar` — leave that file's imports intact since menubar is Phase 6).
- Rewrite `resolve_workspace`:

  ```python
  def resolve_startup_workspace(args, log) -> tuple[Path | None, bool]:
      """Return (workspace, needs_picker).
      workspace is None when:
        (a) the user passed --workspace to a nonexistent path (already logged), or
        (b) no workspace is resolvable from args/memory and the TUI picker should run.
      needs_picker disambiguates (a) from (b) so main() can decide between exit-1 and pick-mode.
      """
      if args.workspace is not None:
          ws = args.workspace.expanduser().resolve()
          if not ws.is_dir():
              log.error("--workspace 指定的目录不存在: %s", ws)
              return None, False  # hard error, don't pick
          return ws, False

      last = load_last_workspace()
      if args.choose:
          log.info("--choose 指定，进入 TUI 选择屏（initialdir=%s）", last or "$HOME")
          return None, True  # always pick, even if memory exists

      if last is not None:
          log.info("使用上次工作区: %s （--choose 可重选）", last)
          return last, False

      log.info("无 --workspace 也无记忆，进入 TUI 选择屏...")
      return None, True
  ```

- `main()`:

  ```python
  def main() -> int:
      args = parse_args()
      setup_logging(args.verbose)
      log = logging.getLogger("trace.main")

      workspace, needs_picker = resolve_startup_workspace(args, log)
      if workspace is None and not needs_picker:
          return 1  # bad --workspace
      if workspace is not None:
          save_last_workspace(workspace)
          log.info("Trace启动，工作目录: %s", workspace)

      from daemon.manager import DaemonManager
      daemon = DaemonManager()
      if workspace is not None:
          daemon.start(workspace)
          log.info("守护进程运行中。")

      if args.headless:
          if workspace is None:
              log.error("headless 模式必须有 --workspace 或上次工作区；TUI 选择屏不可用。")
              return 1
          return _run_headless(daemon, log)
      return _run_with_tui(daemon, log, pick_workspace=needs_picker, controller_workspace=workspace)
  ```

- `_run_with_tui(daemon, log, *, pick_workspace: bool = False, controller_workspace: Path | None = None)`:
  - If `pick_workspace=True`, the controller is constructed lazily after the picker (since `repo` isn't ready yet). Pass `controller=None` to `TraceApp`; the picker flow will set the controller on serve.
  - Else, build the controller from `daemon.repo`/`daemon.workspace` as before.

### Backward compatibility

The existing `test_workspace_resolution.py::TestResolveWorkspace` calls `self.main_mod.resolve_workspace` directly. **Decision**: keep `resolve_workspace(args, log) -> Path | None` as a thin shim that calls `resolve_startup_workspace` and returns `None` whenever `needs_picker=True` (so the 5 existing tests keep passing unchanged — they all assert `None` on cancel/no-memory which still holds).

But wait — the existing test `test_choose_flag_invokes_picker` patches `_pick_workspace`. Since we're deleting `_pick_workspace`, that patch would fail. **Fix**: rewrite the 5 tests to use the new `resolve_startup_workspace` signature. This is in-scope per the migration spec §7.

### Test cases (rewrite `tests/test_workspace_resolution.py::TestResolveWorkspace`)

- `test_explicit_workspace_wins`: `resolve_startup_workspace(args(workspace=td)) == (td_resolved, False)`.
- `test_explicit_nonexistent_returns_no_pick`: `(None, False)` — main() exits 1.
- `test_last_memory_used_silently`: `(td_resolved, False)`.
- `test_choose_flag_returns_pick_needed_even_with_memory`: state set, `--choose` → `(None, True)`.
- `test_no_memory_no_args_returns_pick_needed`: `(None, True)`.

---

## Task 4: Full-suite check + smoke

- [ ] Run `uv run python -m unittest discover -s tests`. Expected: zero failures (Phase 4 baseline 410; this phase adds roughly 4 + 3 + 5 - 5 replaced ≈ +7 → ~417; exact count irrelevant, only zero-failures matters).
- [ ] Manual smoke (human-run, optional): `uv run python code/main.py` (no `--workspace`, no memory) → picker screen opens at `$HOME`; navigate to `test_workspace`, press `o` → daemon starts, tabs appear. Run again with no `--workspace` → memory picks up `test_workspace` silently. Run `--choose` → picker opens again (memory now used as `initial` default if `WorkspacePickerScreen` is wired for it — otherwise `$HOME`). Press `escape` → app exits 0.
- [ ] Commit any smoke-driven fixes.

---

## Self-Review notes

- **Spec coverage (this phase):** design spec §4.4 workspace selection (Tasks 1-3), §5 error contract (an invalid `--workspace` is a hard exit-1, not a picker trigger — Task 3), §6 logistical hint that Tkinter removal is in this phase (Task 3's import removal).
- **Type consistency:** `resolve_startup_workspace -> tuple[Path | None, bool]`; `TraceApp(daemon, controller=None, *, pick_workspace=False)`; `WorkspacePickerScreen` is a `ModalScreen[Path | None]`.
- **Markup-injection guard:** all path-derived text in the picker is wrapped in `rich.text.Text(...)` (carrying forward Phase 2/4 lesson — paths with brackets/special chars render literally).
- **Cross-platform:** the old macOS AppleScript detour was only needed because Tk couldn't run from a rumps main loop; Textual has no such restriction, so the picker is identical on all platforms. The menubar path (`code/menubar/app.py`) keeps its AppleScript fallback for Phase 6 — we don't delete `_choose_workspace_for_menubar`.
- **Deferred:** the `views/workspace_picker.py` file itself is kept (used by `test_windows_startup.py::test_workspace_picker_module_imports_on_windows`). Its deletion is Phase 6.
- **Daemon late-start:** `DaemonManager.start(workspace)` already accepts a workspace arg; we just delay calling it until after the picker. The controller is built inside `serve_workspace` once `daemon.repo` is available.
