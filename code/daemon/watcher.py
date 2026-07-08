"""
Watchdog 文件监听
======================
监听工作目录的文件变化，做噪声防护后送给 batcher。

噪声防线（按顺序应用）：
    1. 路径忽略（.git / .trace / __pycache__ / node_modules / Office 临时文件）
    2. 恢复/回退 sentinel 静默窗口（跨进程自身写入排除）
    3. 同路径 dedup（500ms 内同一文件多次事件视为一次，且定期 GC 旧条目）
    4. 文件稳定性等待（异步线程等文件大小稳定后再读）
    5. 线程池限流（最多 8 个并发处理，避免 git clone 时的"线程爆炸"）

# coding:Claude 4.7 + gpt5.5 code review
# 修正：
#   - IGNORE_PARTS 扩展，加入 .venv / .pytest_cache
#   - PathDeduper 加锁——AI 原版用了 dict 但没加锁，多线程不安全
#   - on_moved 处理 Office .docx 临时文件 rename 模式
#   - PathDeduper 加 GC（last_seen 长期运行会无限增长，5 分钟未见即清理）
#   - 用 ThreadPoolExecutor 替换裸 Thread.start()——避免 git clone 时
#     几百个事件各起线程冲击系统
#   - start_watcher 返回 (observer, handler)，main 退出时 handler.shutdown()
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from models.agent import AgentAttribution
from utils.ignore import should_ignore
from utils.restore_sentinel import active_restore_window
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from daemon.attribution_resolver import resolve_attribution
from daemon.detectors.transcript_detector import find_transcript_attribution

logger = logging.getLogger("trace.watcher")


# === 噪声防线 1：路径忽略（评审 #2：抽到 utils/ignore.py 共享给 repository）===


# === 噪声防线 2：同路径 dedup ===
class PathDeduper:
    """
    500ms 内同一 (路径, 事件类型) 的多次事件视为一次。

    # gpt5.5修正：last_seen 字典守护进程长期运行会无限增长，
    # 加增量 GC（每 60 秒清一次 5 分钟前的旧条目）
    # 人工修正（E2E 冒烟踩坑）：原版只按 path 去重，FSEvents 会把
    # "write→delete" 合并成一个 NativeEvent，watchdog 拆为 modify+delete
    # 两条相邻事件——按路径去重时 delete 被前一秒的 modify 吃掉，
    # 导致删除从未进 batcher。改成 (path, kind) 联合 key 解决：
    # modify 和 delete 各走各的窗口。
    """

    DEDUP_WINDOW = 0.5
    GC_INTERVAL = 60.0
    MAX_AGE = 300.0  # 5 分钟未见过 → 直接清理

    def __init__(self):
        self.last_seen: dict[tuple[Path, str], float] = {}
        self.lock = threading.Lock()
        self._last_gc = time.time()

    def should_process(self, path: Path, kind: str = "write") -> bool:
        """
        kind 取值：
            "write"  → on_modified / on_created / on_moved 共享一个窗口
            "delete" → on_deleted 独立窗口
        """
        now = time.time()
        key = (path, kind)
        with self.lock:
            # 顺便做个增量 GC
            if now - self._last_gc > self.GC_INTERVAL:
                self._gc(now)
                self._last_gc = now
            last = self.last_seen.get(key, 0.0)
            self.last_seen[key] = now
            return (now - last) >= self.DEDUP_WINDOW

    def _gc(self, now: float) -> None:
        """删除 MAX_AGE 之前的条目（必须在持锁状态下调用）。"""
        cutoff = now - self.MAX_AGE
        stale = [k for k, t in self.last_seen.items() if t < cutoff]
        for k in stale:
            del self.last_seen[k]
        if stale:
            logger.debug("PathDeduper GC: 清理了 %d 个旧条目", len(stale))


# === 噪声防线 3：文件稳定性等待 ===
def wait_for_stable(path: Path, max_wait: float = 2.0, poll: float = 0.1):
    """等文件大小连续不变 → 认为写完。文件不见了返回 None。"""
    last = -1
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            cur = path.stat().st_size
        except FileNotFoundError:
            return None
        if cur == last:
            return cur
        last = cur
        time.sleep(poll)
    return last


# === 主 Handler ===
class TraceHandler(FileSystemEventHandler):
    """把噪声防护后的事件喂给 batcher。归属在这里做（简版：扫 agent → 取一个 → 归它）。"""

    MAX_WORKERS = 8  # 线程池上限：git clone / npm install 时不让线程爆炸

    def __init__(
        self, workspace: Path, batcher, *, ignore_patterns: list[str] | None = None
    ):
        self.workspace = workspace
        self.batcher = batcher
        self.ignore_patterns = list(ignore_patterns or [])
        self.activity_recorder: Any | None = None
        self.trace_activity: Any | None = None
        self.deduper = PathDeduper()
        # 用线程池限流：原版裸 Thread.start() 在 git clone 时会同时起
        # 几百个线程，对系统资源冲击大
        self._executor = ThreadPoolExecutor(
            max_workers=self.MAX_WORKERS,
            thread_name_prefix="trace-handler",
        )
        # 可由 UI/配置设置的两个状态：
        # paused=True 时，dispatch 直接 return，事件不进 batcher
        # override_agent 不为 None 时，_attribute 强制返回该 agent
        self.paused: bool = False
        self.override_agent: str | None = None

    def _dispatch(self, raw_path: str) -> None:
        # Task 4.1：暂停时早退
        if self.paused:
            return
        p = Path(raw_path)
        if should_ignore(p, self.ignore_patterns):
            return
        if active_restore_window(self.workspace) is not None:
            logger.debug("恢复窗口内忽略自写入事件: %s", p)
            return
        if not self.deduper.should_process(p, kind="write"):
            return
        # 投递到线程池而非裸 Thread.start()：
        # 超过 MAX_WORKERS 时事件在队列里等，不会同时跑几百个线程
        self._executor.submit(self._after_stable, p)

    def _dispatch_delete(self, raw_path: str) -> None:
        """
        删除事件专用分派路径（评审 #2 + E2E 冒烟修）：
        - 不调 wait_for_stable（文件已经没了，等不到）
        - 走 should_ignore + deduper("delete")——delete 用独立窗口，
          不会被相邻的 modify 事件吃掉
        - 仍投到线程池：归属决策本身要跑 psutil，别阻塞 watchdog 主线程
        """
        # Task 4.1：暂停时早退
        if self.paused:
            return
        p = Path(raw_path)
        if should_ignore(p, self.ignore_patterns):
            return
        if active_restore_window(self.workspace) is not None:
            logger.debug("恢复窗口内忽略自删除事件: %s", p)
            return
        if not self.deduper.should_process(p, kind="delete"):
            return
        self._executor.submit(self._handle_delete, p)

    def _after_stable(self, p: Path) -> None:
        try:
            size = wait_for_stable(p)
            if size is None:
                return
            event_time = time.time()
            attribution = self._attribute(p, event_time=event_time)
            self.batcher.add_change(p, event_time, attribution, kind="upsert")
        except Exception:
            # 线程池 future 异常如果不显式 catch 会被吞，所以这里兜底
            logger.exception("处理文件事件失败: %s", p)

    def _handle_delete(self, p: Path) -> None:
        """on_deleted 走这里：仅做归属 + 投递 delete change。"""
        try:
            event_time = time.time()
            attribution = self._attribute(p, event_time=event_time)
            self.batcher.add_change(p, event_time, attribution, kind="delete")
        except Exception:
            logger.exception("处理删除事件失败: %s", p)

    def _attribute(
        self, file_path: Path, *, event_time: float | None = None
    ) -> AgentAttribution:
        """根据恢复窗口、手动覆盖、MCP 活动和进程证据判断本次变更来源。

        override_agent 设定后作为手动覆盖证据参与归因；Repository 恢复
        自身写入的 sentinel 优先级更高，避免恢复操作被误记成人工修改。
        """
        restore_window = active_restore_window(self.workspace)
        if restore_window is not None:
            return AgentAttribution(
                agent="human",
                confidence=1.0,
                detection_method=str(
                    restore_window.get("detection_method") or "restore"
                ),
            )

        # 用户手动覆盖优先级最高，但低于 Repository 恢复自身写入 sentinel。
        transcript_scan = getattr(
            self, "_transcript_for_test", find_transcript_attribution
        )
        scan_workspace = getattr(self, "_scan_for_test", None)
        scan_global = getattr(self, "_scan_global_for_test", None)
        return resolve_attribution(
            self.workspace,
            file_path,
            event_time=event_time if event_time is not None else time.time(),
            override_agent=self.override_agent,
            trace_activity=getattr(self, "trace_activity", None),
            activity_recorder=self.activity_recorder,
            transcript_scan=transcript_scan,
            scan_workspace=scan_workspace,
            scan_global=scan_global,
        )

    def shutdown(self) -> None:
        """守护退出时调用，等线程池里所有任务跑完再走。"""
        self._executor.shutdown(wait=True)
        logger.info("Handler 线程池已关闭")

    # === watchdog 回调入口 ===
    def on_modified(self, event):
        if not event.is_directory:
            self._dispatch(str(event.src_path))

    def on_created(self, event):
        if not event.is_directory:
            self._dispatch(str(event.src_path))

    def on_moved(self, event):
        # Office 等 GUI 应用写 .docx 走的是"先写临时文件再 rename"
        # 必须接 on_moved 才能抓到这种保存；普通 mv 还必须把旧路径作为 delete
        # 投递，否则旧文件会永久残留在 manifest。
        if not event.is_directory:
            self._dispatch_delete(str(event.src_path))
            self._dispatch(str(event.dest_path))

    def on_deleted(self, event):
        # 评审 #2：删除事件接入，走 delete 专用分派
        if not event.is_directory:
            self._dispatch_delete(str(event.src_path))


def start_watcher(
    workspace: Path,
    batcher,
    *,
    ignore_patterns: list[str] | None = None,
) -> tuple[Any, TraceHandler]:
    """
    启动 watchdog 观察者，返回 (observer, handler)。

    main 在退出时需要：
        observer.stop(); observer.join()
        handler.shutdown()    # 让线程池里的任务跑完
    """
    handler = TraceHandler(
        workspace=workspace,
        batcher=batcher,
        ignore_patterns=ignore_patterns,
    )
    observer = Observer()
    observer.schedule(handler, str(workspace), recursive=True)
    observer.start()
    logger.info("Watcher 已启动，监听: %s", workspace)
    return observer, handler
