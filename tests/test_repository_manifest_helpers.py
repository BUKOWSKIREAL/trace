import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from core.repository import Repository
from models.agent import AgentAttribution
from models.change import Change


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(
        file_path=path,
        event_time=time.time(),
        attribution=AgentAttribution(agent=agent, confidence=0.95),
        kind=kind,
    )


class RepositoryManifestHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.ws = Path(self._tmp.name)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_prev_commit_id_returns_none_before_any_commit(self):
        self.assertIsNone(self.repo.get_prev_commit_id(1))

    def test_get_manifest_and_prev_commit_id_across_two_commits(self):
        a = self.ws / "a.txt"
        a.write_text("one", encoding="utf-8")
        c1 = self.repo.commit("human", [make_change(a)])

        a.write_text("two", encoding="utf-8")
        c2 = self.repo.commit("human", [make_change(a)])

        self.assertIsNone(self.repo.get_prev_commit_id(c1))
        self.assertEqual(self.repo.get_prev_commit_id(c2), c1)

        manifest1 = self.repo.get_manifest(c1)
        manifest2 = self.repo.get_manifest(c2)
        self.assertEqual({row["file_path"] for row in manifest1}, {"a.txt"})
        self.assertEqual({row["file_path"] for row in manifest2}, {"a.txt"})
        self.assertNotEqual(
            next(r["blob_hash"] for r in manifest1 if r["file_path"] == "a.txt"),
            next(r["blob_hash"] for r in manifest2 if r["file_path"] == "a.txt"),
        )


if __name__ == "__main__":
    unittest.main()
