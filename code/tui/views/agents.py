"""AgentsView — per-agent stats and a list of registered agents."""
from __future__ import annotations

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Label, ListItem, ListView, Static


class RevertConfirmModal(ModalScreen[bool]):
    """Shows how many files an agent-revert will change before applying it."""

    def __init__(self, agent: str, changed_count: int, controller) -> None:
        super().__init__()
        self._agent = agent
        self.changed_count = changed_count
        self._controller = controller

    def compose(self) -> ComposeResult:
        with Vertical(id="revert-modal"):
            yield Label(
                Text(f"Revert all changes by '{self._agent}'? "
                     f"{self.changed_count} file(s) will change.")
            )
            with Horizontal():
                yield Button("Revert", id="confirm", variant="error")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.run_worker(self.confirm())
        else:
            self.dismiss(False)

    async def confirm(self) -> None:
        result = self._controller.revert_agent(self._agent)
        self.dismiss(bool(result.get("ok")))


class AgentsView(Widget):
    BINDINGS = [("r", "revert_highlighted_agent", "Revert agent")]

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

    async def action_revert_highlighted_agent(self) -> None:
        item = self.agent_list.highlighted_child
        if item is None or item.id is None:
            return
        agent = item.id.removeprefix("agentrow-")
        await self.action_revert_agent(agent)

    async def action_revert_agent(self, agent: str) -> None:
        preview = self._controller.preview_revert_agent(agent)
        if not preview.get("ok"):
            return
        changed_count = len(preview["preview"].get("changed_paths", []))
        modal = RevertConfirmModal(agent, changed_count, self._controller)
        await self.app.push_screen(modal)
