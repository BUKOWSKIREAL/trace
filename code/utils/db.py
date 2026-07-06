"""
SQLite 数据库初始化与连接管理
================================
关键设计：**每个线程独立 connection**（SQLite 默认不允许跨线程共享）。

"""

import atexit
import sqlite3
import threading
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS commits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    time            TEXT    NOT NULL,
    author_agent    TEXT    NOT NULL,
    detection_method TEXT   NOT NULL,
    confidence      REAL    NOT NULL DEFAULT 1.0,
    candidates      TEXT,                       -- JSON array, ambiguous 时记录所有候选
    summary         TEXT                        -- 简短描述，如 "改了 3 个文件"
);

CREATE TABLE IF NOT EXISTS snapshots (
    commit_id   INTEGER NOT NULL,
    file_path   TEXT    NOT NULL,
    blob_hash   TEXT    NOT NULL,
    PRIMARY KEY (commit_id, file_path),
    FOREIGN KEY (commit_id) REFERENCES commits(id)
);

CREATE TABLE IF NOT EXISTS agents (
    name         TEXT PRIMARY KEY,
    category     TEXT NOT NULL,                 -- 'cli' | 'gui_app' | 'web' | 'local_script'
    match_rules  TEXT NOT NULL,                 -- JSON
    display_name TEXT NOT NULL,
    color        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commits_time ON commits(time);
CREATE INDEX IF NOT EXISTS idx_commits_agent ON commits(author_agent);
"""


# 预置 agent 数据（首次建库时塞进去）
PRESET_AGENTS = [
    ("claude", "cli", '{"process_name":["claude"]}', "Claude Code", "#D97757"),
    ("codex", "cli", '{"process_name":["codex"]}', "Codex CLI", "#10A37F"),
    ("openclaw", "cli", '{"process_name":["openclaw"]}', "OpenClaw", "#5E6AD2"),
    ("opencode", "cli", '{"process_name":["opencode"]}', "OpenCode", "#2F80ED"),
    ("hermes", "cli", '{"process_name":["hermes"]}', "Hermes", "#C89211"),
    (
        "kimi",
        "cli",
        '{"process_name":["kimi","kimi-code","kimi code"]}',
        "Kimi Code",
        "#8B5CF6",
    ),
    ("cursor", "gui_app", '{"app_name":["Cursor"]}', "Cursor", "#7C3AED"),
    ("vscode", "gui_app", '{"app_name":["Code","Visual Studio Code"]}', "VS Code", "#007ACC"),
    ("claude-script", "local_script", "{}", "Claude Script", "#D97757"),
    ("codex-script", "local_script", "{}", "Codex Script", "#10A37F"),
    ("local-script", "local_script", "{}", "Local AI Script", "#6B7280"),
    ("human", "manual", "{}", "Human", "#9B9A97"),
    ("unknown", "cli", "{}", "Unknown", "#787774"),
]


class TraceConnection(sqlite3.Connection):
    """SQLite connection that closes itself before GC emits ResourceWarning."""

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# 每个 (线程, db_path) 持一个 connection（thread-local + dict）
# # 人工修正（评审 #1）：原版只按线程缓存，第二个 db_path 进来会复用第一个
# # 连接，导致多 workspace 场景把数据写进错误数据库。改成 dict 键控。
_local = threading.local()
_registry_lock = threading.Lock()
_global_conns: dict[tuple[int, str], sqlite3.Connection] = {}


def get_connection(db_path: Path) -> sqlite3.Connection:
    """
    取当前线程对 db_path 的 connection。没有就建一个。
    每个 (线程, db_path) 独立 connection，避免：
        (a) SQLite 跨线程共享报错（thread-local 部分）
        (b) 同线程访问多个仓库时复用错误连接（dict 键控部分）
    """
    key = str(db_path)
    if not hasattr(_local, "conns"):
        _local.conns = {}
    conn = _local.conns.get(key)
    if conn is None:
        conn = sqlite3.connect(
            str(db_path),
            timeout=10.0,  # 写冲突时最多等 10 秒
            isolation_level=None,  # 自动提交模式
            factory=TraceConnection,
        )
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")  # WAL 模式对并发友好
        conn.row_factory = sqlite3.Row  # SELECT 结果像 dict 一样取
        _local.conns[key] = conn
        with _registry_lock:
            _global_conns[(threading.get_ident(), key)] = conn
    return conn


def init_db(db_path: Path) -> None:
    """首次建库：执行 schema + 塞预置 agent 数据。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    # 塞预置 agent（INSERT OR IGNORE 避免重启时重复插入）
    conn.executemany(
        "INSERT OR IGNORE INTO agents(name, category, match_rules, display_name, color) "
        "VALUES (?, ?, ?, ?, ?)",
        PRESET_AGENTS,
    )
    # 旧版本曾用带空格的内部 key `kimi code`，会导致检测和 CSS class 都不一致。
    conn.execute(
        "UPDATE commits SET author_agent = 'kimi' WHERE author_agent = 'kimi code'"
    )
    conn.execute("DELETE FROM agents WHERE name = 'kimi code'")


def _close_one(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass


def close_connections(db_path: Path | None = None) -> None:
    """Close cached SQLite connections for the current thread."""
    conns = getattr(_local, "conns", None)
    if not conns:
        return
    tid = threading.get_ident()
    keys = [str(db_path)] if db_path is not None else list(conns.keys())
    for key in keys:
        conn = conns.pop(key, None)
        if conn is not None:
            _close_one(conn)
            with _registry_lock:
                _global_conns.pop((tid, key), None)


def close_all_connections() -> None:
    """Close every cached SQLite connection across all threads."""
    with _registry_lock:
        entries = list(_global_conns.items())
        _global_conns.clear()
    for _, conn in entries:
        _close_one(conn)
    if hasattr(_local, "conns"):
        _local.conns.clear()


atexit.register(close_all_connections)
