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


class RepositoryAgentsWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.ws = Path(self._tmp.name).resolve()
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_agents_includes_presets_with_zero_counts(self):
        agents = self.repo.list_agents()
        by_name = {a["name"]: a for a in agents}
        self.assertIn("claude", by_name)
        self.assertIn("codex", by_name)
        self.assertEqual(by_name["claude"]["commit_count"], 0)
        self.assertEqual(by_name["claude"]["display_name"], "Claude Code")

    def test_list_agents_counts_commits_and_orders_by_count_desc(self):
        a = self.ws / "a.txt"
        a.write_text("1", encoding="utf-8")
        self.repo.commit("claude", [make_change(a, agent="claude")])
        a.write_text("2", encoding="utf-8")
        self.repo.commit("claude", [make_change(a, agent="claude")])

        agents = self.repo.list_agents()
        self.assertEqual(agents[0]["name"], "claude")
        self.assertEqual(agents[0]["commit_count"], 2)
        self.assertIsNotNone(agents[0]["last_time"])

    def test_workspace_summary_reports_counts_and_paths(self):
        a = self.ws / "a.txt"
        a.write_text("1", encoding="utf-8")
        self.repo.commit("human", [make_change(a)])

        summary = self.repo.workspace_summary()
        self.assertEqual(summary["workspace"], str(self.ws))
        self.assertTrue(summary["db_path"].endswith("trace.db"))
        self.assertEqual(summary["commit_count"], 1)
        self.assertGreaterEqual(summary["snapshot_count"], 1)
        self.assertGreaterEqual(summary["agent_count"], 1)


if __name__ == "__main__":
    unittest.main()
