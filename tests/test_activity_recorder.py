import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from daemon.activity_recorder import (  # noqa: E402
    ActivityStore,
    AgentActivityRecorder,
    WriteActivityEvent,
    parse_fs_usage_line,
)


class TestActivityStore(unittest.TestCase):
    def test_query_returns_matching_path_in_window(self):
        store = ActivityStore(max_age=60)
        path = Path("/tmp/ws/a.txt")
        now = time.time()
        store.record(
            WriteActivityEvent(
                timestamp=now,
                pid=1,
                agent="claude",
                path=path,
                op="write",
                source="psutil_poll",
                confidence=0.8,
            )
        )
        hits = store.query(path, now - 1, now + 1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].agent, "claude")


class TestAgentActivityRecorder(unittest.TestCase):
    def test_resolve_single_agent(self):
        recorder = AgentActivityRecorder(Path("/tmp/ws"))
        now = time.time()
        recorder.store.record(
            WriteActivityEvent(
                timestamp=now,
                pid=1,
                agent="codex",
                path=Path("/tmp/ws/file.py"),
                op="write",
                source="fs_usage",
                confidence=0.98,
            )
        )
        attr = recorder.resolve(Path("/tmp/ws/file.py"), now)
        self.assertIsNotNone(attr)
        self.assertEqual(attr.agent, "codex")
        self.assertEqual(attr.detection_method, "activity_fs_usage")


class TestFsUsageParser(unittest.TestCase):
    def test_parse_write_line(self):
        ws = Path("/tmp/project")
        line = "18:00:01.123456  WRITE  4321  0  0 /tmp/project/readme.md"
        event = parse_fs_usage_line(line, ws)
        self.assertIsNotNone(event)
        self.assertEqual(event.path, Path("/tmp/project/readme.md"))
        self.assertEqual(event.path, Path("/tmp/project/readme.md"))


if __name__ == "__main__":
    unittest.main()
