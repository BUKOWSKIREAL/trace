import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from core.repository import Repository
from tui.controller import TraceController


class _BoomRepo:
    """Every method raises, to exercise the error-wrapping contract."""

    def list_commits(self, limit=50):
        raise RuntimeError("boom")

    def restore_file(self, commit_id, file_path, backup_current=True):
        raise RuntimeError("boom")

    def reassign_commit(self, commit_id, new_agent):
        raise RuntimeError("boom")

    def preview_revert_agent(self, agent):
        raise RuntimeError("boom")

    def revert_agent(self, agent, backup_current=True):
        raise RuntimeError("boom")


class TraceControllerHappyPath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_commits_ok_on_fresh_repo(self):
        result = self.controller.list_commits()
        self.assertTrue(result["ok"])
        self.assertEqual(result["commits"], [])

    def test_get_diff_returns_line_list(self):
        result = self.controller.get_diff("hello.txt", None, None)
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["lines"], list)


class TraceControllerErrorContract(unittest.TestCase):
    def setUp(self):
        self.controller = TraceController(_BoomRepo(), Path("/tmp"))

    def test_list_commits_wraps_error(self):
        result = self.controller.list_commits()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")

    def test_restore_file_wraps_error(self):
        result = self.controller.restore_file(1, "x.txt")
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])


if __name__ == "__main__":
    unittest.main()
