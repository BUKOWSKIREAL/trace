"""
PathDeduper 单元测试
========================
锁定 E2E 冒烟暴露的真 bug 的修复——dedup 必须按 (path, kind) 联合 key，
不能只按 path：否则 modify→delete 相邻事件中 delete 会被吞。

红绿验证（运行时模拟）：本文件还含一个 test_old_behavior_would_lose_delete，
它复刻"旧版只按 path 去重"的逻辑，验证那个版本**真的会**吞 delete——
确保我们的新合同（(path, kind) 各走窗口）有实际意义。

# 人工编写（5/21 审计后补：E2E 修复需要单元级回归保护）
"""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from daemon.watcher import PathDeduper  # noqa: E402


class TestPathDeduper(unittest.TestCase):

    def test_first_event_passes(self):
        d = PathDeduper()
        self.assertTrue(d.should_process(Path("/x/a.py")))

    def test_repeated_same_kind_within_window_blocked(self):
        d = PathDeduper()
        p = Path("/x/a.py")
        self.assertTrue(d.should_process(p, kind="write"))
        self.assertFalse(d.should_process(p, kind="write"),
                         "500ms 内同 (path, kind) 第二次应被去重")

    def test_modify_and_delete_same_path_both_pass(self):
        """**核心合同**：modify 和 delete 同路径短时间内不互相吞。

        这是 E2E 冒烟暴露的真 bug 的修复点：FSEvents 把 write→delete
        合并成一个 native event，watchdog 拆为相邻两个事件，旧版按 path
        去重把 delete 吞了 → batcher 收不到 delete → checkout 时
        文件不消失。
        """
        d = PathDeduper()
        p = Path("/x/b.txt")
        # 时间紧挨着——模拟 FSEvents 拆出来的两条
        self.assertTrue(d.should_process(p, kind="write"),
                        "modify 事件应当通过")
        self.assertTrue(d.should_process(p, kind="delete"),
                        "★ 紧跟着的 delete 不应被 modify 吞掉")

    def test_different_paths_dont_dedup_each_other(self):
        d = PathDeduper()
        self.assertTrue(d.should_process(Path("/x/a.py"), kind="write"))
        self.assertTrue(d.should_process(Path("/x/b.py"), kind="write"))
        self.assertTrue(d.should_process(Path("/x/c.py"), kind="write"))

    def test_after_window_repeat_passes_again(self):
        d = PathDeduper()
        p = Path("/x/a.py")
        # 把 DEDUP_WINDOW 缩到 0.05s 加速测试
        d.DEDUP_WINDOW = 0.05
        self.assertTrue(d.should_process(p))
        time.sleep(0.06)
        self.assertTrue(d.should_process(p), "窗口过后应可再次通过")

    def test_gc_clears_old_entries(self):
        d = PathDeduper()
        d.MAX_AGE = 0.01
        d.GC_INTERVAL = 0.0  # 每次 should_process 都触发 GC
        d.should_process(Path("/x/old.py"))
        time.sleep(0.05)
        # 触发一次 should_process 让 GC 跑
        d.should_process(Path("/x/new.py"))
        self.assertNotIn((Path("/x/old.py"), "write"), d.last_seen,
                         "GC 后旧条目应被清理")


class TestOldBehaviorWouldFail(unittest.TestCase):
    """红绿验证：用一个"只按 path 去重"的简化复刻，证明那个版本会
    吞掉 delete——这样新合同的回归保护就有实证。
    """

    def test_old_path_only_dedup_eats_delete(self):
        """复刻评审 #2 修复前的逻辑（只按 path），证明它会吞 delete。"""
        last_seen: dict[Path, float] = {}
        DEDUP_WINDOW = 0.5

        def old_should_process(path: Path) -> bool:
            now = time.time()
            last = last_seen.get(path, 0.0)
            last_seen[path] = now
            return (now - last) >= DEDUP_WINDOW

        p = Path("/x/b.txt")
        # 第一条 modify 事件
        modify_ok = old_should_process(p)
        # 紧跟着的 delete（FSEvents 拆分模拟）
        delete_ok = old_should_process(p)

        self.assertTrue(modify_ok)
        self.assertFalse(delete_ok,
                         "★ 旧逻辑确实会吞掉 delete——这就是修复前的真 bug，"
                         "证明我们的 (path, kind) 修复是有价值的")


if __name__ == "__main__":
    unittest.main(verbosity=2)
