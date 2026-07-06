"""
Codex lifecycle hook for Trace attribution.

Codex MCP tools are available to the model, but not guaranteed to be called.
This hook records file paths during Codex tool lifecycle events so Trace can
attribute filesystem changes before falling back to passive process detection.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any

from daemon.trace_activity import TraceActivityReport, TraceActivityStore
from utils.ignore import should_ignore


PATCH_PATH_PREFIXES = (
    "*** Add File: ",
    "*** Update File: ",
    "*** Delete File: ",
    "*** Move to: ",
)
PATH_KEYS = {
    "file",
    "file_path",
    "filepath",
    "filename",
    "path",
    "target",
    "target_file",
    "target_path",
}
COMMAND_KEYS = {"cmd", "command", "script", "shell", "bash"}
INPUT_KEYS = ("tool_input", "toolInput", "input", "arguments", "params")
TOOL_NAME_KEYS = ("tool_name", "toolName", "name", "tool", "matcher")
WRITE_TOOLS = {"apply_patch", "Edit", "Write", "MultiEdit"}
SCAN_TOOLS = {"Bash", "Shell", "exec_command"}
RECENT_WINDOW_SECONDS = 20.0


def parse_patch_paths(text: str) -> list[str]:
    paths: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        for prefix in PATCH_PATH_PREFIXES:
            if line.startswith(prefix):
                value = line[len(prefix) :].strip()
                if value:
                    paths.append(value)
                break
    return _dedupe(paths)


def run_hook(
    payload: dict[str, Any],
    *,
    workspace: Path,
    phase: str,
    event_time: float | None = None,
) -> list[TraceActivityReport]:
    workspace = workspace.expanduser().resolve(strict=False)
    timestamp = event_time if event_time is not None else time.time()
    tool_name = _extract_tool_name(payload)
    tool_input = _extract_tool_input(payload)
    files = extract_files(
        payload,
        workspace=workspace,
        phase=phase,
        tool_name=tool_name,
        event_time=timestamp,
    )

    if not files:
        return []

    confidence = 0.98 if phase == "post" and tool_name in SCAN_TOOLS else 1.0

    store = TraceActivityStore(workspace)
    return [
        store.record_files(
            agent="codex",
            files=files,
            operation="write",
            event_time=timestamp,
            source=f"codex_hook_{phase}",
            confidence=confidence,
        )
    ]


def extract_files(
    payload: dict[str, Any],
    *,
    workspace: Path,
    phase: str,
    tool_name: str,
    event_time: float | None = None,
) -> list[str]:
    tool_input = _extract_tool_input(payload)
    explicit = _explicit_paths(tool_input, workspace)
    if phase == "post" and tool_name in SCAN_TOOLS:
        recent = _recent_workspace_files(workspace, event_time or time.time())
        if recent:
            return recent
        return explicit
    if explicit:
        return explicit

    return []


def _extract_tool_name(payload: dict[str, Any]) -> str:
    for key in TOOL_NAME_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    tool = payload.get("tool")
    if isinstance(tool, dict):
        for key in TOOL_NAME_KEYS:
            value = tool.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_tool_input(payload: dict[str, Any]) -> Any:
    for key in INPUT_KEYS:
        if key in payload:
            return _jsonish(payload[key])
    return payload


def _jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    if stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _explicit_paths(value: Any, workspace: Path) -> list[str]:
    paths: list[str] = []
    for candidate in _walk_path_candidates(value, key=""):
        paths.extend(_paths_from_candidate(candidate, workspace))
    return _dedupe(_normalize_paths(paths, workspace))


def _walk_path_candidates(value: Any, *, key: str) -> list[str]:
    found: list[str] = []
    key_lc = key.lower()

    if isinstance(value, dict):
        for child_key, child_value in value.items():
            child_key_lc = str(child_key).lower()
            if child_key_lc == "patch" and isinstance(child_value, str):
                found.extend(parse_patch_paths(child_value))
            elif child_key_lc in PATH_KEYS:
                if isinstance(child_value, list):
                    found.extend(str(item) for item in child_value if isinstance(item, str))
                elif isinstance(child_value, str):
                    found.append(child_value)
            elif child_key_lc in COMMAND_KEYS and isinstance(child_value, str):
                found.append(child_value)
            else:
                found.extend(_walk_path_candidates(child_value, key=child_key_lc))
        return found

    if isinstance(value, list):
        for item in value:
            found.extend(_walk_path_candidates(item, key=key_lc))
        return found

    if isinstance(value, str):
        if key_lc == "patch" or value.startswith("*** Begin Patch"):
            found.extend(parse_patch_paths(value))
        elif key_lc in COMMAND_KEYS:
            found.append(value)
    return found


def _paths_from_candidate(value: str, workspace: Path) -> list[str]:
    if not value:
        return []
    if "\n" in value and value.startswith("*** Begin Patch"):
        return parse_patch_paths(value)

    paths: list[str] = []
    raw = value.strip()
    if _looks_like_path(raw, workspace):
        paths.append(raw)
    paths.extend(_extract_paths_from_command(raw, workspace))
    return paths


def _extract_paths_from_command(command: str, workspace: Path) -> list[str]:
    paths: list[str] = []
    workspace_text = re.escape(workspace.as_posix())
    for quoted in re.finditer(r"""["']([^"']+)["']""", command):
        value = quoted.group(1)
        if _looks_like_path(value, workspace):
            paths.append(value)

    for match in re.finditer(rf"{workspace_text}/[^\s'\";|&><)]+", command):
        paths.append(match.group(0))

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for token in tokens:
        if _looks_like_path(token, workspace):
            paths.append(token)
    return paths


def _looks_like_path(value: str, workspace: Path) -> bool:
    if not value or value.startswith("-"):
        return False
    if "\x00" in value:
        return False
    path = Path(value).expanduser()
    if path.is_absolute():
        try:
            path.resolve(strict=False).relative_to(workspace)
            return True
        except ValueError:
            return False
    return (
        "/" in value
        or "\\" in value
        or Path(value).suffix != ""
        or value in {".", ".."}
    )


def _normalize_paths(values: list[str], workspace: Path) -> list[str]:
    normalized: list[str] = []
    for value in values:
        raw = value.strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = workspace / path
        path = path.resolve(strict=False)
        try:
            rel = path.relative_to(workspace)
        except ValueError:
            continue
        if not rel.parts or should_ignore(rel):
            continue
        normalized.append(rel.as_posix())
    return normalized


def _recent_workspace_files(workspace: Path, now: float) -> list[str]:
    cutoff = now - RECENT_WINDOW_SECONDS
    found: list[str] = []
    for root, dirs, files in os.walk(workspace):
        root_path = Path(root)
        try:
            rel_root = root_path.resolve(strict=False).relative_to(workspace)
        except ValueError:
            continue

        dirs[:] = [
            name
            for name in dirs
            if not should_ignore((rel_root / name) if rel_root.parts else Path(name))
        ]

        for name in files:
            rel = (rel_root / name) if rel_root.parts else Path(name)
            if should_ignore(rel):
                continue
            full_path = root_path / name
            try:
                stat = full_path.stat()
            except OSError:
                continue
            if cutoff <= stat.st_mtime <= now + 2.0:
                found.append(rel.as_posix())
    return _dedupe(found)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record Codex file activity for Trace.")
    parser.add_argument(
        "--workspace",
        default=os.environ.get("TRACE_WORKSPACE") or ".",
        help="Workspace whose .trace/trace_activity.jsonl receives hook reports.",
    )
    parser.add_argument(
        "--phase",
        choices=("pre", "post"),
        default="post",
        help="Codex lifecycle phase that invoked this hook.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        run_hook(payload, workspace=Path(args.workspace), phase=args.phase)
    except Exception as exc:
        _log_error(exc)
    return 0


def _log_error(exc: Exception) -> None:
    try:
        log_path = Path.home() / ".codex" / "trace_hook.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {exc}\n")
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
