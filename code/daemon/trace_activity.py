"""
Trace-side agent activity reports.

This module stores explicit file-change reports from integrations such as MCP.
They are stronger than passive process scans because the agent declares the
files it is about to change or has just changed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from models.agent import AgentAttribution


@dataclass(frozen=True)
class TraceActivityReport:
    timestamp: float
    agent: str
    files: list[str]
    operation: str
    source: str
    confidence: float


class TraceActivityStore:
    """JSONL-backed explicit activity store scoped to one workspace."""

    def __init__(self, workspace: Path, *, max_age: float = 600.0):
        self.workspace = workspace.expanduser().resolve(strict=False)
        self.max_age = max_age
        self.path = self.workspace / ".trace" / "trace_activity.jsonl"

    def record_files(
        self,
        *,
        agent: str,
        files: list[str],
        operation: str = "write",
        event_time: float | None = None,
        source: str = "mcp",
        confidence: float = 1.0,
    ) -> TraceActivityReport:
        timestamp = event_time if event_time is not None else time.time()
        normalized_files = [self._normalize_file(value) for value in files if value]
        report = TraceActivityReport(
            timestamp=timestamp,
            agent=str(agent or "unknown"),
            files=normalized_files,
            operation=str(operation or "write"),
            source=str(source or "mcp"),
            confidence=float(confidence),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "timestamp": report.timestamp,
                        "agent": report.agent,
                        "files": report.files,
                        "operation": report.operation,
                        "source": report.source,
                        "confidence": report.confidence,
                    },
                    ensure_ascii=False,
                )
            )
            handle.write("\n")
        return report

    def resolve(self, file_path: Path, event_time: float) -> AgentAttribution | None:
        matches = self.query(file_path, event_time - self.max_age, event_time + 2.0)
        if not matches:
            return None

        matches.sort(key=lambda report: abs(report.timestamp - event_time))
        best = matches[0]
        if best.agent == "unknown":
            return None
        return AgentAttribution(
            agent=best.agent,
            confidence=best.confidence,
            detection_method=f"trace_{best.source}",
        )

    def query(self, file_path: Path, t0: float, t1: float) -> list[TraceActivityReport]:
        target = self._normalize_file(str(file_path))
        reports: list[TraceActivityReport] = []
        if not self.path.exists():
            return reports

        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                timestamp = float(row.get("timestamp", 0))
            except (TypeError, ValueError):
                continue
            if not (t0 <= timestamp <= t1):
                continue

            files = [
                self._normalize_file(str(value))
                for value in row.get("files", [])
                if isinstance(value, str) and value
            ]
            if target not in files:
                continue

            reports.append(
                TraceActivityReport(
                    timestamp=timestamp,
                    agent=str(row.get("agent") or "unknown"),
                    files=files,
                    operation=str(row.get("operation") or "write"),
                    source=str(row.get("source") or "mcp"),
                    confidence=float(row.get("confidence") or 1.0),
                )
            )
        return reports

    def _normalize_file(self, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        try:
            rel = path.resolve(strict=False).relative_to(self.workspace)
            return rel.as_posix()
        except ValueError:
            return path.resolve(strict=False).as_posix()
