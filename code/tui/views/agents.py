"""AgentsView — per-agent stats and a list of registered agents."""
from __future__ import annotations

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static


class AgentsView(Widget):
    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self._agents: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="agents-stats")
            yield ListView(id="agent-list")

    @property
    def agent_list(self) -> ListView:
        return self.query_one("#agent-list", ListView)

    @property
    def active_count(self) -> int:
        return sum(1 for a in self._agents if a.get("commit_count", 0) > 0)

    async def on_mount(self) -> None:
        await self.refresh_agents()

    async def refresh_agents(self) -> None:
        result = self._controller.list_agents()
        self._agents = result.get("agents", []) if result.get("ok") else []

        total_commits = sum(a.get("commit_count", 0) for a in self._agents)
        self.query_one("#agents-stats", Static).update(
            Text(
                f"commits: {total_commits}   active: {self.active_count}   "
                f"registered: {len(self._agents)}"
            )
        )

        list_view = self.agent_list
        await list_view.clear()
        for agent in self._agents:
            name = agent.get("name", "unknown")
            display = agent.get("display_name", name)
            count = agent.get("commit_count", 0)
            last = agent.get("last_time") or "never"
            label = f"{display} ({name})  ·  {count} commits  ·  last {last}"
            await list_view.append(ListItem(Label(Text(label)), id=f"agentrow-{name}"))
