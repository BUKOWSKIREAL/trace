import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.app import App, ComposeResult

from core.repository import Repository
from tui.controller import TraceController
from tui.views.mcp import InstallResultModal, MCPView


class _Harness(App):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        yield MCPView(self._controller)


class MCPViewBehavior(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.ws = Path(self._tmp.name).resolve()
        self.ws.mkdir(exist_ok=True)
        self.repo = Repository(self.ws)
        self.repo.init_if_needed()
        self.controller = TraceController(self.repo, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_lists_four_agent_rows(self):
        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(MCPView)
            await view.refresh_setup()
            await pilot.pause()
            self.assertEqual(len(view.mcp_list.children), 4)
            self.assertIn("codex", view._rows_by_id)
            self.assertIn("other", view._rows_by_id)

    async def test_install_other_agent_informs_user_no_modal(self):
        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(MCPView)
            await view.refresh_setup()
            await pilot.pause()

            await view.action_install_for_id("other")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, InstallResultModal)

    async def test_install_codex_writes_config_and_shows_modal(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home_dir:
            with patch.object(Path, "home", return_value=Path(home_dir)):
                app = _Harness(self.controller)
                async with app.run_test() as pilot:
                    view = app.query_one(MCPView)
                    await view.refresh_setup()
                    await pilot.pause()

                    await view.action_install_for_id("codex")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, InstallResultModal)
                    codex_dir = Path(home_dir) / ".codex"
                    self.assertTrue((codex_dir / "config.toml").exists())
                    self.assertTrue((codex_dir / "hooks.json").exists())

    async def test_copy_command_uses_clipboard(self):
        captured = {"text": None}
        notices: list[str] = []

        # App.copy_to_clipboard 是同步 API——fake 必须也是同步的，
        # 否则会掩盖生产代码里错误 await 的回归。
        def _fake_clipboard(text):
            captured["text"] = text

        app = _Harness(self.controller)
        async with app.run_test() as pilot:
            view = app.query_one(MCPView)
            await view.refresh_setup()
            await pilot.pause()

            # Highlight the first row (codex) so action_copy_command has a target.
            view.mcp_list.index = 0
            await pilot.pause()
            with (
                patch.object(app, "copy_to_clipboard", side_effect=_fake_clipboard),
                patch.object(
                    app, "notify", side_effect=lambda msg, **kw: notices.append(str(msg))
                ),
            ):
                await view.action_copy_command()
                await pilot.pause()

            self.assertIsNotNone(captured["text"])
            self.assertIn("codex", captured["text"])
            self.assertTrue(notices and notices[0].startswith("copied"), notices)


if __name__ == "__main__":
    unittest.main()
