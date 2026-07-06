import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from daemon import ipc  # noqa: E402


class TestIPC(unittest.TestCase):
    def setUp(self):
        while True:
            try:
                ipc.ui_queue.get_nowait()
            except Exception:
                break

    def test_emit_and_drain(self):
        ipc.emit("new_commit", commit_id=7, agent="claude")
        events = ipc.drain()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "new_commit")
        self.assertEqual(events[0].payload["commit_id"], 7)


if __name__ == "__main__":
    unittest.main()
