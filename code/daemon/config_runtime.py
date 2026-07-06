"""
Runtime configuration for the Trace daemon.

Loads `.trace/config.json`, exposes typed accessors, and supports hot updates
from the menubar without restarting the watcher.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from utils.config import DEFAULT_CONFIG, load_config, save_config

logger = logging.getLogger("trace.config")


class RuntimeConfig:
    """Thread-safe view over workspace config.json."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = load_config(config_path)

    def reload(self) -> dict[str, Any]:
        with self._lock:
            self._data = load_config(self.config_path)
            return dict(self._data)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    @property
    def tracking_enabled(self) -> bool:
        with self._lock:
            return bool(self._data.get("tracking_enabled", True))

    @property
    def high_precision_mode(self) -> bool:
        with self._lock:
            return bool(self._data.get("high_precision_mode", False))

    @property
    def ignore_patterns(self) -> list[str]:
        with self._lock:
            patterns = self._data.get("ignore_patterns") or []
            return [str(p) for p in patterns if str(p).strip()]

    def forced_agent_override(self) -> str | None:
        """Return forced agent name, or None for automatic detection."""
        with self._lock:
            value = str(self._data.get("forced_agent", "auto") or "auto").strip()
            if not value or value == "auto":
                return None
            return value

    def set_forced_agent(self, agent: str | None) -> None:
        with self._lock:
            self._data["forced_agent"] = agent if agent else "auto"
            save_config(self.config_path, self._data)
            logger.info("已持久化 forced_agent=%s", self._data["forced_agent"])

    def set_tracking_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._data["tracking_enabled"] = bool(enabled)
            save_config(self.config_path, self._data)

    def ensure_defaults(self) -> None:
        with self._lock:
            merged = dict(DEFAULT_CONFIG)
            merged.update(self._data)
            if merged != self._data:
                self._data = merged
                save_config(self.config_path, self._data)
