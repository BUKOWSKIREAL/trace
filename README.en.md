# Trace

> [中文](README.md) · **English**

Trace is a local version tracker built for AI-assisted, multi-agent coding. It doesn't replace Git — it complements it. When you edit the same project with Claude Code, Codex CLI, Cursor, OpenCode, and others at the same time, Trace records **which agent changed which files, and when**, in the background, and saves every change as a local snapshot you can diff, restore, or revert per agent.

Trace targets three problems that show up when several agents work on one codebase:

- **See the source** — tell apart manual human edits from Claude, Codex, Cursor, and other origins.
- **Follow the process** — merge bursts of rapid file changes into a single version record, so every step stays reviewable.
- **Recover safely** — view diffs in the Electron console and restore a single file, or roll back one agent's batch of changes, to an earlier version.

## Architecture

![Trace architecture](assets/architecture.png)

Capture file changes → filter noise → wait for the file to settle → attribute via MCP / activity / process evidence → batch-commit → persist to SQLite and content-addressed blobs → serve to the UI over an IPC bridge.

## Using Trace

### 1. Pick a workspace to track

After launching Trace, choose the project folder you want to track (for example your course-project directory). Trace creates a `.trace/` folder inside it to hold the local database and file snapshots.

`.trace/` is Trace's own local data directory — you don't edit it by hand. If the project uses Git, add `.trace/` to your `.gitignore`.

### 2. Keep Trace running in the background

Once started, Trace lives in the system tray / menu bar and runs a file-watching service. You then use your editor, terminal, or AI coding tools as usual; Trace automatically captures create, modify, delete, and move events.

Running from source:

```bash
uv sync
uv run python code/main.py --workspace /path/to/your/project
```

Running a packaged build:

- macOS: open `Trace.app` and select a workspace.
- Windows: run `Trace.exe` and select a workspace (or reuse the last one).

### 3. Configure MCP reporting for your AI tools

Trace supports MCP. Once configured, agents such as Codex and Claude Code can actively tell Trace "I just changed these files", which makes attribution more accurate than process scanning alone.

The easiest way is to open the **MCP** page in the Electron console and click the one-click "Add" button for each agent. After that, restart the corresponding AI tool so the new MCP config takes effect.

### 4. Review history, diffs, and attribution

In the Electron console you can see:

- **Timeline** — every recorded file-change commit.
- **Agents** — per-agent activity statistics.
- **Diff** — the exact per-file changes in a commit.
- **Workspace** — the current workspace, database location, and snapshot count.
- **MCP** — connection status for Codex, Claude Code, and other tools.

Trace records versions of text, Office documents, PDFs, images, and binary files; common text and document formats get a friendlier diff summary.

### 5. Restore files or revert changes

Select a history entry, review the diff, and restore as needed. Common flows:

- Restore a single file to a historical version.
- Roll back a batch of changes made by a specific agent.
- Keep the current version before restoring, to avoid accidentally overwriting existing content.

All data stays in the workspace's `.trace/` directory — nothing is uploaded to the cloud, and no LLM API key is required.

## Overview

Trace is a multi-CLI-agent version tracker. It watches workspace file changes in the background, identifies the currently active CLI agent (Claude Code, Codex CLI, Cursor, OpenClaw, OpenCode, Hermes, or Kimi Code), writes each batch of changes to a local SQLite database attributed to an agent, and stores file versions as content-addressed blobs.

## Core capabilities

- Auto-detect active CLI agents in the workspace and record `confidence`, `candidates`, and `ambiguous` attribution metadata.
- Watch file create / modify / move / delete events with watchdog.
- Filter out noise from `.git`, `.trace`, temp files, and duplicate events.
- Debounce per agent independently (2 s) and merge continuous changes into one commit.
- Store any file type as a SHA-256 blob.
- Support restore-to-any-point-in-time via full-manifest commits.
- Show diffs for text, `.docx`, `.pptx`, `.xlsx`, `.pdf`, images, and unknown binary files.
- Provide a macOS/Windows menu-bar app and an Electron console.
- Support `AgentActivityRecorder` active sampling, GUI/Script detection, ambiguous-attribution correction, per-agent selective revert, and offline-change compensation.

## Quick start

```bash
uv sync
bash scripts/demo.sh
```

Launch the full menu-bar app (it opens the Electron console by default; `--headless` runs only the daemon with no UI):

```bash
uv run python code/main.py --workspace test_workspace
```

Run the Electron console on its own (for development):

```bash
cd electron_app
npm install
npm start -- --workspace=../test_workspace
```

## Trace MCP interface

Trace ships a local stdio MCP server so agents such as Codex, Claude Code, Cursor, and OpenCode can actively report the files they changed. Codex can additionally install Trace hooks to automatically record file changes from `apply_patch`, `Write`, `Edit`, and `Bash` during PreToolUse / PostToolUse — avoiding guess-only attribution when several agents run at once. Reports are written to the workspace's `.trace/trace_activity.jsonl`; the attributor prefers these records and only falls back to transcript / process scanning when none exist.

### Quick configuration

**Claude Code CLI**: the project-root `.mcp.json` is read automatically — no extra setup.

**Cursor**: one-click automatic setup (recommended)

```bash
python scripts/setup_cursor_mcp.py
```

See [CURSOR_SETUP.md](CURSOR_SETUP.md) for details. Or configure manually in your global MCP config (on Windows, change `command` to `py`):

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

Cursor config file location:
- macOS: `~/Library/Application Support/Cursor/User/mcp.json`
- Linux: `~/.config/Cursor/User/mcp.json`
- Windows: `%APPDATA%\Cursor\User\mcp.json`

**Codex CLI**: add to `~/.codex/config.toml`:

```toml
[mcp_servers.trace]
command = "/path/to/project/.venv/bin/python"
args = ["-m", "mcp.trace_server", "--workspace", "/path/to/workspace"]

[mcp_servers.trace.env]
PYTHONPATH = "/path/to/project/code"
```

The Electron console's MCP page writes the config above directly and replaces any old `trace` section — prefer the in-page one-click add. See [MCP_SETUP.md](MCP_SETUP.md) for details and troubleshooting.

### MCP tool

- `trace_record_files(agent, files, operation="write", confidence=1.0)`

An agent calls this once before/after writing files — e.g. set `agent` to `codex`, `claude`, or `cursor`, and pass `files` as a list of workspace-relative or absolute paths.

### Codex hooks

Codex hook modules (which call the MCP automatically):

- `hooks.trace_codex_hook --workspace /path/to/workspace --phase pre`
- `hooks.trace_codex_hook --workspace /path/to/workspace --phase post`

The Electron console's MCP page writes `~/.codex/config.toml` and `~/.codex/hooks.json` in one click. After restarting Codex, run `/hooks` and trust the Trace hook once.

Developing the Electron renderer:

```bash
cd electron_app
npm run dev:renderer
VITE_DEV_SERVER_URL=http://127.0.0.1:5173 npm run start:dev -- --workspace=../test_workspace
```

## Testing

```bash
uv run python -m unittest discover -s tests
```

The current suite covers repository, watcher, batcher, activity recorder, agent detector, handlers, menu bar, the Electron renderer, packaging scripts, and multi-file-type diffs.

## Packaging

macOS:

```bash
bash scripts/build_macos_app.sh
```

This builds the Electron console, embeds `Trace Console.app` into the main `Trace.app`, re-signs ad-hoc, and produces a DMG.

Windows (run on Windows):

```powershell
pwsh .\scripts\build_windows_app.ps1
```

This builds the Electron Windows unpacked directory, then uses PyInstaller to produce `dist\Trace\Trace.exe` and `dist\Trace\TraceBridge.exe`.

Source launcher fallback:

```bash
bash install.sh
```

## Directory layout

```text
code/             Python source
tests/            unit and E2E tests
electron_app/     Electron console
scripts/          demo and packaging scripts
prompts/          vibe-coding prompts
screenshots/      demo screenshots
assets/           static assets (diagrams, icons)
dist/             local build output (gitignored)
test_workspace/   local demo workspace (gitignored)
```

## Known limitations

- The Windows packaging script and PyInstaller spec are complete, but the `.exe` still needs to be built and validated on a real Windows machine.
- Linux is source-compatible but not yet validated on real hardware.
- Legacy `.ppt` files can be tracked and restored as binary, but without the semantic diff that `.pptx` gets.
- Offline changes made while the daemon is not running are not backfilled.
- File permission bits are not stored; e.g. a script's executable bit (`+x`) must be reapplied manually after restore.

## License

[MIT](LICENSE)
