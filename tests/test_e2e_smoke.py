"""
端到端冒烟测试（subprocess 起真的 main.py）
==============================================
最贴近真实使用的测试：
    1. 在临时目录新建一个 workspace
    2. subprocess 启 main.py --workspace WS
    3. 等守护就绪（轮询日志）
    4. 在 WS 里真的写/改/删文件
    5. 信号让守护优雅退出
    6. 打开 .trace/trace.db 验 SQLite 真的有期望的 commit

# 人工编写（评审：这是"真的能用吗"的唯一直接证据）
# 注意：
#   - HOME 重定向到临时目录，避免污染真实的"上次工作区"记忆
#   - 关键时序：每次文件操作后 sleep > IDLE_WINDOW (2.0s) + 安全余量
"""

import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
CODE_DIR = ROOT / "code"


IDLE_WAIT = 3.5  # > batcher.IDLE_WINDOW_SECONDS(2.0) + 安全余量
STARTUP_WAIT = 5.0  # 等"守护进程运行中" 出现的最长时间


def _wait_for_ready(proc: subprocess.Popen, log_path: Path, timeout: float) -> None:
    """轮询 proc 的日志文件，等到看到"守护进程运行中"为止。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if log_path.exists():
            text = log_path.read_text(errors="replace")
            if "守护进程运行中" in text:
                return
        if proc.poll() is not None:
            raise RuntimeError(
                f"守护进程意外退出，returncode={proc.returncode}\n日志:\n"
                + (
                    log_path.read_text(errors="replace")
                    if log_path.exists()
                    else "(无)"
                )
            )
        time.sleep(0.2)
    raise TimeoutError(f"守护进程 {timeout}s 内未就绪")


class TestE2ESmoke(unittest.TestCase):
    def test_full_lifecycle(self):
        """
        生命周期覆盖：启动 → 新建 → 修改 → 删除 → 优雅退出 → 数据齐全。
        """
        with (
            tempfile.TemporaryDirectory() as fake_home,
            tempfile.TemporaryDirectory() as ws_dir,
        ):
            ws = Path(ws_dir)
            log_path = ws / "daemon.log"

            # 重定向 HOME 让 state.json 不污染真用户目录
            env = os.environ.copy()
            env["HOME"] = fake_home
            env["PYTHONUNBUFFERED"] = "1"
            env["TRACE_DISABLE_GLOBAL_AGENT_FALLBACK"] = "1"

            with log_path.open("w") as logf:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "main.py",
                        "--workspace",
                        str(ws),
                        "--headless",  # Task 4.3 起 main.py 默认会拉 rumps；
                        # E2E 用 --headless 跑纯守护进程
                        "-v",
                    ],
                    cwd=str(CODE_DIR),
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    env=env,
                )

            try:
                _wait_for_ready(proc, log_path, STARTUP_WAIT)

                # === 阶段 1: 新建两个文件 ===
                (ws / "a.py").write_text("def hello():\n    return 'a'\n")
                (ws / "b.txt").write_text("line1\nline2\n")
                time.sleep(IDLE_WAIT)

                # === 阶段 2: 修改其中一个 ===
                (ws / "a.py").write_text("def hello():\n    return 'A2'\n")
                time.sleep(IDLE_WAIT)

                # === 阶段 3: 删除一个 ===
                (ws / "b.txt").unlink()
                time.sleep(IDLE_WAIT)

                # === 优雅退出 ===
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=10)

            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

            # === 验证 ===
            db_path = ws / ".trace" / "trace.db"
            self.assertTrue(
                db_path.exists(), f"数据库不存在；日志:\n{log_path.read_text()}"
            )

            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                commits = conn.execute(
                    "SELECT id, author_agent, summary FROM commits ORDER BY id"
                ).fetchall()
                self.assertGreaterEqual(
                    len(commits),
                    3,
                    f"期望至少 3 个 commit（新建/修改/删除各一），实际 {len(commits)}\n"
                    f"commits = {[dict(c) for c in commits]}\n"
                    f"日志:\n{log_path.read_text()}",
                )

                # 所有 commit 都应归 human（没启动 claude / codex）
                for c in commits:
                    self.assertEqual(
                        c["author_agent"],
                        "human",
                        f"commit {c['id']} 归属错: {c['author_agent']}",
                    )

                # 最末 commit 的 manifest 应该只剩 a.py（b.txt 已删）
                last_cid = commits[-1]["id"]
                files = {
                    r["file_path"]
                    for r in conn.execute(
                        "SELECT file_path FROM snapshots WHERE commit_id=?", (last_cid,)
                    ).fetchall()
                }
                self.assertEqual(
                    files,
                    {"a.py"},
                    f"末 commit manifest 期望 {{a.py}}, 实际 {files}\n"
                    f"全日志:\n{log_path.read_text()}",
                )

                # 倒数第二的 manifest 应同时有 a.py + b.txt（删除前的状态）
                mid_cid = commits[-2]["id"]
                mid_files = {
                    r["file_path"]
                    for r in conn.execute(
                        "SELECT file_path FROM snapshots WHERE commit_id=?", (mid_cid,)
                    ).fetchall()
                }
                self.assertIn("a.py", mid_files)
                self.assertIn("b.txt", mid_files)

                # 第一个 commit 应包含两个新建文件
                first_cid = commits[0]["id"]
                first_files = {
                    r["file_path"]
                    for r in conn.execute(
                        "SELECT file_path FROM snapshots WHERE commit_id=?",
                        (first_cid,),
                    ).fetchall()
                }
                self.assertEqual(first_files, {"a.py", "b.txt"})

            # blob 存储应不为空
            blobs_root = ws / ".trace" / "objects"
            self.assertTrue(blobs_root.is_dir())
            blob_count = sum(1 for _ in blobs_root.rglob("*") if _.is_file())
            self.assertGreater(blob_count, 0, "blob 目录是空的")


if __name__ == "__main__":
    unittest.main(verbosity=2)
