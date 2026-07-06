"""
CLI 进程检测器单元测试
========================
mock psutil.process_iter 验证：
- 进程名不匹配 → 不被选
- 进程名匹配但 cwd 在工作目录外 → 不被选
- 进程名匹配且 cwd 在工作目录嵌套子目录 → 被选
- AccessDenied / NoSuchProcess / ZombieProcess → 静默吞掉
- cwd 为空字符串 / None → 跳过

# 人工编写
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

import psutil  # noqa: E402
from daemon.detectors.cli_detector import (  # noqa: E402
    clear_process_snapshot_cache,
    scan_cli_agents,
    scan_global_cli_agents,
)


def make_proc(
    name: str, pid: int, cwd: str | None, create_time: float = 1000.0
) -> MagicMock:
    """构造一个伪造的 psutil.Process（含 .info 字典）。"""
    p = MagicMock()
    p.info = {
        "pid": pid,
        "name": name,
        "cwd": cwd,
        "create_time": create_time,
    }
    return p


class FailingProc(MagicMock):
    """info 访问会抛特定异常的伪造 Process。"""

    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    @property
    def info(self):
        raise self._exc


class TestScanCliAgents(unittest.TestCase):
    def setUp(self):
        clear_process_snapshot_cache()
        self.workspace = Path("/Users/test/proj").resolve()

    def _run_with_procs(self, procs):
        """patch process_iter 返回 procs，跑 scan_cli_agents。"""
        clear_process_snapshot_cache()
        with patch(
            "daemon.detectors.cli_detector.psutil.process_iter",
            return_value=iter(procs),
        ):
            return scan_cli_agents(self.workspace)

    def test_unknown_process_skipped(self):
        result = self._run_with_procs(
            [
                make_proc("python", 100, str(self.workspace)),
                make_proc("zsh", 101, str(self.workspace)),
            ]
        )
        self.assertEqual(result, [])

    def test_cwd_outside_workspace_skipped(self):
        result = self._run_with_procs(
            [
                make_proc("claude", 200, "/Users/test/other_project"),
            ]
        )
        self.assertEqual(result, [])

    def test_cwd_inside_workspace_picked(self):
        result = self._run_with_procs(
            [
                make_proc("claude", 300, str(self.workspace)),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "claude")
        self.assertEqual(result[0].display_name, "Claude Code")
        self.assertEqual(result[0].pid, 300)
        self.assertEqual(result[0].category, "cli")

    def test_windows_exe_process_name_picked(self):
        """Windows 上 psutil 可能返回 codex.exe，大小写也不应影响匹配。"""
        result = self._run_with_procs(
            [
                make_proc("Codex.EXE", 350, str(self.workspace)),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "codex")
        self.assertEqual(result[0].display_name, "Codex CLI")

    def test_opencode_process_name_picked(self):
        result = self._run_with_procs(
            [
                make_proc("opencode", 360, str(self.workspace)),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "opencode")
        self.assertEqual(result[0].display_name, "OpenCode")

    def test_hermes_process_name_picked(self):
        result = self._run_with_procs(
            [
                make_proc("Hermes.EXE", 361, str(self.workspace)),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "hermes")
        self.assertEqual(result[0].display_name, "Hermes")

    def test_cursor_process_name_picked(self):
        result = self._run_with_procs(
            [
                make_proc("cursor", 365, str(self.workspace)),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "cursor")
        self.assertEqual(result[0].display_name, "Cursor")

    def test_kimi_alias_process_name_picked_with_canonical_key(self):
        result = self._run_with_procs(
            [
                make_proc("kimi-code", 362, str(self.workspace)),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "kimi")
        self.assertEqual(result[0].display_name, "Kimi Code")

    def test_cwd_is_resolved_before_workspace_comparison(self):
        nested = self.workspace / "src"
        result = self._run_with_procs(
            [
                make_proc("claude", 363, str(nested / ".." / "src")),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(Path(result[0].cwd), nested.resolve())

    def test_cwd_in_nested_subdir_picked(self):
        nested = self.workspace / "src" / "deep"
        result = self._run_with_procs(
            [
                make_proc("codex", 400, str(nested)),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "codex")

    def test_cwd_none_skipped(self):
        result = self._run_with_procs(
            [
                make_proc("claude", 500, None),
                make_proc("claude", 501, ""),
            ]
        )
        self.assertEqual(result, [])

    def test_access_denied_does_not_crash(self):
        result = self._run_with_procs(
            [
                FailingProc(psutil.AccessDenied()),
                make_proc("claude", 600, str(self.workspace)),  # 跟在后面的应仍被处理
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pid, 600)

    def test_no_such_process_does_not_crash(self):
        result = self._run_with_procs(
            [
                FailingProc(psutil.NoSuchProcess(1234)),
                make_proc("openclaw", 700, str(self.workspace)),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "openclaw")

    def test_zombie_process_does_not_crash(self):
        result = self._run_with_procs(
            [
                FailingProc(psutil.ZombieProcess(1234)),
            ]
        )
        self.assertEqual(result, [])

    def test_multiple_agents_all_picked(self):
        result = self._run_with_procs(
            [
                make_proc("claude", 800, str(self.workspace)),
                make_proc("codex", 801, str(self.workspace)),
                make_proc("cursor", 802, str(self.workspace)),
                make_proc("python", 803, str(self.workspace)),  # 应被跳
                make_proc("openclaw", 804, str(self.workspace / "src")),
                make_proc("opencode", 805, str(self.workspace / "tools")),
                make_proc("hermes", 806, str(self.workspace / "agents")),
                make_proc("kimi", 807, str(self.workspace / "chat")),
            ]
        )
        names = sorted(a.name for a in result)
        self.assertEqual(
            names, ["claude", "codex", "cursor", "hermes", "kimi", "openclaw", "opencode"]
        )

    def test_global_scan_picks_cli_agent_outside_workspace(self):
        result = []
        with patch(
            "daemon.detectors.cli_detector.psutil.process_iter",
            return_value=iter(
                [
                    make_proc("codex", 901, "/Users/test/other_project"),
                    make_proc("python", 902, "/Users/test/other_project"),
                ]
            ),
        ):
            result = scan_global_cli_agents()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "codex")
        self.assertEqual(result[0].pid, 901)


if __name__ == "__main__":
    unittest.main(verbosity=2)
