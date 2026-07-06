import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from core.repository import Repository
from models.agent import AgentAttribution
from models.change import Change
from tui.controller import TraceController


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(
        file_path=path,
        event_time=time.time(),
        attribution=AgentAttribution(agent=agent, confidence=0.95),
        kind=kind,
    )


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

    def list_agents(self):
        raise RuntimeError("boom")

    def workspace_summary(self):
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


class TraceControllerCommitDiff(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_commit_shows_all_files_as_new(self):
        a = self.ws / "a.txt"
        a.write_text("hello\n", encoding="utf-8")
        c1 = self.repo.commit("human", [make_change(a)])

        result = self.controller.get_commit_diff(c1)
        self.assertTrue(result["ok"])
        files = result["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["path"], "a.txt")
        self.assertEqual(files[0]["status"], "new")
        self.assertTrue(files[0]["can_restore"])
        self.assertIsInstance(files[0]["lines"], list)

    def test_second_commit_shows_modified_and_marks_deleted_not_restorable(self):
        a = self.ws / "a.txt"
        b = self.ws / "b.txt"
        a.write_text("one\n", encoding="utf-8")
        b.write_text("keep me\n", encoding="utf-8")
        self.repo.commit("human", [make_change(a), make_change(b)])

        a.write_text("two\n", encoding="utf-8")
        b.unlink()
        c2 = self.repo.commit("human", [make_change(a), make_change(b, kind="delete")])

        result = self.controller.get_commit_diff(c2)
        self.assertTrue(result["ok"])
        by_path = {f["path"]: f for f in result["files"]}
        self.assertEqual(by_path["a.txt"]["status"], "modified")
        self.assertTrue(by_path["a.txt"]["can_restore"])
        self.assertEqual(by_path["b.txt"]["status"], "deleted")
        self.assertFalse(by_path["b.txt"]["can_restore"])

    def test_unchanged_files_are_excluded(self):
        a = self.ws / "a.txt"
        b = self.ws / "b.txt"
        a.write_text("one\n", encoding="utf-8")
        b.write_text("stays the same\n", encoding="utf-8")
        self.repo.commit("human", [make_change(a), make_change(b)])

        a.write_text("two\n", encoding="utf-8")
        c2 = self.repo.commit("human", [make_change(a)])

        result = self.controller.get_commit_diff(c2)
        paths = {f["path"] for f in result["files"]}
        self.assertEqual(paths, {"a.txt"})

    def test_truncates_long_diffs_at_800_lines(self):
        a = self.ws / "a.txt"
        a.write_text("\n".join(str(i) for i in range(5)), encoding="utf-8")
        self.repo.commit("human", [make_change(a)])

        a.write_text("\n".join(str(i) for i in range(2000)), encoding="utf-8")
        c2 = self.repo.commit("human", [make_change(a)])

        result = self.controller.get_commit_diff(c2)
        lines = result["files"][0]["lines"]
        self.assertEqual(len(lines), 801)  # 800 real lines + 1 truncation marker
        self.assertIn("truncated", lines[-1]["text"])

    def test_unknown_commit_id_returns_empty_file_list(self):
        result = self.controller.get_commit_diff(999)
        self.assertTrue(result["ok"])
        self.assertEqual(result["files"], [])


class TraceControllerAgentsWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name).resolve()
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_agents_ok(self):
        result = self.controller.list_agents()
        self.assertTrue(result["ok"])
        self.assertTrue(any(a["name"] == "claude" for a in result["agents"]))

    def test_get_workspace_summary_ok(self):
        result = self.controller.get_workspace_summary()
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["workspace"], str(self.ws))

    def test_list_agents_wraps_error(self):
        controller = TraceController(_BoomRepo(), Path("/tmp"))
        result = controller.list_agents()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")


if __name__ == "__main__":
    unittest.main()
