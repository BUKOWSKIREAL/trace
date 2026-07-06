"""
忽略规则（共享）
==================
判定一个路径是否应被Trace忽略——daemon/watcher.py（实时过滤）和
core/repository.py（备份扫描）都要用，所以提到 utils 层共享，避免
反向依赖（core → daemon）。

# 人工编写（评审 #2 重构：从 daemon/watcher.py 抽出来）
"""
from __future__ import annotations

import fnmatch
from pathlib import Path


# 出现在路径段中的目录名 → 整个子树都忽略
IGNORE_PARTS = {
    ".git",
    ".trace",
    "__pycache__",
    "node_modules",
    ".DS_Store",
    ".pytest_cache",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
    ".mypy_cache",
}

# 文件扩展名
IGNORE_SUFFIXES = {".pyc", ".pyo", ".swp", ".swo", ".tmp", ".log"}

# 文件名前缀（Office / Emacs 临时文件）
IGNORE_PREFIXES = {"~$", ".#", "#"}


def _matches_extra_pattern(path: Path, pattern: str) -> bool:
    """Match a user-configured ignore pattern from config.json."""
    raw = pattern.strip()
    if not raw:
        return False

    posix = path.as_posix()
    if raw.endswith("/"):
        part = raw.strip("/")
        return part in path.parts

    if "*" in raw or "?" in raw or "[" in raw:
        if fnmatch.fnmatch(path.name, raw):
            return True
        return fnmatch.fnmatch(posix, raw)

    if raw in path.parts or path.name == raw:
        return True
    return posix.endswith(raw)


def should_ignore(path: Path, extra_patterns: list[str] | None = None) -> bool:
    """返回 True 表示这个路径应被忽略（不入库、不备份）。"""
    if any(p in IGNORE_PARTS for p in path.parts):
        return True
    if path.suffix.lower() in IGNORE_SUFFIXES:
        return True
    if any(path.name.startswith(p) for p in IGNORE_PREFIXES):
        return True
    for pattern in extra_patterns or []:
        if _matches_extra_pattern(path, pattern):
            return True
    return False
