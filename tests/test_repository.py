"""
Repository / Storage / DB 连接缓存 综合回归测试
==================================================
这文件持久化第 12 周对话中跑过、但当时只以 inline `python -c` 形式验证的
关键断言——把它们写成可重跑的 unittest，确保以后任何人 `python -m unittest`
都能看到这些验证：

- 评审 #1：SQLite 连接缓存按 (线程, db_path) 联合 key，多 workspace 不串库
- 评审 #2：全量 manifest commit 模型 + BEGIN IMMEDIATE 并发安全
- 评审 #5：BlobStorage 构造函数无写盘副作用

# 人工编写（5/21 审计后补：把过去的 inline 验证固化到 tests/）
"""

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).parent.parent
ROOT = PROJECT / "code"
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(ROOT))

from core.repository import Repository  # noqa: E402
from core.storage import BlobStorage  # noqa: E402
from models.agent import AgentAttribution  # noqa: E402
from models.change import Change  # noqa: E402
from tests._tempdir import temp_dir, temp_repository  # noqa: E402
from utils.db import close_all_connections, close_connections, get_connection, init_db  # noqa: E402


class RepositoryTestCase(unittest.TestCase):
    def tearDown(self):
        close_all_connections()


def make_change(path: Path, kind: str = "upsert", agent: str = "claude") -> Change:
    return Change(
        file_path=path,
        event_time=time.time(),
        attribution=AgentAttribution(agent=agent, confidence=0.95),
        kind=kind,
    )


# ============================================================
# 评审 #5：BlobStorage 构造函数无副作用
# ============================================================
class TestBlobStorageNoSideEffect(RepositoryTestCase):
    """评审 #5 验证：构造 Repository 不应直接 mkdir."""

    def test_construct_does_not_mkdir(self):
        with temp_repository() as (r, ws):
            self.assertFalse(
                (ws / ".trace").exists(), "Repository 构造时不应创建 .trace/"
            )
            # init_if_needed 应当被调用一次才创建
            r.init_if_needed()
            self.assertTrue((ws / ".trace" / "objects").exists())

    def test_first_time_detection_accurate(self):
        """init_if_needed 必须能准确识别首次初始化。"""
        with temp_repository() as (r1, ws):
            r1.init_if_needed()
            # 第二次调用同一仓库不应再算"首次"——但本测试核心是构造不影响
            # 第一次的判断，所以这里我们建第二个仓库验证状态隔离
            with temp_dir() as ws2:
                r2 = Repository(ws2)
                # 还没 init_if_needed → .trace 不存在
                self.assertFalse((ws2 / ".trace").exists())

    def test_blob_storage_ensure_dir_explicit(self):
        """ensure_dir() 是显式接口，构造函数不做任何 mkdir。"""
        with temp_dir() as root:
            objects = root / "objects"
            bs = BlobStorage(objects)
            self.assertFalse(objects.exists(), "构造不该创建 objects/")
            bs.ensure_dir()
            self.assertTrue(objects.is_dir())

    def test_blob_storage_uses_os_replace_for_final_move(self):
        """跨平台小修：最终落点用 os.replace，而不是 Path.rename。"""
        with temp_dir() as root:
            src = root / "hello.txt"
            src.write_text("hello", encoding="utf-8")
            objects = root / "objects"
            bs = BlobStorage(objects)
            bs.ensure_dir()

            def real_replace(src_path, dst_path):
                Path(src_path).rename(dst_path)

            with patch("core.storage.os.replace", side_effect=real_replace) as replace:
                sha = bs.put_file(src)

            final = objects / sha[:2] / sha[2:]
            self.assertTrue(final.exists())
            self.assertEqual(final.read_bytes(), b"hello")
            replace.assert_called_once()


# ============================================================
# 评审 #1：SQLite 连接缓存按 (线程, db_path) 联合 key
# ============================================================
class TestDBConnectionCache(RepositoryTestCase):
    """评审 #1 验证：多 workspace 不能复用同一连接。"""

    def test_different_db_paths_get_distinct_connections(self):
        with temp_dir() as root:
            db1 = root / "a.db"
            db2 = root / "b.db"
            c1 = get_connection(db1)
            c2 = get_connection(db2)
            self.assertIsNot(c1, c2, "两个 db_path 不能复用同一连接（评审 #1）")

    def test_same_db_path_cached(self):
        with temp_dir() as root:
            db1 = root / "a.db"
            c1 = get_connection(db1)
            c1_again = get_connection(db1)
            self.assertIs(c1, c1_again, "同 db_path 应命中缓存")

    def test_data_isolation_between_two_dbs(self):
        """物理隔离：写 db1 不会跑到 db2 里去。"""
        with temp_dir() as root:
            db1 = root / "a.db"
            db2 = root / "b.db"
            c1 = get_connection(db1)
            c2 = get_connection(db2)

            c1.execute("CREATE TABLE t(x INTEGER)")
            c1.execute("INSERT INTO t VALUES (1)")
            c2.execute("CREATE TABLE t(y TEXT)")
            c2.execute("INSERT INTO t VALUES ('hello')")

            r1 = c1.execute("SELECT x FROM t").fetchone()
            r2 = c2.execute("SELECT y FROM t").fetchone()
            self.assertEqual(r1["x"], 1)
            self.assertEqual(r2["y"], "hello")


class TestAgentRegistry(RepositoryTestCase):
    """Agent 注册表应包含所有可自动检测和手动指定的 CLI agent。"""

    def test_preset_agents_include_opencode_and_hermes(self):
        with temp_dir() as root:
            db_path = root / "trace.db"
            init_db(db_path)
            conn = get_connection(db_path)
            rows = conn.execute(
                "SELECT name, display_name FROM agents ORDER BY name"
            ).fetchall()

        display_by_name = {row["name"]: row["display_name"] for row in rows}
        self.assertEqual(display_by_name["opencode"], "OpenCode")
        self.assertEqual(display_by_name["hermes"], "Hermes")
        self.assertEqual(display_by_name["kimi"], "Kimi Code")
        self.assertNotIn("kimi code", display_by_name)


# ============================================================
# 评审 #2：全量 manifest commit 模型
# ============================================================
class TestManifestCommitModel(RepositoryTestCase):
    """评审 #2 的 7 项核心回归——把 inline 验证固化。"""

    def test_checkout_removes_extra_files(self):
        """**子代理审计复现的核心 bug**：
        checkout 到删除文件后的 commit 时，已删文件不应再出现。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a, b = ws / "a.txt", ws / "b.txt"
            a.write_text("A1")
            b.write_text("B1")
            c1 = r.commit("claude", [make_change(a), make_change(b)])
            b.unlink()
            c2 = r.commit("claude", [make_change(b, kind="delete")])

            r.checkout_commit(c1, backup_current=False)
            self.assertTrue((ws / "a.txt").exists())
            self.assertTrue((ws / "b.txt").exists())

            r.checkout_commit(c2, backup_current=False)
            self.assertTrue((ws / "a.txt").exists())
            self.assertFalse(
                (ws / "b.txt").exists(),
                "★ 核心修复点：checkout 必须删除目标 commit 不应有的文件",
            )

    def test_empty_manifest_commit_is_valid(self):
        """评审 #2 D1：删空后的 commit (空 manifest) 也合法可 checkout。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a = ws / "a.txt"
            a.write_text("hello")
            r.commit("claude", [make_change(a)])
            a.unlink()
            c2 = r.commit("claude", [make_change(a, kind="delete")])

            r.checkout_commit(c2, backup_current=True)
            self.assertFalse((ws / "a.txt").exists())

    def test_nonexistent_commit_raises(self):
        with temp_repository() as (r, ws):
            r.init_if_needed()
            with self.assertRaises(ValueError):
                r.checkout_commit(999, backup_current=False)

    def test_concurrent_commits_no_lost_update(self):
        """评审 #2 Q1：BEGIN IMMEDIATE 串行化两个 agent 并发 flush 不丢数据。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            f_c = ws / "claude.txt"
            f_x = ws / "codex.txt"
            f_c.write_text("claude")
            f_x.write_text("codex")
            results = {}

            def worker(name, change):
                try:
                    results[name] = r.commit(name, [change])
                finally:
                    close_connections(r.db_path)

            t1 = threading.Thread(
                target=worker, args=("claude", make_change(f_c, agent="claude"))
            )
            t2 = threading.Thread(
                target=worker, args=("codex", make_change(f_x, agent="codex"))
            )
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            last = max(results.values())
            m = r._load_manifest(last)
            self.assertIn("claude.txt", m, f"lost-update! manifest={m}")
            self.assertIn("codex.txt", m, f"lost-update! manifest={m}")

    def test_snapshot_current_state_reflects_disk(self):
        """评审 #2 Q3：_snapshot_current_state 备份应同步处理已删的文件。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a, b = ws / "a.txt", ws / "b.txt"
            a.write_text("A")
            b.write_text("B")
            r.commit("claude", [make_change(a), make_change(b)])

            a.unlink()
            backup = r._snapshot_current_state("test backup")
            m = r._load_manifest(backup)
            self.assertEqual(
                set(m.keys()), {"b.txt"}, f"备份应仅含当前实存文件，不应保留已删: {m}"
            )

    def test_mixed_upsert_and_delete_in_single_commit(self):
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a, b, c = ws / "a.txt", ws / "b.txt", ws / "c.txt"
            a.write_text("A0")
            b.write_text("B")
            c.write_text("C")
            r.commit("claude", [make_change(a), make_change(b), make_change(c)])
            a.write_text("A2")
            c.unlink()
            cid = r.commit("claude", [make_change(a), make_change(c, kind="delete")])
            m = r._load_manifest(cid)
            self.assertEqual(set(m.keys()), {"a.txt", "b.txt"})
            self.assertEqual(r.storage.get(m["a.txt"]), b"A2")

    def test_multi_checkout_roundtrip(self):
        """连续 checkout 多个历史版本，每次文件集合都对得上。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a, b, c = ws / "a.txt", ws / "b.txt", ws / "c.txt"
            a.write_text("A")
            b.write_text("B")
            cid1 = r.commit("claude", [make_change(a), make_change(b)])
            c.write_text("C")
            cid2 = r.commit("claude", [make_change(c)])
            b.unlink()
            cid3 = r.commit("claude", [make_change(b, kind="delete")])

            r.checkout_commit(cid1, backup_current=False)
            visible = sorted(
                p.name
                for p in ws.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
            self.assertEqual(visible, ["a.txt", "b.txt"])

            r.checkout_commit(cid3, backup_current=False)
            visible = sorted(
                p.name
                for p in ws.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
            self.assertEqual(visible, ["a.txt", "c.txt"])

            r.checkout_commit(cid2, backup_current=False)
            visible = sorted(
                p.name
                for p in ws.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
            self.assertEqual(visible, ["a.txt", "b.txt", "c.txt"])

    def test_untracked_user_files_preserved_across_checkout(self):
        """git 风格：从未跟踪过的用户文件不应被 checkout 删掉。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a = ws / "a.txt"
            a.write_text("A")
            cid = r.commit("claude", [make_change(a)])

            untracked = ws / "user_notes.txt"
            untracked.write_text("我的临时笔记")

            r.checkout_commit(cid, backup_current=False)
            self.assertTrue(
                untracked.exists(), "未跟踪文件不应被 checkout 删除（git 行为）"
            )

    def test_noop_commit_is_not_written_when_manifest_unchanged(self):
        """重复文件事件但内容未变时，不应生成一个和 HEAD 完全相同的新 commit。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a = ws / "a.txt"
            a.write_text("same", encoding="utf-8")
            first = r.commit("human", [make_change(a, agent="human")])

            duplicate = r.commit("human", [make_change(a, agent="human")])

            self.assertIsNotNone(first)
            self.assertIsNone(duplicate)
            commits = r.list_commits()
            self.assertEqual(len(commits), 1)
            self.assertEqual(commits[0]["id"], first)

    def test_list_commits_includes_detection_metadata(self):
        """Electron 时间线需要候选 agent 和置信度来显示不确定归因。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a = ws / "a.txt"
            a.write_text("ambiguous", encoding="utf-8")
            r.commit(
                "unknown",
                [make_change(a, agent="unknown")],
                attribution=AgentAttribution(
                    agent="unknown",
                    confidence=0.35,
                    detection_method="global_cli_fallback",
                    candidates=["claude", "codex"],
                    ambiguous=True,
                ),
            )

            commit = r.list_commits()[0]

            self.assertEqual(commit["author_agent"], "unknown")
            self.assertEqual(commit["detection_method"], "global_cli_fallback")
            self.assertEqual(commit["candidates"], ["claude", "codex"])
            self.assertEqual(commit["confidence"], 0.35)

    def test_snapshot_current_state_returns_none_when_disk_matches_head(self):
        """自动备份时磁盘状态等于 HEAD，也不应写重复 commit。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a = ws / "a.txt"
            a.write_text("same", encoding="utf-8")
            r.commit("human", [make_change(a, agent="human")])

            backup = r._snapshot_current_state("noop backup")

            self.assertIsNone(backup)
            self.assertEqual(len(r.list_commits()), 1)

    def test_checkout_records_human_commit_and_prevents_manifest_drift(self):
        """checkout 后 HEAD 必须等于磁盘状态，下一次 commit 不能带回幽灵文件。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a, b, c = ws / "a.txt", ws / "b.bin", ws / "c.txt"
            a.write_text("A1", encoding="utf-8")
            b.write_bytes(b"bin")
            c1 = r.commit("claude", [make_change(a), make_change(b)])
            a.write_text("A2", encoding="utf-8")
            c.write_text("C", encoding="utf-8")
            r.commit("claude", [make_change(a), make_change(c)])

            backup = r.checkout_commit(c1, backup_current=True)

            self.assertIsNone(backup)
            self.assertFalse(c.exists())
            head = r.list_commits(limit=1)[0]
            self.assertEqual(head["author_agent"], "human")
            self.assertEqual(head["detection_method"], "checkout")
            self.assertEqual(
                set(r._load_manifest(head["id"]).keys()), {"a.txt", "b.bin"}
            )

            a.write_text("A3", encoding="utf-8")
            c_after = r.commit("codex", [make_change(a, agent="codex")])
            self.assertNotIn("c.txt", r._load_manifest(c_after))

            r.checkout_commit(c_after, backup_current=False)
            self.assertFalse(c.exists(), "幽灵 c.txt 不应在后续 checkout 中复活")

    def test_checkout_skips_files_whose_hash_is_unchanged(self):
        """checkout 不应无差别重写目标 manifest 中内容未变化的文件。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()
            a, b = ws / "a.txt", ws / "b.txt"
            a.write_text("A1", encoding="utf-8")
            b.write_text("stable", encoding="utf-8")
            c1 = r.commit("human", [make_change(a), make_change(b)])
            a.write_text("A2", encoding="utf-8")
            r.commit("human", [make_change(a)])
            b_mtime_ns = b.stat().st_mtime_ns

            r.checkout_commit(c1, backup_current=False)

            self.assertEqual(b.read_text(encoding="utf-8"), "stable")
            self.assertEqual(b.stat().st_mtime_ns, b_mtime_ns)


# ============================================================
# restore_file 单文件恢复测试
# ============================================================
class TestRestoreFile(RepositoryTestCase):
    """验证 restore_file 方法的正确性和边界情况。"""

    def test_restore_single_file_from_history(self):
        """基础场景：从历史 commit 恢复单个文件到磁盘。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()

            # commit 1: a.txt = "v1"
            a = ws / "a.txt"
            a.write_text("v1", encoding="utf-8")
            c1 = r.commit("human", [make_change(a)])

            # commit 2: a.txt = "v2"
            a.write_text("v2", encoding="utf-8")
            c2 = r.commit("human", [make_change(a)])

            # 当前磁盘 = v2（等于 HEAD），恢复 c1 的 a.txt
            # 由于磁盘 = HEAD，_snapshot_current_state 不会产生备份
            backup = r.restore_file(c1, "a.txt")

            # 磁盘 = HEAD 时不产生备份
            self.assertIsNone(backup, "磁盘等于 HEAD 时无需备份")
            self.assertEqual(a.read_text(encoding="utf-8"), "v1")
            commits = r.list_commits()
            self.assertEqual(len(commits), 3)
            self.assertEqual(commits[0]["author_agent"], "human")
            self.assertEqual(commits[0]["detection_method"], "restore_file")
            self.assertEqual(
                r.storage.get(r._load_manifest(commits[0]["id"])["a.txt"]), b"v1"
            )

    def test_restore_with_uncommitted_changes_creates_backup(self):
        """磁盘有未提交的修改时，恢复会产生备份。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()

            # commit 1: a.txt = "v1"
            a = ws / "a.txt"
            a.write_text("v1", encoding="utf-8")
            c1 = r.commit("human", [make_change(a)])

            # commit 2: a.txt = "v2"
            a.write_text("v2", encoding="utf-8")
            c2 = r.commit("human", [make_change(a)])

            # 修改磁盘但不提交
            a.write_text("v3-uncommitted", encoding="utf-8")

            # 恢复 c1：此时磁盘 != HEAD，会产生备份
            backup = r.restore_file(c1, "a.txt")

            self.assertIsNotNone(backup, "未提交的修改应产生备份")
            self.assertEqual(a.read_text(encoding="utf-8"), "v1")
            # c1, c2, backup, restore commit = 4 个 commit
            commits = r.list_commits()
            self.assertEqual(len(commits), 4)
            self.assertEqual(commits[0]["detection_method"], "restore_file")

            # 验证备份保存了 v3
            manifest = r._load_manifest(backup)
            backup_hash = manifest["a.txt"]
            backup_content = r.storage.get(backup_hash)
            self.assertEqual(backup_content, b"v3-uncommitted")

    def test_restore_file_not_in_commit(self):
        """历史 commit 中不包含该文件 → 抛 ValueError。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()

            a = ws / "a.txt"
            a.write_text("old", encoding="utf-8")
            c1 = r.commit("human", [make_change(a)])

            # b.txt 从未存在于 c1
            with self.assertRaises(ValueError) as ctx:
                r.restore_file(c1, "b.txt")
            self.assertIn("不存在", str(ctx.exception))

    def test_restore_file_no_changes_returns_none(self):
        """磁盘内容已经等于历史版本 → 返回 None（无备份）。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()

            a = ws / "a.txt"
            a.write_text("same", encoding="utf-8")
            c1 = r.commit("human", [make_change(a)])

            # 磁盘未改动，恢复等于 no-op
            backup = r.restore_file(c1, "a.txt")

            self.assertIsNone(backup)
            self.assertEqual(len(r.list_commits()), 1)

    def test_restore_deleted_file_from_history(self):
        """磁盘已删除的文件可以从历史恢复。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()

            a = ws / "a.txt"
            a.write_text("exists", encoding="utf-8")
            c1 = r.commit("human", [make_change(a)])

            # 删除文件并提交
            a.unlink()
            c2 = r.commit("human", [make_change(a, kind="delete")])

            # 恢复（磁盘 = HEAD（空），无备份需求）
            backup = r.restore_file(c1, "a.txt")

            # 磁盘 = HEAD 时不产生备份
            self.assertIsNone(backup, "磁盘 = HEAD 时无需备份")
            self.assertTrue(a.exists())
            self.assertEqual(a.read_text(encoding="utf-8"), "exists")
            commits = r.list_commits()
            self.assertEqual(len(commits), 3)
            self.assertEqual(commits[0]["detection_method"], "restore_file")

    def test_restore_file_preserves_other_files(self):
        """恢复单个文件不影响其他文件。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()

            a = ws / "a.txt"
            b = ws / "b.txt"
            a.write_text("a1", encoding="utf-8")
            b.write_text("b1", encoding="utf-8")
            c1 = r.commit("human", [make_change(a), make_change(b)])

            # 修改两个文件
            a.write_text("a2", encoding="utf-8")
            b.write_text("b2", encoding="utf-8")
            r.commit("human", [make_change(a), make_change(b)])

            # 只恢复 a
            r.restore_file(c1, "a.txt")

            self.assertEqual(a.read_text(encoding="utf-8"), "a1")
            self.assertEqual(b.read_text(encoding="utf-8"), "b2", "b 不应被影响")

    def test_restore_file_outside_workspace_raises_error(self):
        """文件路径在 workspace 之外 → ValueError。"""
        with temp_repository() as (r, ws):
            r.init_if_needed()

            a = ws / "a.txt"
            a.write_text("in", encoding="utf-8")
            c1 = r.commit("human", [make_change(a)])

            # 尝试使用相对路径逃逸
            with self.assertRaises(ValueError) as ctx:
                r.restore_file(c1, "../outside.txt")
            self.assertIn("workspace 之外", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
