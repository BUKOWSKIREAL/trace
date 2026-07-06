"""
AgentActivityRecorder — 主动采样架构

后台持续记录写活动证据，watchdog 事件来时按 (path, event_time) 反查。
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from daemon.detectors import scan_active_agents
from daemon.detectors.cli_detector import KNOWN_CLI_AGENTS, _is_within
from models.agent import AgentAttribution

logger = logging.getLogger("trace.activity")


@dataclass(frozen=True)
class WriteActivityEvent:
    timestamp: float
    pid: int
    agent: str
    path: Path
    op: str
    source: str
    confidence: float


class ActivityStore:
    """Thread-safe ring buffer of recent write activity."""

    def __init__(self, *, max_age: float = 600.0, max_events: int = 10000):
        self.max_age = max_age
        self.max_events = max_events
        self._events: list[WriteActivityEvent] = []
        self._lock = threading.Lock()

    def record(self, event: WriteActivityEvent) -> None:
        with self._lock:
            self._events.append(event)
            self._prune_locked(time.time())

    def query(self, path: Path, t0: float, t1: float) -> list[WriteActivityEvent]:
        target = _normalize_path(path)
        with self._lock:
            self._prune_locked(time.time())
            return [
                e
                for e in self._events
                if t0 <= e.timestamp <= t1 and _paths_match(e.path, target)
            ]

    def _prune_locked(self, now: float) -> None:
        cutoff = now - self.max_age
        self._events = [e for e in self._events if e.timestamp >= cutoff]
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]


def _normalize_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return path.expanduser()


def _paths_match(left: Path, right: Path) -> bool:
    left_n = _normalize_path(left)
    right_n = _normalize_path(right)
    return left_n == right_n


def parse_fs_usage_line(line: str, workspace: Path) -> WriteActivityEvent | None:
    """Parse a single fs_usage output line into a write activity event."""
    if not line or line.startswith("Tracing"):
        return None
    upper = line.upper()
    if " WRITE " not in f" {upper} " and " RENAME " not in f" {upper} ":
        return None

    parts = line.split()
    if len(parts) < 4:
        return None

    pid = 0
    for index, token in enumerate(parts):
        if token.upper() in {"WRITE", "RENAME"} and index + 1 < len(parts):
            try:
                pid = int(parts[index + 1])
            except ValueError:
                pid = 0
            break

    raw_path = parts[-1]
    if not raw_path.startswith("/"):
        return None

    path = Path(raw_path)
    try:
        if not _is_within(path, workspace):
            return None
    except Exception:
        return None

    agent = _agent_for_pid(pid) or "unknown"
    op = "rename" if "RENAME" in upper else "write"
    return WriteActivityEvent(
        timestamp=time.time(),
        pid=pid,
        agent=agent,
        path=path,
        op=op,
        source="fs_usage",
        confidence=0.98,
    )


def _agent_for_pid(pid: int) -> str | None:
    try:
        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
        base = name.rsplit("/", 1)[-1]
        if base.endswith(".exe"):
            base = base[:-4]
        if base in KNOWN_CLI_AGENTS:
            meta = KNOWN_CLI_AGENTS[base]
            return meta.get("canonical", base)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None
    return None


class AgentActivityRecorder:
    POLL_INTERVAL = 3.0
    OPEN_FILES_INTERVAL = 15.0

    def __init__(self, workspace: Path, *, high_precision_mode: bool = False):
        self.workspace = workspace.expanduser().resolve(strict=False)
        self.high_precision_mode = high_precision_mode
        self.store = ActivityStore()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._fs_proc: subprocess.Popen[str] | None = None
        self._last_open_files_sample = 0.0

    def start(self) -> None:
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._poll_loop, name="trace-activity-poll", daemon=True),
            threading.Thread(
                target=self._transcript_loop, name="trace-activity-transcript", daemon=True
            ),
        ]
        if self.high_precision_mode and sys.platform == "darwin":
            self._threads.append(
                threading.Thread(
                    target=self._fs_usage_loop, name="trace-activity-fsusage", daemon=True
                )
            )
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc = self._fs_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._fs_proc = None

    def resolve(self, file_path: Path, event_time: float) -> AgentAttribution | None:
        hits = self.store.query(file_path, event_time - 2.0, event_time + 0.5)
        if not hits:
            return None

        by_agent: dict[str, list[WriteActivityEvent]] = {}
        for hit in hits:
            by_agent.setdefault(hit.agent, []).append(hit)

        agents = [a for a in by_agent if a != "unknown"]
        if not agents:
            return None
        if len(agents) == 1:
            agent = agents[0]
            best = min(by_agent[agent], key=lambda h: abs(h.timestamp - event_time))
            return AgentAttribution(
                agent=agent,
                confidence=best.confidence,
                detection_method=f"activity_{best.source}",
            )

        candidates = list(dict.fromkeys(agents))
        return AgentAttribution(
            agent="unknown",
            confidence=0.5,
            detection_method="activity_ambiguous",
            ambiguous=True,
            candidates=candidates,
        )

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.POLL_INTERVAL):
            try:
                self._sample_psutil()
            except Exception:
                logger.exception("psutil activity sampling failed")

    def _transcript_loop(self) -> None:
        while not self._stop.wait(2.0):
            try:
                self._sample_transcripts()
            except Exception:
                logger.exception("transcript activity sampling failed")

    def _fs_usage_loop(self) -> None:
        try:
            self._fs_proc = subprocess.Popen(
                ["fs_usage", "-w", "-f", "filesystem"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            logger.warning("fs_usage 启动失败（可能需要 sudo）: %s", exc)
            return

        assert self._fs_proc.stdout is not None
        workspace_hint = str(self.workspace)
        for line in self._fs_proc.stdout:
            if self._stop.is_set():
                break
            if workspace_hint not in line:
                continue
            event = parse_fs_usage_line(line, self.workspace)
            if event is not None:
                self.store.record(event)

    def _sample_psutil(self) -> None:
        now = time.time()
        active = scan_active_agents(self.workspace)
        seen_pids = {a.pid for a in active if a.pid}
        if not seen_pids:
            return

        if now - self._last_open_files_sample < self.OPEN_FILES_INTERVAL:
            return
        self._last_open_files_sample = now

        for agent in active:
            if not agent.pid:
                continue
            try:
                proc = psutil.Process(agent.pid)
                for opened in proc.open_files():
                    path = Path(opened.path)
                    if _is_within(path, self.workspace):
                        self.store.record(
                            WriteActivityEvent(
                                timestamp=now,
                                pid=agent.pid,
                                agent=agent.name,
                                path=path,
                                op="write",
                                source="psutil_poll",
                                confidence=0.80,
                            )
                        )
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue

    def _sample_transcripts(self) -> None:
        # Transcript-backed path evidence is resolved on demand in
        # attribution_resolver; the tail loop stays lightweight for now.
        return
