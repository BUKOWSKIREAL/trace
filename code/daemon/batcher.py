"""
CommitBatcher — 防抖合并器
============================
按 (agent, idle window) 聚合文件变化为一次 commit。

# AI 辅助生成（Claude 4.7 协助）
# 修正：
#   - 第 56-58 行：force_flush_all 里取 keys 用 list() 复制，避免边迭代边改
#   - 第 78-83 行：_flush_agent 加 try/except，commit 失败不影响其他 agent
#   - 第 38 行：把 IDLE_WINDOW 设为 2.0 秒，与操作台展示一致
# 重构（评审 #2）：
#   - Change 移到 models/change.py + 加 kind="upsert"|"delete" 字段
#   - add_change 接受 kind 关键字参数；watcher 的 on_deleted 走 kind="delete"
#   - _flush_agent 把 list[Change] 整体传给 repo.commit（而不是仅 list[Path]）
"""

import logging
import threading
from pathlib import Path

from daemon.ipc import emit
from models.agent import AgentAttribution
from models.change import Change

logger = logging.getLogger("trace.batcher")


class CommitBatcher:
    """
    每 agent 独立 timer 的防抖合并器。

    关键设计：单全局 timer 会导致 A 的提交被 B 的事件无限推迟，所以这里
    用 dict[agent] -> timer。新事件来时只 cancel 自己 agent 的 timer。
    """

    IDLE_WINDOW_SECONDS = 2.0  # 闲置 2 秒后 flush

    def __init__(self, repo):
        self.repo = repo
        self.pending: dict[str, list[Change]] = {}
        self.timers: dict[str, threading.Timer] = {}
        self.lock = threading.Lock()

    def add_change(
        self,
        file_path: Path,
        event_time: float,
        attribution: AgentAttribution,
        *,
        kind: str = "upsert",
    ) -> None:
        """
        收到一次文件变化事件，按 agent 入队 + 重置该 agent 的 timer。

        kind="upsert" 用于 on_modified / on_created / on_moved（评审 #2 默认）
        kind="delete" 用于 on_deleted——文件已不在磁盘上，commit 时只
            从 new_manifest 删除该 path，不写 blob。
        """
        agent = attribution.agent
        with self.lock:
            self.pending.setdefault(agent, []).append(
                Change(
                    file_path=file_path,
                    event_time=event_time,
                    attribution=attribution,
                    kind=kind,
                )
            )
            # 取消"自己"的 timer，不影响其他 agent
            old = self.timers.get(agent)
            if old is not None:
                old.cancel()
            t = threading.Timer(
                self.IDLE_WINDOW_SECONDS,
                lambda a=agent: self._flush_agent(a),
            )
            t.daemon = True
            self.timers[agent] = t
            t.start()
        logger.debug(
            "队列加入 [%s][%s]: %s (该 agent 待提交 %d 项)",
            agent,
            kind,
            file_path.name,
            len(self.pending[agent]),
        )

    def _flush_agent(self, agent: str) -> None:
        """把某 agent 的 pending 全部 commit 到 repo。"""
        with self.lock:
            changes = self.pending.pop(agent, [])
            self.timers.pop(agent, None)

        if not changes:
            return

        # 同一文件多次改 → 只取最后一次（含 kind）
        # 例如先 upsert 再 delete，留 delete；先 delete 再 upsert（罕见），留 upsert
        dedup: dict[Path, Change] = {}
        for c in changes:
            dedup[c.file_path] = c
        final_changes = list(dedup.values())

        # commit 失败不应让其他 agent 受影响
        try:
            commit_id = self.repo.commit(
                agent=agent,
                changes=final_changes,
                attribution=changes[-1].attribution,
            )
            if commit_id is None:
                logger.info(
                    "Flush [%s] 跳过：没有实际内容变化 (%d 个事件)",
                    agent,
                    len(final_changes),
                )
                return
            logger.info(
                "Flushed [%s] → commit #%d (%d 个变化)",
                agent,
                commit_id,
                len(final_changes),
            )
            attribution = changes[-1].attribution
            emit(
                "new_commit",
                commit_id=commit_id,
                agent=agent,
                ambiguous=bool(attribution.ambiguous),
                candidates=list(attribution.candidates),
            )
            if attribution.ambiguous:
                emit(
                    "ambiguous_commit",
                    commit_id=commit_id,
                    candidates=list(attribution.candidates),
                )
        except Exception as e:
            logger.error("Flush [%s] 失败: %s", agent, e)

    def force_flush_agent(self, agent: str) -> None:
        """立即 flush 某个 agent 的 pending（切换强制归属前调用）。"""
        with self.lock:
            timer = self.timers.pop(agent, None)
            if timer is not None:
                timer.cancel()
        self._flush_agent(agent)

    def force_flush_all(self) -> None:
        """守护退出时调用，把所有 pending 立刻落库。"""
        with self.lock:
            # list() 复制 keys 避免边迭代边改字典
            agents = list(self.pending.keys())
            # 取消所有还在跑的 timer
            for a in list(self.timers.keys()):
                self.timers[a].cancel()
        for a in agents:
            self._flush_agent(a)
