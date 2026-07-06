import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.app import App, ComposeResult

from core.repository import Repository
from models.agent import AgentAttribution
from models.change import Change
from tui.controller import TraceController
from tui.views.agents import AgentsView


def make_change(path: Path, kind: str = "upsert", agent: str = "human") -> Change:
    return Change(path, time.time(), AgentAttribution(agent=agent, confidence=0.95), kind)


class _Harness(App):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        yield AgentsView(self._controller)


class AgentsViewBehavior(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name).resolve()
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_lists_agents_and_reports_active_count(self):
        a = self.ws / "a.txt"
        a.write_text("1", encoding="utf-8")
        self.repo.commit("claude", [make_change(a, agent="claude")])

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(AgentsView)
            await view.refresh_agents()
            await pilot.pause()
            # one active agent (claude, 1 commit), several registered
            self.assertEqual(view.active_count, 1)
            self.assertGreaterEqual(len(view.agent_list.children), 5)


if __name__ == "__main__":
    unittest.main()
