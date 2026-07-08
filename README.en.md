# Trace

> [中文](README.md) · **English**

Trace is a local version tracker for AI-assisted, multi-agent coding. It does not replace Git — it complements it. When Claude Code, Codex CLI, Cursor, OpenCode, and other tools edit the same project, Trace records **which agent changed which files, and when**, then stores every change as a local snapshot you can diff, restore, or revert per agent.

Trace is now a pure Python + Textual TUI product: one command starts both the watcher daemon and the terminal UI; leaving the TUI stops tracking.

## Goals

- **See the source** — tell manual edits apart from Claude, Codex, Cursor, and other origins.
- **Follow the process** — merge rapid bursts of file changes into reviewable version records.
- **Recover safely** — inspect diffs in the Textual TUI, restore a single file, or revert one agent's contribution.

## Architecture

![Trace architecture](assets/architecture.svg)

Capture file changes → filter noise → wait for files to settle → attribute via MCP / activity / transcript / process evidence → debounce per agent → commit to SQLite and content-addressed blobs → render through the in-process Textual TUI.

## Quick start

```bash
uv sync
uv run python code/main.py --workspace test_workspace
```

If `--workspace` is omitted, Trace reuses the last workspace. If none exists, it opens a Textual directory picker.

Common commands:

```bash
# Run the full test suite
uv run python -m unittest discover -s tests

# Generate demo data in test_workspace/.trace
bash scripts/demo.sh

# Run only the daemon, with no TUI
uv run python code/main.py --workspace test_workspace --headless

# Force workspace selection
uv run python code/main.py --choose
```

After installing the project entrypoint, you can also run:

```bash
trace --workspace /path/to/workspace
```

## TUI features

The Textual TUI has four views:

- **Commits** — timeline, per-file diffs, single-file restore, and low-confidence attribution reassignment.
- **Agents** — per-agent activity stats and previewed agent-level revert.
- **Workspace** — current workspace, database path, commit/snapshot/agent counts.
- **MCP** — config status and one-click setup for Codex, Claude Code, OpenCode, and manual configs.

Trace stores versions of text, Office documents, PDFs, images, and unknown binary files. Common text and document formats get friendlier diff summaries.

## Trace MCP interface

Trace ships a local stdio MCP server so agents such as Codex, Claude Code, Cursor, and OpenCode can explicitly report the files they changed. Codex can additionally install Trace hooks that automatically record changes from `apply_patch`, `Write`, `Edit`, and `Bash` during PreToolUse / PostToolUse.

Reports are written to `.trace/trace_activity.jsonl` in the workspace. Attribution prefers these records before falling back to transcripts or process scanning.

### Quick configuration

**Claude Code CLI**: the project-root `.mcp.json` is read automatically.

**Cursor**: automatic setup (recommended):

```bash
python scripts/setup_cursor_mcp.py
```

See [CURSOR_SETUP.md](CURSOR_SETUP.md). Or configure manually in your global MCP config; on Windows, change `command` to `py`:

```json
{
  "mcpServers": {
    "trace": {
      "type": "stdio",
      "command": "/path/to/project/.venv/bin/python",
      "args": ["/path/to/project/run_mcp_server.py", "--workspace", "/path/to/workspace"]
    }
  }
}
```

**Codex CLI**: add to `~/.codex/config.toml`:

```toml
[mcp_servers.trace]
command = "/path/to/project/.venv/bin/python"
args = ["-m", "mcp.trace_server", "--workspace", "/path/to/workspace"]

[mcp_servers.trace.env]
PYTHONPATH = "/path/to/project/code"
```

You can also use the **MCP** view in the TUI for one-click setup. It replaces stale `trace` sections so the workspace does not point at an old path. See [MCP_SETUP.md](MCP_SETUP.md) for details.

### MCP tool

- `trace_record_files(agent, files, operation="write", confidence=1.0)`

Call it before or after writing files. Set `agent` to values such as `codex`, `claude`, or `cursor`, and pass workspace-relative or absolute file paths.

### Codex hooks

Trace hook modules:

- `hooks.trace_codex_hook --workspace /path/to/workspace --phase pre`
- `hooks.trace_codex_hook --workspace /path/to/workspace --phase post`

The TUI MCP view can write `~/.codex/config.toml` and `~/.codex/hooks.json` automatically. Restart Codex, then run `/hooks` and trust the Trace hook once.

## Directory layout

```text
code/             Python source (daemon / repository / handlers / TUI / MCP)
tests/            unittest suite
scripts/          demo, self-tests, and MCP helpers
prompts/          development prompt notes
screenshots/      historical demo screenshots
assets/           architecture and static assets
dist/             local build output (gitignored)
test_workspace/   local demo workspace (gitignored)
```

## Testing

```bash
uv run python -m unittest discover -s tests
```

The suite covers repository, watcher, batcher, activity recorder, agent detection, handlers, MCP, TUI controller/views, workspace selection, and multi-file-type diffs.

## Known limitations

- Legacy `.ppt` files are tracked/restored as binary, without the semantic diff available for `.pptx`.
- File permission bits are not stored; for example, executable bits may need to be reapplied after restore.
- Complex human/agent conflict resolution should still be handled with Git.

## License

[MIT](LICENSE)
