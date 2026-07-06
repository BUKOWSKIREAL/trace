"""
全局状态持久化（守护进程外的轻量状态）
==========================================
跨守护进程实例的"上次工作区"等记忆。**和 .trace/config.json 区分**：
那个是某个仓库内的配置；这里是用户级、系统级的偏好。

存储位置：
    macOS:   ~/Library/Application Support/Trace/state.json
    Linux:   ~/.config/trace/state.json
    Windows: %APPDATA%\\Trace\\state.json （未测试）

# 人工编写
"""
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("trace.state")

_APP_NAME = "Trace"


def state_dir() -> Path:
    """跨平台返回应用状态目录（按各 OS 习惯）。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / _APP_NAME
    # Linux / 其它：遵循 XDG
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / _APP_NAME.lower()


def _state_file() -> Path:
    return state_dir() / "state.json"


def _load() -> dict:
    p = _state_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("state.json 损坏，重置: %s", e)
        return {}


def _save(data: dict) -> None:
    p = _state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_last_workspace() -> Path | None:
    """
    取上次使用的工作区。当且仅当路径仍然是真实目录时才返回；
    否则视作"没记忆"——避免用户挪走目录后程序卡死在不存在的路径上。
    """
    raw = _load().get("last_workspace")
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_dir():
        logger.info("上次工作区已不存在，忽略记忆: %s", p)
        return None
    return p.resolve()


def save_last_workspace(workspace: Path) -> None:
    """把这次的工作区记下来，下次启动直接用。"""
    data = _load()
    data["last_workspace"] = str(workspace.resolve())
    _save(data)
    logger.debug("已记录上次工作区: %s", workspace)
