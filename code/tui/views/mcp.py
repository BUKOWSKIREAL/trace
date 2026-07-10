"""MCPView — one row per agent showing MCP install state, with install/copy actions."""
from __future__ import annotations

import asyncio

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Label, ListItem, ListView, Static


class InstallResultModal(ModalScreen[bool]):
    """Shows the install outcome (config path / restart hint) with an OK button."""

    def __init__(self, server_id: str, result: dict) -> None:
        super().__init__()
        self._server_id = server_id
        self._result = result

    def compose(self) -> ComposeResult:
        with Vertical(id="mcp-result-modal"):
            yield Label(Text(self._summary()))
            yield Button("OK", id="ok")

    def _summary(self) -> str:
        if not self._result.get("ok"):
            err = self._result.get("error") or "install failed"
            return f"[{self._server_id}] failed: {err}"
        parts = [f"[{self._server_id}] installed."]
        if self._result.get("already_installed"):
            parts = [f"[{self._server_id}] already installed."]
        if self._result.get("config_path"):
            parts.append(f"config: {self._result['config_path']}")
        if self._result.get("hook_path"):
            parts.append(f"hooks:  {self._result['hook_path']}")
        if self._result.get("restart_required"):
            parts.append("restart the agent to apply.")
        if self._result.get("approval_required"):
            parts.append("approve the MCP server once in the agent UI.")
        return "  ".join(parts)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(bool(self._result.get("ok")))


class MCPView(Widget):
    """Lists each agent's MCP install state; supports install (i) and copy (c)."""

    BINDINGS = [
        ("i", "install_highlighted", "Install"),
        ("c", "copy_command", "Copy command"),
    ]

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self._rows_by_id: dict[str, dict] = {}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="mcp-stats")
            with VerticalScroll():
                yield ListView(id="mcp-list")

    @property
    def mcp_list(self) -> ListView:
        return self.query_one("#mcp-list", ListView)

    async def on_mount(self) -> None:
        if self._controller is None:
            return
        await self.refresh_setup()

    async def refresh_setup(self) -> None:
        if self._controller is None:
            return
        result = self._controller.list_mcp_setup()
        rows = result.get("rows", []) if result.get("ok") else []
        self._rows_by_id = {row["id"]: row for row in rows}

        installed = sum(1 for r in rows if r.get("installed"))
        self.query_one("#mcp-stats", Static).update(
            Text(f"agents: {len(rows)}   installed: {installed}")
        )

        list_view = self.mcp_list
        await list_view.clear()
        for row in rows:
            name = row.get("name", "?")
            label_txt = row.get("status_label", "")
            prefix = row.get("command_prefix") or "manual"
            label = f"{name}  ·  {label_txt}  ·  {prefix}"
            await list_view.append(ListItem(Label(Text(label)), id=f"mcprow-{row['id']}"))

    async def action_install_highlighted(self) -> None:
        item = self.mcp_list.highlighted_child
        if item is None or item.id is None:
            return
        server_id = item.id.removeprefix("mcprow-")
        await self.action_install_for_id(server_id)

    async def action_install_for_id(self, server_id: str) -> None:
        row = self._rows_by_id.get(server_id)
        if row is None:
            return
        if not row.get("can_auto_install"):
            self.app.notify(
                f"'{row.get('name', server_id)}' does not support one-click install — copy the command instead.",
                severity="warning",
            )
            return
        # install 里可能有最长 20s 的子进程调用（claude mcp add），放线程池免得冻住 UI
        result = await asyncio.to_thread(
            self._controller.install_mcp_server, server_id
        )
        await self.refresh_setup()
        await self.app.push_screen(InstallResultModal(server_id, result))

    async def action_copy_command(self) -> None:
        item = self.mcp_list.highlighted_child
        if item is None or item.id is None:
            return
        server_id = item.id.removeprefix("mcprow-")
        row = self._rows_by_id.get(server_id)
        if row is None:
            return
        command = row.get("command", "")
        try:
            self.app.copy_to_clipboard(command)
            self.app.notify(f"copied: {command[:60]}{'…' if len(command) > 60 else ''}")
        except Exception as exc:  # noqa: BLE001 - clipboard may be unavailable on some platforms
            self.app.notify(f"copy failed: {exc}", severity="error")
