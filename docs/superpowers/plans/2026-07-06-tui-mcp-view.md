# TUI MCP View (Phase 4) Implementation Plan

**Goal:** Fill the last empty tab — the **MCP** view — by porting `electron_app/main.js` MCP setup logic (~590 lines: `mcpSetupRows`, the `inspect_*`/`install_*` functions for Codex / Claude / OpenCode, the TOML/JSON/JSONC editors, shell-quoting helpers, and `runMcpInstallCommand`) into a new pure-Python module, then exposing it through `TraceController` and a Textual view. After Phase 4 the TUI is feature-complete for parity with Electron's MCP panel; teardown of Electron itself stays in Phase 6.

**Architecture:** Same layering as Phases 1-3. A new `code/mcp/setup.py` module owns all MCP config detection/installation (no `electron` import paths, no bundled-python detection — TUI is a `pipx`/`uvx` pure-Python product so `sys.executable` + `PYTHONPATH=<root>/code` is the only launch spec). `TraceController.list_mcp_setup` / `install_mcp_server` are thin `{ok}`-wrapped accessors. `MCPView` renders one `ListItem` per agent (status + command) and installs the highlighted agent via `i` (with a result modal) or copies its command via `c`.

**Tech Stack:** Python 3.13, stdlib `tomllib`/`json`/`shlex`/`subprocess`, Textual 8.2.8, `unittest` + Textual `Pilot`.

**Prerequisite:** Phase 3 complete on branch `feat/tui-foundation` (commit `bc0184c`). This plan continues on that branch.

**Scope notes:**
- Cursor support stays in `scripts/setup_cursor_mcp.py`; it is not in Electron's `mcpSetupRows` and is not added here.
- The bundled-py / portable-exe / Homebrew-binary probing in `electron_app/main.js` (`resolvePythonBridgeCommand`, `findCodexBinary`, `bundledTraceLayout`, `windowsPortableLayout`) is **not ported**. TUI launch spec is always `sys.executable -m mcp.trace_server --workspace <ws>` with `PYTHONPATH=<project_root>/code`. Claude install shells out to `claude` (resolved via `shutil.which`, fallback `"claude"`) — same shape as JS, minus the macOS brew path probing.
- No `rendererSmokeTest` toggle: TUI installs write files directly; tests inject `home` and stub subprocesses.

---

## Reference: backend facts (verified against the code)

- Constants ported from `electron_app/main.js:14-26`:
  - `TRACE_MCP_MODULE = "mcp.trace_server"`
  - `TRACE_CODEX_HOOK_MODULE = "hooks.trace_codex_hook"`
  - `TRACE_MCP_TOOL = "trace_record_files"`
  - `TRACE_MCP_SERVER_NAME = "trace"`
- Config paths (JS `codexConfigPath`/`codexHooksPath`/`opencodeConfigPath`):
  - `~/.codex/config.toml`, `~/.codex/hooks.json`, `~/.config/opencode/opencode.jsonc`
- Claude inspection scans **both** `~/.claude.json` and `<workspace>/.mcp.json`; if `~/.claude.json` already contains the trace server, that path wins as `config_path`.
- Codex "installed" = TOML `mcp_servers.trace` contains the trace module **and** the workspace **and** the hooks JSON contains a trace hook with the workspace.
- TOML value format = `JSON.stringify(String(value))` (i.e., JSON-quoted string). TOML array = `[<quoted>, ...]`.
- JSONC parse = strip `//` line comments + `/* */` block comments + trailing commas before `,` `}` or `]`, then `json.loads`.

---

## File Structure

- `code/mcp/setup.py` — new module: `McpSetup` class (workspace + home) with `list_rows()`, `install(server_id)`, plus all `_*` private inspectors/installers/command-builders.
- `code/tui/controller.py` — add `list_mcp_setup`, `install_mcp_server`.
- `code/tui/views/mcp.py` — `MCPView` + `InstallResultModal`.
- `code/tui/app.py` — replace MCP tab's `Static` placeholder with `MCPView`.
- `tests/test_mcp_setup.py` — direct unit tests for `McpSetup`.
- `tests/test_tui_controller.py` — extend with `TraceControllerMcp`.
- `tests/test_tui_mcp_view.py` — Pilot tests for `MCPView`.
- `tests/test_tui_app.py` — append MCP-tab-mounted test.

Run all tests with: `uv run python -m unittest discover -s tests`

---

## Task 1: `code/mcp/setup.py` Python port

**Files:** Create `code/mcp/setup.py`, `tests/test_mcp_setup.py`.

Port the following JS functions (electron_app/main.js, in order):

| JS function | Python method on `McpSetup` |
|---|---|
| `traceMcpLaunchSpec` | `_launch_spec()` — return `{command, args, cwd, env}` |
| `traceCodexHookLaunchSpec(phase)` | `_hook_launch_spec(phase)` |
| `inspectCodexTraceMcp` | `_inspect_codex_mcp()` |
| `installCodexTraceMcpConfig` | `_install_codex_mcp_config()` |
| `inspectCodexTraceHook` | `_inspect_codex_hook()` |
| `installCodexTraceHookConfig` | `_install_codex_hook_config()` |
| `inspectClaudeTraceMcp` | `_inspect_claude_mcp()` |
| `inspectOpencodeTraceMcp` | `_inspect_opencode_mcp()` |
| `installOpencodeTraceMcpConfig` | `_install_opencode_config()` |
| `codexMcpAddCommand` | `_codex_add_command()` |
| `claudeMcpAddCommand` | `_claude_add_command()` |
| `opencodeMcpAddCommand` | `_opencode_add_command()` |
| `mcpSetupRows` | `list_rows()` |
| `runMcpInstallCommand` | `_run_install_command(binary, args)` — used by claude install path |
| `shellQuote`/`commandLine`/`formatTomlValue`/`formatTomlArray`/`extractTomlSection`/`stripTomlSections`/`stripJsonComments`/`stripTrailingJsonCommas`/`parseJsonLikeObject`/`loadJsonObject`/`isTraceHookEntry`/`stripTraceHookEntries`/`hookCommand`/`traceHookEntry`/`traceMcpConfigObject`/`opencodeTraceConfigText` | module-level helpers |

Module-level constants:
```python
TRACE_MCP_MODULE = "mcp.trace_server"
TRACE_CODEX_HOOK_MODULE = "hooks.trace_codex_hook"
TRACE_MCP_TOOL = "trace_record_files"
TRACE_MCP_SERVER_NAME = "trace"
CODEX_MCP_ADD_PREFIX = "codex mcp add"
CLAUDE_MCP_ADD_PREFIX = "claude mcp add"
OPENCODE_MCP_ADD_PREFIX = "opencode mcp add"
```

`McpSetup` constructor: `__init__(self, workspace: Path, home: Path | None = None)`.
- `self.workspace = workspace.expanduser().resolve()`
- `self.home = home or Path.home()`
- `self.project_root = Path(__file__).resolve().parents[2]`  # code/mcp/setup.py → project root

`list_rows()` returns a list of 4 dicts (codex, claude, opencode, other) with the shape documented in §"row shape" below.

`install(server_id)` dispatches:
- `"claude"`: if already installed → `{ok:True, already_installed:True, ...}`. Else shell out via `_run_install_command(claude_bin, args)`.
- `"opencode"`: if already installed → already_installed. Else `_install_opencode_config()` and report.
- `"codex"`: if `_inspect_codex_mcp().installed and _inspect_codex_hook().installed` → already_installed. Else install both, return `replaced_existing_mcp` / `replaced_existing_hook`.
- Unknown `server_id` or `"other"` → `{ok:False, error:"..."}`.

### Row shape (each entry of `list_rows()`)

```python
{
    "id": "codex" | "claude" | "opencode" | "other",
    "name": str,
    "tool": "trace_record_files",
    "installed": bool,
    "status": "installed" | "partial" | "not-installed" | "manual",
    "status_label": str,                 # "已添加" / "待修复" / "可一键添加" / "复制配置"
    "can_auto_install": bool,
    "action_label": str,
    "command": str,                       # full shell line to show + copy
    "command_prefix": str,                # "codex mcp add" etc.
    "config_path": str,
    "description": str,
    "hook_path": str | "",                # codex only; "" otherwise
    "hook_command": str | "",             # codex only
}
```

### Install return shape

```python
{
    "ok": bool,
    "already_installed"?: bool,
    "server_id": str,
    "command": str,
    "config_path": str,
    "hook_path"?: str,                    # codex only
    "hook_installed"?: bool,              # codex only
    "replaced_existing_mcp"?: bool,       # codex only
    "replaced_existing_hook"?: bool,      # codex only
    "restart_required": bool,
    "approval_required"?: bool,           # claude only
    "error"?: str,
}
```

### Test cases (`tests/test_mcp_setup.py`)

- `test_codex_install_replaces_stale_config_and_writes_hooks`: temp `home`, pre-seed `config.toml` + `hooks.json` with a stale trace section pointing at an old workspace; run `McpSetup(workspace=ws, home=tmp_home).install("codex")`; assert `ok`, exactly one `[mcp_servers.trace]` + one `[mcp_servers.trace.env]` in the TOML, the new workspace appears, the old workspace doesn't, hooks JSON contains the new workspace and the unrelated `echo keep-me` entry is preserved.
- `test_codex_install_is_idempotent_when_already_installed`: install twice; second call returns `already_installed=True`.
- `test_codex_mcp_row_reports_partial_when_only_mcp_present`: seed only the TOML (no hooks); `list_rows()[codex]["status"] == "partial"`.
- `test_opencode_install_writes_jsonc_config`: install on fresh `home`, parse the resulting `opencode.jsonc` JSON, assert `mcp.trace.command[0]` is `sys.executable` and `--workspace <ws>` is in `args`, env contains `PYTHONPATH`.
- `test_claude_install_already_installed_skips_subprocess`: seed `~/.claude.json` so `_inspect_claude_mcp().installed` is True; `install("claude")` returns `already_installed=True` without invoking subprocess.
- `test_claude_install_invokes_claude_binary`: monkeypatch `McpSetup._run_install_command` to return `{ok:True}`; assert it was called with args containing `mcp add --scope user trace`.
- `test_other_server_id_returns_error`: `install("other")` returns `{ok:False, error}`.
- `test_list_rows_returns_four_agents_in_order`: `list_rows()` returns codex/claude/opencode/other, each with non-empty `name`, `command`, `description`; the "other" row has `can_auto_install=False`.

---

## Task 2: `TraceController.list_mcp_setup` / `install_mcp_server`

**Files:** Modify `code/tui/controller.py`, `tests/test_tui_controller.py`.

Add to `TraceController`:

```python
def list_mcp_setup(self) -> dict[str, Any]:
    try:
        from mcp.setup import McpSetup
        rows = McpSetup(self._workspace).list_rows()
        return {"ok": True, "rows": rows}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

def install_mcp_server(self, server_id: str) -> dict[str, Any]:
    try:
        from mcp.setup import McpSetup
        return McpSetup(self._workspace).install(server_id)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
```

### Test cases (extend `tests/test_tui_controller.py` with `TraceControllerMcp`)

- `test_list_mcp_setup_ok`: returns 4 rows, contains "codex" id.
- `test_install_other_returns_not_ok`: `install_mcp_server("other")["ok"] is False`.
- `test_install_codex_writes_config`: temp `home` injected via `unittest.mock.patch` on `McpSetup.__init__`'s `home` default — actually simpler: monkeypatch `Path.home()` to return `tmp_home` for the duration of the call.
- `test_list_mcp_setup_wraps_error`: stub a `McpSetup` class (via monkeypatching `mcp.setup.McpSetup`) to raise; assert `{ok:False, error}`.

---

## Task 3: `MCPView`

**Files:** Create `code/tui/views/mcp.py`, `tests/test_tui_mcp_view.py`.

```python
class InstallResultModal(ModalScreen[bool]):
    """Shows the install outcome (config path, restart hint) with an OK button."""

class MCPView(Widget):
    BINDINGS = [
        ("i", "install_highlighted", "Install"),
        ("c", "copy_command", "Copy command"),
    ]
```

Compose: a `Static(id="mcp-stats")` + `ListView(id="mcp-list")`.

`refresh_setup()` queries controller, fills list with `ListItem` per row, label = `f"{name}  ·  {status_label}  ·  {command_prefix or command}"`. Stores rows keyed by id.

`action_install_highlighted()`: get the highlighted row's id; if not `can_auto_install`, notify "manual setup — copy the command" and return. Else call `controller.install_mcp_server(id)` and push `InstallResultModal` showing the result.

`action_copy_command()`: copy the highlighted row's `command` to clipboard via `self.app.copy_to_clipboard(text)` inside try/except; notify success.

### Test cases (`tests/test_tui_mcp_view.py`)

- `test_lists_four_agent_rows`: pilot harness; `view.refresh_setup()`; `len(view.mcp_list.children) == 4`.
- `test_install_other_agent_informs_user_no_modal`: highlight "other" row → press `i` → no modal pushed; status/notification reflects "manual".
- `test_install_codex_writes_config_and_shows_modal`: monkeypatch `Path.home` to temp dir; trigger `view.action_install_for_id("codex")` directly; assert modal pushed and `~/.codex/config.toml` exists on disk; dismiss modal.
- `test_copy_command_uses_clipboard`: monkeypatch `app.copy_to_clipboard`; trigger `c`; assert called with the highlighted row's command.

(`action_install_for_id(server_id)` is a public helper used by tests so they don't have to drive highlight state.)

---

## Task 4: Mount `MCPView` in `TraceApp`

**Files:** Modify `code/tui/app.py`, `tests/test_tui_app.py`.

Replace the MCP tab's `Static("mcp", id="body-mcp")` placeholder with `MCPView(self._controller)`. Do **not** add an IPC-driven refresh for MCP (its state is independent of commit events — install state only changes when the user clicks install).

### Test (append to `tests/test_tui_app.py`)

- `test_mcp_tab_hosts_mcp_view`: query for `MCPView`, assert it's an `MCPView` instance; assert `len(view.mcp_list.children) == 4` after mount.

---

## Task 5: Full-suite check + smoke

- [ ] Run `uv run python -m unittest discover -s tests`. Expected: zero failures (baseline 389; this phase adds roughly 8 + 4 + 4 + 1 = 17 tests → ~406; exact count irrelevant, only zero-failures matters).
- [ ] Manual smoke (human-run, optional): `uv run python code/main.py --workspace test_workspace`; the MCP tab shows 4 agents with status labels; highlighting Codex and pressing `i` writes `~/.codex/config.toml` and `~/.codex/hooks.json` and shows a result modal; pressing `c` copies the highlighted command; `q` exits cleanly.
- [ ] Commit any smoke-driven fixes.

---

## Self-Review notes

- **Spec coverage (this phase):** design spec §4.2 `mcp.py` view (Tasks 3-4), §4.3 read + write data flow (Tasks 1-2), §5 error contract on install (Task 2), full-functionality-parity for MCP one-click install + copy command (Tasks 1, 3) for Codex/Claude/OpenCode.
- **Type consistency:** `list_mcp_setup → {ok, rows: [...]}`; `install_mcp_server(id) → {ok, already_installed?, restart_required, config_path, error?}`. `TraceApp(daemon, controller=None)` unchanged.
- **Markup-injection guard:** every row's `name`/`command`/`status_label` is wrapped in `rich.text.Text(...)` before going into a `ListItem`/`Label`, carrying forward the Phase 2 lesson (agent names / paths with brackets render literally).
- **Deferred to later phases:** Electron teardown (Phase 6) — do not delete `electron_app/main.js` or `code/core/electron_*_bridge.py` here. Cursor stays in `scripts/setup_cursor_mcp.py`.
- **Subprocess safety:** only the Claude path shells out; tests stub `_run_install_command`. The Codex/OpenCode paths only touch files.
