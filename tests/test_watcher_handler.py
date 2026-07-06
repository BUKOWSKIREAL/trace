"""
TraceHandler 单元测试（Task 4：override_agent + paused 字段）
==================================================================
锁定 Handler 在两个新状态下的行为：
- paused=True 时，_dispatch / _dispatch_delete 应当不投递事件给 batcher
- override_agent="claude" 时，_attribute 应返回 forced=claude 的 attribution
  （manual_override / confidence=1.0），跳过 psutil 扫描

# 人工编写（TDD：测试先于实现）
"""

import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from daemon.watcher import TraceHandler  # noqa: E402
from daemon.trace_activity import TraceActivityStore  # noqa: E402
from models.agent import AgentAttribution, AgentInstance  # noqa: E402
from utils.restore_sentinel import mark_restore_window  # noqa: E402


def make_handler(active_agents=None, monkey_scan=True):
    """构造一个测试用 Handler，batcher 用 MagicMock。
    monkey_scan=True 时把 scan_active_agents 替换成可控 mock。"""
    workspace = Path("/tmp/test_ws")
    batcher = MagicMock()
    h = TraceHandler(workspace, batcher)
    if monkey_scan:
        # 注入一个 mock scan，让 _attribute 测试不依赖真实 psutil
        h._scan_for_test = MagicMock(return_value=active_agents or [])
    return h, batcher


class TestHandlerInitialState(unittest.TestCase):
    """Task 4.1：新字段默认值。"""

    def test_paused_default_false(self):
        h, _ = make_handler()
        self.assertFalse(h.paused)

    def test_override_agent_default_none(self):
        h, _ = make_handler()
        self.assertIsNone(h.override_agent)


class TestHandlerRestoreSentinel(unittest.TestCase):
    """Repository 恢复/回退写盘期间 watcher 不应生成假 agent 事件。"""

    def test_restore_sentinel_blocks_dispatch(self):
        with TemporaryDirectory() as td:
            workspace = Path(td)
            (workspace / ".trace").mkdir()
            target = workspace / "foo.py"
            target.write_text("x", encoding="utf-8")
            mark_restore_window(workspace, "checkout", detection_method="checkout")
            batcher = MagicMock()
            h = TraceHandler(workspace, batcher)
            h._executor = MagicMock()

            h._dispatch(str(target))
            h._dispatch_delete(str(target))

            h._executor.submit.assert_not_called()

    def test_restore_sentinel_attributes_inflight_event_to_human(self):
        with TemporaryDirectory() as td:
            workspace = Path(td)
            (workspace / ".trace").mkdir()
            mark_restore_window(
                workspace, "restore_file", detection_method="restore_file"
            )
            h = TraceHandler(workspace, MagicMock())
            h.override_agent = "claude"

            attr = h._attribute(workspace / "foo.py")

            self.assertEqual(attr.agent, "human")
            self.assertEqual(attr.confidence, 1.0)
            self.assertEqual(attr.detection_method, "restore_file")


class TestHandlerTraceActivity(unittest.TestCase):
    def test_trace_mcp_report_beats_workspace_multi_agent_ambiguity(self):
        with TemporaryDirectory() as td:
            workspace = Path(td)
            target = workspace / "foo.py"
            target.write_text("print('x')\n", encoding="utf-8")
            batcher = MagicMock()
            h = TraceHandler(workspace, batcher)
            h.trace_activity = TraceActivityStore(workspace)
            event_time = time.time()
            h.trace_activity.record_files(
                agent="codex",
                files=["foo.py"],
                event_time=event_time,
                source="mcp",
            )
            h._scan_for_test = MagicMock(
                return_value=[
                    AgentInstance("codex", "Codex CLI", "cli", cwd=str(workspace)),
                    AgentInstance("claude", "Claude Code", "cli", cwd=str(workspace)),
                ]
            )

            attr = h._attribute(target, event_time=event_time)

            self.assertEqual(attr.agent, "codex")
            self.assertEqual(attr.confidence, 1.0)
            self.assertEqual(attr.detection_method, "trace_mcp")
            self.assertFalse(attr.ambiguous)


class TestHandlerPause(unittest.TestCase):
    """Task 4.1：paused=True 时事件不应被处理。"""

    def test_paused_blocks_dispatch_write(self):
        h, batcher = make_handler()
        h.paused = True
        # _dispatch 应该在 paused 时直接返回，不投到线程池
        # 通过 mock 线程池验证 submit 没被调用
        h._executor = MagicMock()
        h._dispatch("/tmp/test_ws/foo.py")
        h._executor.submit.assert_not_called()

    def test_paused_blocks_dispatch_delete(self):
        h, batcher = make_handler()
        h.paused = True
        h._executor = MagicMock()
        h._dispatch_delete("/tmp/test_ws/foo.py")
        h._executor.submit.assert_not_called()

    def test_unpaused_allows_dispatch(self):
        h, batcher = make_handler()
        h.paused = False
        h._executor = MagicMock()
        # 注意：should_ignore 和 deduper 仍生效；用一个普通名字保证不被吞
        h._dispatch("/tmp/test_ws/foo.py")
        h._executor.submit.assert_called_once()


class TestHandlerMoveEvents(unittest.TestCase):
    def test_on_moved_dispatches_delete_for_source_and_upsert_for_dest(self):
        h, _ = make_handler()
        h._dispatch_delete = MagicMock()
        h._dispatch = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/tmp/test_ws/x.txt"
        event.dest_path = "/tmp/test_ws/y.txt"

        h.on_moved(event)

        h._dispatch_delete.assert_called_once_with("/tmp/test_ws/x.txt")
        h._dispatch.assert_called_once_with("/tmp/test_ws/y.txt")

    def test_on_moved_office_temp_source_is_ignored_by_delete_path(self):
        h, _ = make_handler()
        h._executor = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/tmp/test_ws/~$doc.docx"
        event.dest_path = "/tmp/test_ws/doc.docx"

        h.on_moved(event)

        # src 被 should_ignore 吃掉，只剩 dest upsert。
        h._executor.submit.assert_called_once()


class TestHandlerOverride(unittest.TestCase):
    """Task 4.1：override_agent 设了之后，_attribute 直接返回 forced。"""

    def test_override_set_attribute_returns_forced(self):
        h, _ = make_handler(active_agents=[])
        h.override_agent = "claude"
        attr = h._attribute(Path("/tmp/test_ws/foo.py"))
        self.assertEqual(attr.agent, "claude")
        self.assertEqual(attr.detection_method, "manual_override")
        self.assertEqual(attr.confidence, 1.0)

    def test_override_set_to_codex(self):
        h, _ = make_handler(active_agents=[])
        h.override_agent = "codex"
        attr = h._attribute(Path("/tmp/test_ws/foo.py"))
        self.assertEqual(attr.agent, "codex")

    def test_override_none_falls_back_to_auto(self):
        """override_agent=None 时走原来的自动检测（这里没有活跃 agent → human）"""
        h, _ = make_handler(active_agents=[])
        h._scan_global_for_test = MagicMock(return_value=[])
        h.override_agent = None
        attr = h._attribute(Path("/tmp/test_ws/foo.py"))
        self.assertEqual(attr.agent, "human")
        # detection_method 应该不是 manual_override
        self.assertNotEqual(attr.detection_method, "manual_override")

    def test_global_codex_fallback_when_workspace_scan_empty(self):
        """Codex 用绝对路径改另一个 workspace 时，应低置信度归到全局活跃 Codex。"""
        h, _ = make_handler(active_agents=[])
        h._scan_global_for_test = MagicMock(
            return_value=[
                AgentInstance(
                    name="codex",
                    display_name="Codex CLI",
                    category="cli",
                    pid=901,
                    cwd="/Users/test/other_project",
                    started_at=0.0,
                )
            ]
        )

        attr = h._attribute(Path("/tmp/test_ws/foo.py"))

        self.assertEqual(attr.agent, "codex")
        self.assertEqual(attr.detection_method, "global_cli_fallback")
        self.assertLess(attr.confidence, 0.95)
        self.assertGreater(attr.confidence, 0.0)

    def test_global_multi_agent_fallback_is_unknown_with_candidates(self):
        """全局回退有多个候选时不能随便归给第一个 agent。"""
        h, _ = make_handler(active_agents=[])
        h._scan_global_for_test = MagicMock(
            return_value=[
                AgentInstance(
                    name="claude",
                    display_name="Claude Code",
                    category="cli",
                    pid=901,
                    cwd="/Users/test/other_project",
                    started_at=0.0,
                ),
                AgentInstance(
                    name="codex",
                    display_name="Codex CLI",
                    category="cli",
                    pid=902,
                    cwd="/Users/test/other_project",
                    started_at=0.0,
                ),
                AgentInstance(
                    name="codex",
                    display_name="Codex CLI",
                    category="cli",
                    pid=903,
                    cwd="/Users/test/another_project",
                    started_at=0.0,
                ),
            ]
        )

        attr = h._attribute(Path("/tmp/test_ws/foo.py"))

        self.assertEqual(attr.agent, "unknown")
        self.assertEqual(attr.detection_method, "global_cli_fallback")
        self.assertTrue(attr.ambiguous)
        self.assertEqual(attr.candidates, ["claude", "codex"])

    def test_workspace_multi_agent_is_unknown_with_candidates(self):
        """同一 workspace 里多个 agent 活跃时，不能把第一个候选当确定作者。"""
        h, _ = make_handler(
            active_agents=[
                AgentInstance(
                    name="codex",
                    display_name="Codex CLI",
                    category="cli",
                    pid=901,
                    cwd="/tmp/test_ws",
                    started_at=0.0,
                ),
                AgentInstance(
                    name="claude",
                    display_name="Claude Code",
                    category="cli",
                    pid=902,
                    cwd="/tmp/test_ws",
                    started_at=0.0,
                ),
            ]
        )

        attr = h._attribute(Path("/tmp/test_ws/foo.xlsx"))

        self.assertEqual(attr.agent, "unknown")
        self.assertEqual(attr.detection_method, "weighted_ambiguous")
        self.assertTrue(attr.ambiguous)
        self.assertEqual(attr.candidates, ["codex", "claude"])

    def test_transcript_evidence_beats_workspace_multi_agent_ambiguity(self):
        """有 transcript 直接证据时，应归给实际写入的 agent，而不是显示多候选。"""
        h, _ = make_handler(
            active_agents=[
                AgentInstance(
                    name="codex",
                    display_name="Codex CLI",
                    category="cli",
                    pid=901,
                    cwd="/tmp/test_ws",
                    started_at=0.0,
                ),
                AgentInstance(
                    name="claude",
                    display_name="Claude Code",
                    category="cli",
                    pid=902,
                    cwd="/tmp/test_ws",
                    started_at=0.0,
                ),
            ]
        )
        h._transcript_for_test = MagicMock(
            return_value=AgentAttribution(
                agent="claude",
                confidence=0.93,
                detection_method="claude_transcript",
            )
        )

        attr = h._attribute(Path("/tmp/test_ws/foo.xlsx"))

        self.assertEqual(attr.agent, "claude")
        self.assertEqual(attr.detection_method, "claude_transcript")
        self.assertGreaterEqual(attr.confidence, 0.9)
        self.assertFalse(attr.ambiguous)


if __name__ == "__main__":
    unittest.main(verbosity=2)
