"""
Transcript-based agent attribution
==================================
Process scans say which agents are active, not which one wrote a file. This
detector looks for stronger local evidence in Claude Code and Codex transcripts:
recent tool calls whose cwd and command mention the changed file.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from models.agent import AgentAttribution

logger = logging.getLogger("trace.detector.transcript")

DEFAULT_WINDOW_SECONDS = 180.0
MAX_FILES_PER_AGENT = 30


@dataclass(frozen=True)
class TranscriptHit:
    agent: str
    detection_method: str
    timestamp: float
    source: Path


def find_transcript_attribution(
    workspace: Path,
    file_path: Path,
    event_time: float,
    *,
    home: Path | None = None,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
) -> AgentAttribution | None:
    """
    Return transcript-backed attribution for a recent file event.

    A single matching agent is high-confidence. Multiple matching agents remain
    ambiguous because both transcripts contain plausible write evidence.
    No match returns None so the caller can fall back to process scanning.
    """
    home = home or Path.home()
    workspace = workspace.expanduser().resolve()
    file_path = _safe_resolve(file_path)

    hits = [
        *scan_claude_transcripts(
            home, workspace, file_path, event_time, window_seconds
        ),
        *scan_codex_transcripts(home, workspace, file_path, event_time, window_seconds),
    ]
    if not hits:
        return None

    agents = list(
        dict.fromkeys(hit.agent for hit in sorted(hits, key=lambda h: h.timestamp))
    )
    if len(agents) == 1:
        hit = min(hits, key=lambda h: abs(h.timestamp - event_time))
        return AgentAttribution(
            agent=hit.agent,
            confidence=0.93,
            detection_method=hit.detection_method,
        )

    return AgentAttribution(
        agent="unknown",
        confidence=0.5,
        detection_method="transcript_ambiguous",
        ambiguous=True,
        candidates=agents,
    )


def scan_claude_transcripts(
    home: Path,
    workspace: Path,
    file_path: Path,
    event_time: float,
    window_seconds: float,
) -> list[TranscriptHit]:
    hits: list[TranscriptHit] = []
    for transcript in _recent_claude_transcripts(home, workspace, event_time):
        for row in _read_jsonl(transcript):
            ts = _timestamp(row)
            if ts is None or abs(ts - event_time) > window_seconds:
                continue
            cwd_value = row.get("cwd")
            cwd = (
                Path(cwd_value)
                if isinstance(cwd_value, str) and cwd_value
                else Path("/")
            )
            for command in _claude_commands(row):
                if _command_mentions_file(command, cwd, workspace, file_path):
                    hits.append(
                        TranscriptHit("claude", "claude_transcript", ts, transcript)
                    )
    return hits


def scan_codex_transcripts(
    home: Path,
    workspace: Path,
    file_path: Path,
    event_time: float,
    window_seconds: float,
) -> list[TranscriptHit]:
    hits: list[TranscriptHit] = []
    for transcript in _recent_codex_transcripts(home, event_time):
        session_cwd: Path | None = None
        for row in _read_jsonl(transcript):
            if row.get("type") == "session_meta":
                payload = row.get("payload") or {}
                if payload.get("cwd"):
                    session_cwd = Path(payload["cwd"])
                continue

            ts = _timestamp(row)
            if ts is None or abs(ts - event_time) > window_seconds:
                continue
            for command, workdir in _codex_commands(row):
                cwd = Path(workdir) if workdir else (session_cwd or workspace)
                if _command_mentions_file(command, cwd, workspace, file_path):
                    hits.append(
                        TranscriptHit("codex", "codex_transcript", ts, transcript)
                    )
    return hits


def _recent_claude_transcripts(
    home: Path, workspace: Path, event_time: float
) -> list[Path]:
    projects_root = home / ".claude" / "projects"
    candidates: list[Path] = []
    direct = projects_root / _claude_project_dir_name(workspace)
    if direct.is_dir():
        candidates.extend(direct.glob("*.jsonl"))

    # Fallback for path sanitization changes: only inspect a small recent set.
    if not candidates and projects_root.is_dir():
        candidates.extend(projects_root.glob("*/*.jsonl"))

    return _filter_recent_files(candidates, event_time)


def _recent_codex_transcripts(home: Path, event_time: float) -> list[Path]:
    sessions_root = home / ".codex" / "sessions"
    dt = datetime.fromtimestamp(event_time)
    candidates: list[Path] = []
    day_dir = sessions_root / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}"
    if day_dir.is_dir():
        candidates.extend(day_dir.glob("*.jsonl"))

    return _filter_recent_files(candidates, event_time)


def _filter_recent_files(paths: Iterable[Path], event_time: float) -> list[Path]:
    lower = event_time - 24 * 60 * 60
    recent: list[Path] = []
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= lower:
            recent.append(path)
    recent.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return recent[:MAX_FILES_PER_AGENT]


def _claude_project_dir_name(workspace: Path) -> str:
    # Claude Code sanitizes project paths by replacing every non-alphanumeric
    # character (including _, ., spaces and path separators) with '-'.
    return re.sub(r"[^A-Za-z0-9]", "-", str(workspace))


def _read_jsonl(path: Path) -> Iterable[dict]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError as exc:
        logger.debug("Unable to read transcript %s: %s", path, exc)


def _timestamp(row: dict) -> float | None:
    value = row.get("timestamp")
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _claude_commands(row: dict) -> Iterable[str]:
    message = row.get("message") or {}
    content = message.get("content") or []
    if not isinstance(content, list):
        return
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "tool_use" or item.get("name") != "Bash":
            continue
        tool_input = item.get("input") or {}
        command = tool_input.get("command")
        if isinstance(command, str) and command:
            yield command


def _codex_commands(row: dict) -> Iterable[tuple[str, str | None]]:
    payload = row.get("payload") or {}
    if payload.get("type") != "function_call" or payload.get("name") != "exec_command":
        return
    raw_args = payload.get("arguments")
    if not isinstance(raw_args, str):
        return
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        return
    command = args.get("cmd")
    if not isinstance(command, str) or not command:
        return
    workdir = args.get("workdir")
    yield command, workdir if isinstance(workdir, str) else None


def _command_mentions_file(
    command: str, cwd: Path, workspace: Path, file_path: Path
) -> bool:
    normalized_command = command.replace("\\", "/")
    file_abs = _safe_resolve(file_path)
    cwd = _safe_resolve(cwd)
    workspace = _safe_resolve(workspace)

    if str(file_abs).replace("\\", "/") in normalized_command:
        return True

    # Relative path and basename matches are only trustworthy when the transcript
    # command ran inside this workspace. During Claude fallback scans we may read
    # other projects' transcripts; generic names like README.md must not match.
    if not _is_within(cwd, workspace):
        return False

    try:
        rel_to_workspace = file_abs.relative_to(workspace)
    except ValueError:
        rel_to_workspace = None
    if (
        rel_to_workspace is not None
        and rel_to_workspace.as_posix() in normalized_command
    ):
        return True

    if file_abs.name in normalized_command:
        return True

    return False


def _safe_resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(child: Path, parent: Path) -> bool:
    child = _safe_resolve(child)
    parent = _safe_resolve(parent)
    return child == parent or parent in child.parents
