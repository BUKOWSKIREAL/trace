import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).parent.parent
ROOT = PROJECT / "code"
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(ROOT))

from core.repository import Repository  # noqa: E402
from models.agent import AgentAttribution  # noqa: E402
from models.change import Change  # noqa: E402
from tests._tempdir import temp_dir  # noqa: E402


class TestReassignAndRevert(unittest.TestCase):
    def setUp(self):
        self._temp = temp_dir()
        self.ws = self._temp.__enter__()
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()

    def tearDown(self):
        self._temp.__exit__(None, None, None)

    def _commit_text(self, rel: str, content: str, agent: str) -> int:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        commit_id = self.repo.commit(
            agent=agent,
            changes=[
                Change(
                    file_path=path,
                    event_time=1.0,
                    attribution=AgentAttribution(agent=agent, confidence=0.9),
                    kind="upsert",
                )
            ],
        )
        assert commit_id is not None
        return commit_id

    def test_reassign_commit_updates_metadata_only(self):
        cid = self._commit_text("a.txt", "v1", "unknown")
        self.repo.reassign_commit(cid, "claude")
        row = self.repo.list_commits(limit=1)[0]
        self.assertEqual(row["author_agent"], "claude")
        self.assertEqual(row["detection_method"], "manual_reassign")

    def test_revert_agent_removes_only_target_agent_changes(self):
        self._commit_text("a.txt", "human", "human")
        self._commit_text("a.txt", "claude", "claude")
        self._commit_text("b.txt", "codex", "codex")
        preview = self.repo.preview_revert_agent("claude")
        self.assertIn("a.txt", preview["changed_paths"])
        revert_id = self.repo.revert_agent("claude", backup_current=False)
        self.assertIsInstance(revert_id, int)
        head = self.repo.list_commits(limit=1)[0]
        self.assertEqual(head["detection_method"], "revert_agent")
        self.assertEqual((self.ws / "a.txt").read_text(encoding="utf-8"), "human")
        self.assertEqual((self.ws / "b.txt").read_text(encoding="utf-8"), "codex")

    def test_reconcile_offline_changes(self):
        self._commit_text("a.txt", "v1", "human")
        (self.ws / "a.txt").write_text("offline-edit", encoding="utf-8")
        commit_id = self.repo.reconcile_offline_changes()
        self.assertIsNotNone(commit_id)
        row = self.repo.list_commits(limit=1)[0]
        self.assertEqual(row["detection_method"], "offline_reconcile")


if __name__ == "__main__":
    unittest.main()
