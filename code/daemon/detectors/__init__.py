"""
Detectors 注册表
====================
聚合所有类别（CLI/GUI/Web/Script）的检测器，提供统一入口 scan_active_agents()。

# 评审：加 1 秒 TTL 缓存——多个 watcher 工作线程并发调用时
# 不要每次都跑 psutil.process_iter（1000+ 进程时 ~50ms，浪费）
"""

import threading
import time
from pathlib import Path

from models.agent import AgentInstance

from daemon.detectors.cli_detector import scan_cli_agents, scan_global_cli_agents
from daemon.detectors.gui_detector import scan_gui_agents
from daemon.detectors.script_detector import scan_local_ai_scripts

# === 缓存层 ===
_CACHE_TTL = 3.0  # 3 秒内重复调用走缓存，降低 psutil 全量枚举频率
_CACHE_MAX_ENTRIES = 64
_cache_lock = threading.Lock()
_cache: dict[Path, tuple[float, list[AgentInstance]]] = {}
_global_cache: tuple[float, list[AgentInstance]] | None = None


def scan_active_agents(
    workspace: Path, force_refresh: bool = False
) -> list[AgentInstance]:
    """
    聚合 CLI、GUI 和本机脚本检测器的结果。

    缓存策略：
        同一 workspace 在 _CACHE_TTL 秒内的重复调用共享结果。
        force_refresh=True 时强制刷新（比如菜单栏手动点"立刻扫描"）。

    线程安全：缓存读写都在锁内；真实扫描发生在锁外（不阻塞其他线程）。
    """
    now = time.time()
    workspace = workspace.expanduser().resolve(strict=False)

    # 先看缓存
    if not force_refresh:
        with _cache_lock:
            cached = _cache.get(workspace)
            if cached is not None and (now - cached[0]) < _CACHE_TTL:
                return cached[1]

    # 真实扫描（不在锁内，避免阻塞）
    result: list[AgentInstance] = []
    # 类别 1：CLI
    result.extend(scan_cli_agents(workspace))
    # 类别 2：GUI 应用
    result.extend(scan_gui_agents(workspace))
    # 类别 3：网页 AI — 本期不做
    # 类别 4：本机 AI 脚本
    result.extend(scan_local_ai_scripts(workspace))

    # 回填缓存
    with _cache_lock:
        _cache[workspace] = (now, result)
        if len(_cache) > _CACHE_MAX_ENTRIES:
            oldest = min(_cache.items(), key=lambda item: item[1][0])[0]
            _cache.pop(oldest, None)

    return result


def scan_global_active_agents() -> list[AgentInstance]:
    """Scan known active agents without workspace cwd filtering."""
    global _global_cache
    now = time.time()
    with _cache_lock:
        if _global_cache is not None and (now - _global_cache[0]) < _CACHE_TTL:
            return _global_cache[1]

    result = scan_global_cli_agents()

    with _cache_lock:
        _global_cache = (now, result)
    return result
