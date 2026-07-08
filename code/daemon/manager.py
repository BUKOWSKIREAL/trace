"""
DaemonManager — 守护进程生命周期管理
=========================================
封装 repo / batcher / observer / handler 四件套的 start / stop / restart。

设计动机：watchdog Observer 一旦 stop 就不能重启，必须创建新实例。
工作区切换需要 stop 旧的 + start 新的。
没这个抽象的话，生命周期逻辑会散落在入口和 TUI 各处，
而且容易漏掉关闭顺序（observer→handler→batcher）。

用法（main.py）：
    daemon = DaemonManager()
    daemon.start(workspace)
    # ... 跑菜单栏 ...
    daemon.stop()  # 退出时

用法（TUI 工作区切换）：
    self.daemon.restart(new_workspace)

"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from core.repository import Repository

from daemon.batcher import CommitBatcher
from daemon.config_runtime import RuntimeConfig
from daemon.trace_activity import TraceActivityStore
from daemon.watcher import start_watcher

if TYPE_CHECKING:
    from daemon.activity_recorder import AgentActivityRecorder

logger = logging.getLogger("trace.daemon.manager")


class DaemonManager:
    """守护进程组件的生命周期管理器。"""

    def __init__(self) -> None:
        self.workspace: Path | None = None
        self.repo: Repository | None = None
        self.config: RuntimeConfig | None = None
        self.batcher: CommitBatcher | None = None
        self.observer = None  # watchdog.observers.Observer
        self.handler = None  # TraceHandler
        self.recorder: AgentActivityRecorder | None = None
        self.trace_activity: TraceActivityStore | None = None

    # ---- 生命周期 ----

    def start(self, workspace: Path) -> None:
        """启动守护进程。幂等：已在跑的情况下先 stop 再 start。"""
        if self.observer is not None:
            logger.info("DaemonManager.start 检测到旧实例，先 stop")
            self.stop()

        self.workspace = workspace
        self.repo = Repository(workspace)
        self.repo.init_if_needed()
        self.config = RuntimeConfig(self.repo.config_path)
        self.config.ensure_defaults()

        reconcile_id = self.repo.reconcile_offline_changes(
            extra_ignore_patterns=self.config.ignore_patterns
        )
        if reconcile_id is not None:
            logger.info("离线变化已补偿为 commit #%d", reconcile_id)

        self.batcher = CommitBatcher(repo=self.repo)
        self.trace_activity = TraceActivityStore(workspace)
        self.observer, self.handler = start_watcher(
            workspace=workspace,
            batcher=self.batcher,
            ignore_patterns=self.config.ignore_patterns,
        )
        self.handler.trace_activity = self.trace_activity

        from daemon.activity_recorder import AgentActivityRecorder

        self.recorder = AgentActivityRecorder(
            workspace=workspace,
            high_precision_mode=self.config.high_precision_mode,
        )
        self.recorder.start()
        self.handler.activity_recorder = self.recorder

        if not self.config.tracking_enabled:
            self.handler.paused = True
            logger.info("tracking_enabled=false，启动时处于暂停状态")

        forced = self.config.forced_agent_override()
        if forced is not None:
            self.handler.override_agent = forced
            logger.info("从配置加载 forced_agent=%s", forced)

        logger.info("DaemonManager 启动，workspace=%s", workspace)

    def stop(self) -> None:
        """
        优雅关停（顺序很重要，评审 #3 已验证）：
          1. observer.stop / join：不再产生新 watchdog 事件
          2. handler.shutdown：等线程池里已派发的 _after_stable 跑完
          3. batcher.force_flush_all：把刚进来的 pending 全部落库

        start() 之前调用是 no-op。
        """
        if self.observer is None:
            return
        assert self.handler is not None
        assert self.batcher is not None

        logger.info("DaemonManager.stop: 停止文件监听...")
        self.observer.stop()
        self.observer.join(timeout=2.0)

        logger.info("DaemonManager.stop: 等待已派发的文件事件处理完成...")
        self.handler.shutdown()

        if self.recorder is not None:
            self.recorder.stop()
            self.recorder = None

        logger.info("DaemonManager.stop: flush 最后一批待提交...")
        self.batcher.force_flush_all()

        # 清空引用，让 GC 回收
        self.workspace = None
        self.repo = None
        self.config = None
        self.batcher = None
        self.observer = None
        self.handler = None
        self.trace_activity = None

    def restart(self, new_workspace: Path) -> None:
        """
        热切工作区：停旧的 + 启新的。
        watchdog Observer 不能被 stop 后重用，所以 restart 必然创建新实例。
        """
        logger.info("DaemonManager.restart: %s → %s", self.workspace, new_workspace)
        self.start(new_workspace)  # start() 自己处理 idempotent stop
