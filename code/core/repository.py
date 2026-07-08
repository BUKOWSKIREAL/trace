"""
仓库引擎：init / commit / log / checkout
==========================================
对接 storage.py（blob 字节存储）与 utils/db.py（SQLite 元数据）。
对外只暴露高层 API：init_if_needed / commit / log / checkout。

#   关键改动：
#     1. commit() 用 BEGIN IMMEDIATE 串行化，进事务后读 prev_manifest
#        防 lost-update（两个 agent 同时 flush 时读到相同 prev 会覆盖彼此）
#     2. commit() 接收 list[Change]（含 kind），先 hash 再开事务，
#        减小写锁占用时间
#     3. checkout_commit() 加"删除目标 manifest 里没有但当前工作目录
#        里还存在的文件"的步骤——这才是真正的"恢复到时间点"
#     4. _snapshot_current_state() 改为遍历工作目录 + 比对 HEAD manifest，
#        正确处理"曾被跟踪过但目前已删除"的文件
"""

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path

from models.agent import AgentAttribution
from models.change import Change
from utils.config import DEFAULT_CONFIG, save_config
from utils.db import get_connection, init_db
from utils.hasher import hash_file
from utils.ignore import IGNORE_PARTS, should_ignore
from utils.restore_sentinel import mark_restore_window

from core.storage import BlobStorage

logger = logging.getLogger("trace.repo")


class Repository:
    """一个工作目录对应一个 Repository。"""

    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()
        self.trace_dir = self.workspace / ".trace"
        self.db_path = self.trace_dir / "trace.db"
        self.objects_dir = self.trace_dir / "objects"
        self.config_path = self.trace_dir / "config.json"
        self.storage = BlobStorage(self.objects_dir)

    # ------- 初始化 -------

    def init_if_needed(self) -> None:
        """首次启动时创建 .trace/ 目录、数据库、默认配置。"""
        # # 人工修正（评审 #5）：first_time 必须在任何 mkdir 之前算出来。
        first_time = not self.trace_dir.exists()
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        (self.trace_dir / "logs").mkdir(exist_ok=True)
        self.storage.ensure_dir()
        init_db(self.db_path)
        if not self.config_path.exists():
            save_config(self.config_path, dict(DEFAULT_CONFIG))
        if first_time:
            logger.info("初始化新仓库: %s", self.trace_dir)

    # ------- manifest 工具 -------

    def _latest_commit_id(self) -> int | None:
        """取最近一次 commit 的 id（即 HEAD）。空仓库返回 None。"""
        conn = get_connection(self.db_path)
        row = conn.execute("SELECT MAX(id) AS mid FROM commits").fetchone()
        return row["mid"] if row and row["mid"] is not None else None

    def _load_manifest(self, commit_id: int | None) -> dict[str, str]:
        """读某 commit 的完整 manifest：{file_path: blob_hash}。"""
        if commit_id is None:
            return {}
        conn = get_connection(self.db_path)
        rows = conn.execute(
            "SELECT file_path, blob_hash FROM snapshots WHERE commit_id = ?",
            (commit_id,),
        ).fetchall()
        return {r["file_path"]: r["blob_hash"] for r in rows}

    def _commit_exists(self, commit_id: int) -> bool:
        """commit 是否存在（独立于其 manifest 是否为空）。"""
        conn = get_connection(self.db_path)
        row = conn.execute(
            "SELECT 1 FROM commits WHERE id = ?", (commit_id,)
        ).fetchone()
        return row is not None

    def _normalize_manifest(self, manifest: dict[str, str]) -> dict[str, str]:
        """Manifest keys are stored with POSIX separators for cross-platform UI calls."""
        return {path.replace("\\", "/"): blob for path, blob in manifest.items()}

    def _workspace_file(self, file_path: str) -> tuple[str, Path]:
        """Normalize a user/IPC file path to (manifest_key, absolute_path)."""
        normalized_input = file_path.replace("\\", "/")
        abs_path = (self.workspace / normalized_input).resolve()
        rel = abs_path.relative_to(self.workspace).as_posix()
        return rel, abs_path

    def _write_manifest_commit(
        self,
        *,
        agent: str,
        manifest: dict[str, str],
        attribution: AgentAttribution,
        summary: str,
    ) -> int | None:
        """Insert a full-manifest commit without re-hashing files already in storage."""
        normalized_manifest = self._normalize_manifest(manifest)
        now_iso = dt.datetime.now().isoformat(timespec="seconds")
        conn = get_connection(self.db_path)
        conn.execute("BEGIN IMMEDIATE")
        try:
            prev_cid = self._latest_commit_id()
            prev_manifest = self._normalize_manifest(self._load_manifest(prev_cid))
            if normalized_manifest == prev_manifest:
                conn.execute("COMMIT")
                logger.debug(
                    "manifest commit 跳过：manifest 未变化 (agent=%s, method=%s)",
                    agent,
                    attribution.detection_method,
                )
                return None

            cursor = conn.execute(
                "INSERT INTO commits(time, author_agent, detection_method, "
                "confidence, candidates, summary) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    now_iso,
                    agent,
                    attribution.detection_method,
                    attribution.confidence,
                    json.dumps(attribution.candidates, ensure_ascii=False),
                    summary,
                ),
            )
            commit_id = cursor.lastrowid
            assert commit_id is not None, "INSERT 应当返回有效的 rowid"

            if normalized_manifest:
                conn.executemany(
                    "INSERT INTO snapshots(commit_id, file_path, blob_hash) "
                    "VALUES (?, ?, ?)",
                    [(commit_id, p, h) for p, h in sorted(normalized_manifest.items())],
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception("manifest commit 失败，已回滚")
            raise

        logger.info(
            "Commit #%d 已创建: agent=%s, method=%s, manifest=%d 文件",
            commit_id,
            agent,
            attribution.detection_method,
            len(normalized_manifest),
        )
        return commit_id

    # ------- 写入 -------

    def commit(
        self,
        agent: str,
        changes: list[Change],
        attribution: AgentAttribution | None = None,
        *,
        summary: str | None = None,
    ) -> int | None:
        """
        以 prev_manifest（当前 HEAD）为基准，应用一批 changes，写出新 commit。

        参数：
            agent: 归属 agent 名（'claude' / 'codex' / 'human' / ...）
            changes: 本批待提交的 Change 列表（kind="upsert"|"delete"）
            attribution: 归属决策细节；缺省用 confidence=1.0

        实现要点：
            1. **先 hash 再开事务**——put_file 涉及磁盘 I/O 慢，
               在 BEGIN IMMEDIATE 之前完成；事务内只做 SQLite 操作
            2. **BEGIN IMMEDIATE**——SQLite 写锁串行化，防 lost-update：
               两个 agent 同时 flush 时，谁先抢到锁谁先看到 prev_manifest，
               另一方阻塞到第一个 COMMIT 后再开始，能看到刚写的新 commit
            3. **manifest 全量写入**——new_manifest 是 prev_manifest 应用本批
               changes 后的结果，整体写到 snapshots 表，让每个 commit 自包含
        """
        if attribution is None:
            attribution = AgentAttribution(agent=agent, confidence=1.0)

        # === 锁外准备（put_file 慢，不能持锁）===
        # 每条 change 解析成 (rel_path, kind, blob_hash)
        # blob_hash 对 delete 为 None；对 upsert 但文件已不在为 None（跳过）
        resolved: list[tuple[str, str, str | None]] = []
        for c in changes:
            # # 评审 #2 边界：workspace 在 __init__ 里 resolve 过，但 watcher 传进来的
            # # 路径可能含 macOS /var → /private/var 类软链，未 resolve 时 relative_to
            # # 会抛 ValueError 当成"工作目录外"误吞。先 resolve 再算 rel。
            try:
                abs_p = c.file_path.resolve()
                rel = abs_p.relative_to(self.workspace).as_posix()
            except ValueError:
                logger.warning("commit 收到工作目录外的路径，跳过: %s", c.file_path)
                continue

            if c.kind == "delete":
                resolved.append((rel, "delete", None))
            elif c.kind == "upsert":
                if not c.file_path.exists():
                    # upsert 事件但文件已不在（被另一个事件抢先删了）
                    # 跳过；对应的 on_deleted 事件会处理删除
                    logger.debug("upsert 时文件已不存在，跳过: %s", c.file_path)
                    continue
                sha = self.storage.put_file(c.file_path)
                resolved.append((rel, "upsert", sha))
            else:
                logger.warning("未知 Change.kind=%r，跳过: %s", c.kind, c.file_path)

        now_iso = dt.datetime.now().isoformat(timespec="seconds")
        commit_summary = summary or f"{len(resolved)} 个变化 by {agent}"

        # === 写事务（BEGIN IMMEDIATE 串行化）===
        conn = get_connection(self.db_path)
        # BEGIN IMMEDIATE 立刻拿写锁；其他写者阻塞到我 COMMIT
        # 这样 prev_manifest 读出来就是最新的，本批 changes 应用上去不会丢
        conn.execute("BEGIN IMMEDIATE")
        try:
            prev_cid = self._latest_commit_id()
            prev_manifest = self._load_manifest(prev_cid)
            new_manifest = dict(prev_manifest)

            for rel, kind, sha in resolved:
                if kind == "upsert":
                    new_manifest[rel] = sha  # type: ignore[assignment]
                elif kind == "delete":
                    new_manifest.pop(rel, None)

            if new_manifest == prev_manifest:
                conn.execute("COMMIT")
                logger.debug(
                    "commit 跳过：manifest 未变化 (agent=%s, resolved=%d)",
                    agent,
                    len(resolved),
                )
                return None

            cursor = conn.execute(
                "INSERT INTO commits(time, author_agent, detection_method, "
                "confidence, candidates, summary) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    now_iso,
                    agent,
                    attribution.detection_method,
                    attribution.confidence,
                    json.dumps(attribution.candidates, ensure_ascii=False),
                    commit_summary,
                ),
            )
            commit_id = cursor.lastrowid
            assert commit_id is not None, "INSERT 应当返回有效的 rowid"

            if new_manifest:
                conn.executemany(
                    "INSERT INTO snapshots(commit_id, file_path, blob_hash) "
                    "VALUES (?, ?, ?)",
                    [(commit_id, p, h) for p, h in new_manifest.items()],
                )
            # new_manifest 为空也是合法状态：表示"这一时刻工作目录是空的"
            # checkout 此 commit 会把所有曾跟踪文件删掉

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception("commit 失败，已回滚")
            raise

        logger.info(
            "Commit #%d 已创建: agent=%s, manifest=%d 文件, 本批 %d 变化, conf=%.2f",
            commit_id,
            agent,
            len(new_manifest),
            len(resolved),
            attribution.confidence,
        )
        return commit_id

    # ------- 查询 -------

    def list_commits(self, limit: int = 50) -> list[dict]:
        """读最近 N 条 commit（按时间倒序）。"""
        conn = get_connection(self.db_path)
        rows = conn.execute(
            "SELECT id, time, author_agent, detection_method, confidence, candidates, summary "
            "FROM commits ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        commits = []
        for row in rows:
            item = dict(row)
            try:
                item["candidates"] = json.loads(item.get("candidates") or "[]")
            except json.JSONDecodeError:
                item["candidates"] = []
            commits.append(item)
        return commits

    def get_manifest(self, commit_id: int) -> list[dict]:
        """返回某次 commit 的完整文件清单 [{file_path, blob_hash}, ...]。"""
        conn = get_connection(self.db_path)
        rows = conn.execute(
            "SELECT file_path, blob_hash FROM snapshots WHERE commit_id = ?",
            (commit_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_prev_commit_id(self, commit_id: int) -> int | None:
        """返回给定 commit 之前最近的一次 commit id；不存在则 None。"""
        conn = get_connection(self.db_path)
        row = conn.execute(
            "SELECT id FROM commits WHERE id < ? ORDER BY id DESC LIMIT 1",
            (commit_id,),
        ).fetchone()
        return row["id"] if row is not None else None

    def list_agents(self) -> list[dict]:
        """每个 agent 的注册信息 + commit 统计（按 commit 数降序）。"""
        conn = get_connection(self.db_path)
        rows = conn.execute(
            """
            SELECT a.name, a.category, a.display_name, a.color,
                   COALESCE(stats.commit_count, 0) AS commit_count,
                   stats.last_time
            FROM agents a
            LEFT JOIN (
                SELECT author_agent, COUNT(*) AS commit_count, MAX(time) AS last_time
                FROM commits GROUP BY author_agent
            ) stats ON stats.author_agent = a.name
            ORDER BY commit_count DESC, a.name ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def workspace_summary(self) -> dict:
        """当前工作区概览：路径、db、commit/snapshot/agent 计数。"""
        conn = get_connection(self.db_path)
        commit_count = conn.execute("SELECT COUNT(*) AS n FROM commits").fetchone()["n"]
        snapshot_count = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()[
            "n"
        ]
        agent_count = conn.execute("SELECT COUNT(*) AS n FROM agents").fetchone()["n"]
        return {
            "workspace": str(self.workspace),
            "db_path": str(self.db_path),
            "commit_count": commit_count,
            "snapshot_count": snapshot_count,
            "agent_count": agent_count,
        }

    def get_config(self) -> dict:
        """Return merged workspace config."""
        from utils.config import load_config

        return load_config(self.config_path)

    def _disk_manifest(
        self, extra_ignore_patterns: list[str] | None = None
    ) -> dict[str, str]:
        """Build a manifest from the current workspace on disk."""
        manifest: dict[str, str] = {}
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [d for d in dirs if d not in IGNORE_PARTS]
            for filename in files:
                path = Path(root) / filename
                if should_ignore(path, extra_ignore_patterns):
                    continue
                try:
                    rel = path.relative_to(self.workspace).as_posix()
                except ValueError:
                    continue
                manifest[rel] = hash_file(path)
        return manifest

    def reconcile_offline_changes(
        self, *, extra_ignore_patterns: list[str] | None = None
    ) -> int | None:
        """Compensate for file changes made while the daemon was offline."""
        head = self._latest_commit_id()
        if head is None:
            return None

        head_manifest = self._load_manifest(head)
        disk_manifest = self._disk_manifest(extra_ignore_patterns)
        if head_manifest == disk_manifest:
            return None

        now = time.time()
        attr = AgentAttribution(
            agent="unknown",
            confidence=0.4,
            detection_method="offline_reconcile",
        )
        changes: list[Change] = []
        all_paths = set(head_manifest) | set(disk_manifest)
        for rel in sorted(all_paths):
            abs_path = self.workspace / rel
            head_hash = head_manifest.get(rel)
            disk_hash = disk_manifest.get(rel)
            if head_hash == disk_hash:
                continue
            kind = "upsert" if disk_hash is not None else "delete"
            changes.append(
                Change(
                    file_path=abs_path,
                    event_time=now,
                    attribution=attr,
                    kind=kind,
                )
            )

        if not changes:
            return None

        return self.commit(
            agent="unknown",
            changes=changes,
            attribution=attr,
            summary=f"离线变化补偿 ({len(changes)} 个文件)",
        )

    def reassign_commit(self, commit_id: int, new_agent: str) -> None:
        """Update commit metadata without rewriting snapshots."""
        if not self._commit_exists(commit_id):
            raise ValueError(f"commit #{commit_id} 不存在")
        if not new_agent:
            raise ValueError("new_agent 不能为空")

        conn = get_connection(self.db_path)
        conn.execute(
            "UPDATE commits SET author_agent=?, detection_method=?, "
            "confidence=?, candidates=? WHERE id=?",
            (
                new_agent,
                "manual_reassign",
                1.0,
                json.dumps([], ensure_ascii=False),
                commit_id,
            ),
        )
        conn.commit()
        logger.info("commit #%d 归属已修正为 %s", commit_id, new_agent)

    def compute_manifest_without_agent(self, agent: str) -> dict[str, str]:
        """Replay commits while skipping file-level changes from one agent."""
        conn = get_connection(self.db_path)
        rows = conn.execute(
            "SELECT id, author_agent FROM commits ORDER BY id ASC"
        ).fetchall()

        effective: dict[str, str] = {}
        prev: dict[str, str] = {}
        for row in rows:
            manifest = self._load_manifest(int(row["id"]))
            author = str(row["author_agent"])
            for path in set(prev) | set(manifest):
                if prev.get(path) != manifest.get(path):
                    if author != agent:
                        if manifest.get(path) is None:
                            effective.pop(path, None)
                        else:
                            effective[path] = manifest[path]
            prev = manifest
        return effective

    def preview_revert_agent(self, agent: str) -> dict[str, object]:
        """Dry-run for selective agent revert."""
        head = self._latest_commit_id()
        if head is None:
            return {"changed_paths": [], "target_manifest": {}}

        head_manifest = self._load_manifest(head)
        target_manifest = self.compute_manifest_without_agent(agent)
        changed = sorted(
            path
            for path in set(head_manifest) | set(target_manifest)
            if head_manifest.get(path) != target_manifest.get(path)
        )
        return {
            "changed_paths": changed,
            "target_manifest": target_manifest,
            "head_commit_id": head,
        }

    def revert_agent(self, agent: str, *, backup_current: bool = True) -> int:
        """Revert all file-level contributions from one agent."""
        preview = self.preview_revert_agent(agent)
        target_manifest = self._normalize_manifest(preview["target_manifest"])
        head = self._latest_commit_id()
        if head is None:
            raise ValueError("空仓库无法撤销 agent 变更")

        backup_id: int | None = None
        if backup_current:
            backup_id = self._snapshot_current_state(
                summary=f"撤销 {agent} 前的自动备份",
                detection_method="pre_revert_backup",
            )
            if backup_id is not None:
                logger.info("已备份当前状态到 commit #%d", backup_id)

        mark_restore_window(
            self.workspace, "revert_agent", detection_method="revert_agent"
        )

        head_manifest = self._normalize_manifest(self._load_manifest(head))
        for rel, sha in target_manifest.items():
            dest = self.workspace / rel
            current = head_manifest.get(rel)
            if current == sha:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.storage.get(sha))

        conn = get_connection(self.db_path)
        rows = conn.execute("SELECT DISTINCT file_path FROM snapshots").fetchall()
        all_tracked = {str(r["file_path"]).replace("\\", "/") for r in rows}
        for rel in sorted(all_tracked - set(target_manifest.keys())):
            path = self.workspace / rel
            if path.exists() and path.is_file():
                path.unlink()

        mark_restore_window(
            self.workspace, "revert_agent", detection_method="revert_agent"
        )
        revert_commit_id = self._write_manifest_commit(
            agent="human",
            manifest=target_manifest,
            attribution=AgentAttribution(
                agent="human",
                confidence=1.0,
                detection_method="revert_agent",
            ),
            summary=f"撤销 agent {agent} 的全部变更",
        )
        mark_restore_window(
            self.workspace, "revert_agent", detection_method="revert_agent"
        )
        if revert_commit_id is None:
            raise RuntimeError("撤销后未能写入新的 manifest commit")
        logger.info(
            "已撤销 agent %s，生成 commit #%d（备份=%s）",
            agent,
            revert_commit_id,
            backup_id,
        )
        return revert_commit_id

    # ------- 恢复（评审 #2：真正的"恢复到时间点"）-------

    def checkout_commit(
        self,
        commit_id: int,
        target_dir: Path | None = None,
        *,
        backup_current: bool = True,
    ) -> int | None:
        """
        把工作目录恢复为某 commit 时刻的完整状态。

        语义（评审 #2 升级）：
            真正的"恢复到时间点"——对目标 manifest 中的文件写回 blob，
            对"HEAD manifest 有但目标 manifest 没有"的文件执行删除。
            原版只写不删，会留下目标 commit 时还不存在的文件。

        backup_current=True 且 target_dir == workspace 时，先把当前
        工作目录做一次 'human' commit 入库（包含 upsert 和 delete），
        返回备份 commit 的 id。
        """
        if target_dir is None:
            target_dir = self.workspace
        else:
            target_dir = target_dir.expanduser().resolve(strict=False)
        is_workspace_checkout = target_dir == self.workspace

        # # 评审 #2 D1：先确认 commit 存在，独立于其 manifest 是否为空
        # # 原版用 "SELECT * FROM snapshots WHERE commit_id=? + raise if empty"
        # # 会把合法的"空 manifest commit"误判成"不存在"
        if not self._commit_exists(commit_id):
            raise ValueError(f"commit #{commit_id} 不存在")

        backup_id: int | None = None
        if backup_current and target_dir == self.workspace:
            backup_id = self._snapshot_current_state(
                summary=f"checkout #{commit_id} 前的自动备份",
                detection_method="backup",
            )
            if backup_id is not None:
                logger.info("已备份当前状态到 commit #%d", backup_id)

        target_manifest = self._normalize_manifest(self._load_manifest(commit_id))

        if is_workspace_checkout:
            mark_restore_window(self.workspace, "checkout", detection_method="checkout")

        # 1. 写目标 manifest 里内容确实变化的文件。
        written_count = 0
        skipped_count = 0
        for rel, sha in target_manifest.items():
            dest = target_dir / rel
            if dest.exists() and dest.is_file():
                try:
                    if hash_file(dest) == sha:
                        skipped_count += 1
                        continue
                except OSError:
                    # 文件可能被并发改动/删除；按需要重写即可。
                    pass
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.storage.get(sha))
            written_count += 1
            if is_workspace_checkout and written_count % 50 == 0:
                mark_restore_window(
                    self.workspace, "checkout", detection_method="checkout"
                )

        # 2. 删除"历史上曾被跟踪过 ∧ 目标 manifest 没有 ∧ 当前磁盘上还在"的文件。
        #    评审 #2 + 回归测试踩坑：原本想用 prev_manifest（HEAD）作为候选集，
        #    但 checkout(... backup_current=False) 后 HEAD 不会推进、HEAD 不等于
        #    磁盘真实状态，到下一次 checkout 时就漏删。改用"历史曾跟踪过的所有
        #    路径"做候选，类似 git checkout 的行为：不动从未被跟踪的用户文件，
        #    只清理曾被仓库认领过的。
        conn = get_connection(self.db_path)
        rows = conn.execute("SELECT DISTINCT file_path FROM snapshots").fetchall()
        all_tracked = {str(r["file_path"]).replace("\\", "/") for r in rows}
        to_delete = all_tracked - set(target_manifest.keys())
        deleted_count = 0
        for rel in to_delete:
            p = target_dir / rel
            if p.exists() and p.is_file():
                p.unlink()
                deleted_count += 1
                if is_workspace_checkout and deleted_count % 50 == 0:
                    mark_restore_window(
                        self.workspace, "checkout", detection_method="checkout"
                    )
                # 顺手清空目录（如果该目录因此变空）
                try:
                    p.parent.rmdir()  # 非空会抛 OSError，忽略
                except OSError:
                    pass

        if is_workspace_checkout:
            mark_restore_window(self.workspace, "checkout", detection_method="checkout")
            self._write_manifest_commit(
                agent="human",
                manifest=target_manifest,
                attribution=AgentAttribution(
                    agent="human",
                    confidence=1.0,
                    detection_method="checkout",
                ),
                summary=f"checkout 到 commit #{commit_id}",
            )
            mark_restore_window(self.workspace, "checkout", detection_method="checkout")

        logger.info(
            "已恢复 commit #%d: 写 %d 文件, 跳过 %d 文件, 删 %d 文件 (target=%s)",
            commit_id,
            written_count,
            skipped_count,
            deleted_count,
            target_dir,
        )
        return backup_id

    def _snapshot_current_state(
        self,
        summary: str = "自动备份",
        *,
        detection_method: str = "fallback",
        extra_ignore_patterns: list[str] | None = None,
    ) -> int | None:
        """
        把当前工作目录做一次 'human' commit。

        # 评审 #2 D2：必须考虑"HEAD 有 + 当前没了"的文件，否则备份
        # commit 长得和当前工作目录不一样，撤销恢复就失真。
        # 做法：取 HEAD manifest 路径 ∪ 当前实际存在文件路径，对每条
        # 路径检查是否存在 → 生成 upsert/delete Change 列表。

        没东西可备份（HEAD 为空 + 工作目录全是忽略文件）时返回 None。
        """
        head = self._latest_commit_id()
        prev_manifest = self._load_manifest(head)

        # 当前工作目录里所有 "应被跟踪" 的文件（相对路径字符串）
        current_paths: set[str] = set()
        for root, dirs, files in os.walk(self.workspace):
            # 在 dirs 上原地裁剪能让 os.walk 不进 ignored 子树
            dirs[:] = [d for d in dirs if d not in IGNORE_PARTS]
            for f in files:
                p = Path(root) / f
                if should_ignore(p, extra_ignore_patterns):
                    continue
                try:
                    rel = p.relative_to(self.workspace).as_posix()
                except ValueError:
                    continue
                current_paths.add(rel)

        all_paths = set(prev_manifest.keys()) | current_paths
        if not all_paths:
            return None

        now = time.time()
        attr = AgentAttribution(
            agent="human",
            confidence=1.0,
            detection_method=detection_method,
        )

        changes: list[Change] = []
        for rel in all_paths:
            abs_p = self.workspace / rel
            if should_ignore(abs_p, extra_ignore_patterns):
                continue
            kind = "upsert" if abs_p.exists() else "delete"
            changes.append(
                Change(
                    file_path=abs_p,
                    event_time=now,
                    attribution=attr,
                    kind=kind,
                )
            )

        return self.commit(
            agent="human",
            changes=changes,
            attribution=attr,
            summary=summary,
        )

    def restore_file(
        self,
        commit_id: int,
        file_path: str,
        *,
        backup_current: bool = True,
    ) -> int | None:
        """
        从指定 commit 恢复单个文件到工作区。

        参数：
            commit_id: 目标 commit ID
            file_path: 文件相对路径（如 "src/main.py"）
            backup_current: 是否先备份当前状态（默认 True）

        返回：
            备份 commit 的 ID；如果 backup_current=False 或无需备份则返回 None

        异常：
            ValueError: commit 不存在 或 文件在目标 commit 中不存在
            OSError: 磁盘写入失败
        """
        # 1. 验证路径安全性（防止路径遍历），并规范化为 manifest key。
        try:
            manifest_key, abs_path = self._workspace_file(file_path)
        except ValueError:
            raise ValueError(f"文件路径 {file_path} 在 workspace 之外")

        # 2. 验证 commit 存在
        if not self._commit_exists(commit_id):
            raise ValueError(f"commit #{commit_id} 不存在")

        # 3. 加载目标 manifest，检查文件是否存在
        target_manifest = self._normalize_manifest(self._load_manifest(commit_id))
        if manifest_key not in target_manifest:
            raise ValueError(f"文件 {file_path} 在 commit #{commit_id} 中不存在")

        # 4. 备份当前状态（如果需要）
        backup_id: int | None = None
        if backup_current:
            backup_id = self._snapshot_current_state(
                summary=f"恢复 {file_path} 到 commit #{commit_id} 前的自动备份",
                detection_method="backup",
            )
            if backup_id is not None:
                logger.info("已备份当前状态到 commit #%d", backup_id)

        # 5. 读取目标文件的 blob，写入工作区。内容未变化则不重写，避免制造 watcher 噪声。
        blob_hash = target_manifest[manifest_key]
        write_needed = True
        if abs_path.exists() and abs_path.is_file():
            try:
                write_needed = hash_file(abs_path) != blob_hash
            except OSError:
                write_needed = True

        mark_restore_window(
            self.workspace, "restore_file", detection_method="restore_file"
        )
        if write_needed:
            blob_data = self.storage.get(blob_hash)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(blob_data)
        else:
            logger.debug("restore_file 跳过未变化写入: %s", manifest_key)

        # 6. 恢复本身也必须进入历史：否则 HEAD 仍指向恢复前，下一次 commit 会漂移。
        mark_restore_window(
            self.workspace, "restore_file", detection_method="restore_file"
        )
        restore_commit_id = self._snapshot_current_state(
            summary=f"恢复 {manifest_key} 到 commit #{commit_id}",
            detection_method="restore_file",
        )
        mark_restore_window(
            self.workspace, "restore_file", detection_method="restore_file"
        )

        logger.info(
            "已恢复文件 %s 从 commit #%d (blob=%s, restore_commit=%s)",
            manifest_key,
            commit_id,
            blob_hash[:8],
            restore_commit_id,
        )
        return backup_id
