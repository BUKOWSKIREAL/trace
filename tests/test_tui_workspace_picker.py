import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree

from tui.views.workspace import WorkspacePickerScreen

def _populate(parent: Path) -> tuple[Path, Path, Path]:
    dir_a = parent / "alpha"
    dir_b = parent / "beta"
    file_c = parent / "gamma.txt"
    dir_a.mkdir()
    dir_b.mkdir()
    file_c.write_text("hi", encoding="utf-8")
    return dir_a, dir_b, file_c


class _Harness(App):
    def __init__(self, initial: Path | None = None):
        super().__init__()
        self._initial = initial
        self.picked: list[Path | None] = []

    def compose(self) -> ComposeResult:
        yield DirectoryTree("/tmp")  # placeholder; replaced on mount

    async def on_mount(self) -> None:
        await self.push_screen(WorkspacePickerScreen(initial=self._initial), self.picked.append)


class WorkspacePickerScreenBehavior(unittest.IsolatedAsyncioTestCase):
    def _find_node(self, tree: DirectoryTree, target: Path):
        from textual.widgets._tree import TreeNode

        target_resolved = Path(target).resolve()

        def _walk(node: TreeNode):
            node_path = getattr(getattr(node, "data", None), "path", None)
            if node_path is not None and Path(node_path).resolve() == target_resolved:
                return node
            for child in (node.children or []):
                found = _walk(child)
                if found is not None:
                    return found
            return None

        return _walk(tree.root)

    async def test_open_dismisses_with_selected_directory(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            dir_a, _, _ = _populate(parent)

            app = _Harness(initial=parent)
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, WorkspacePickerScreen)
                tree = screen.query_one(DirectoryTree)
                await pilot.pause()
                alpha_node = self._find_node(tree, dir_a)
                self.assertIsNotNone(alpha_node, "alpha dir not loaded into tree")
                tree.move_cursor(alpha_node)
                await pilot.pause()
                # Drive the tree's own select action so it emits DirectorySelected.
                tree.action_select_cursor()
                await pilot.pause()
                screen.action_open()
                await pilot.pause()

            self.assertEqual(len(app.picked), 1)
            self.assertEqual(app.picked[0], Path(dir_a).resolve())

    async def test_cancel_dismisses_with_none(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            _populate(parent)

            app = _Harness(initial=parent)
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                screen.action_cancel()
                await pilot.pause()

            self.assertEqual(app.picked, [None])

    async def test_selecting_file_does_not_open(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            _, _, file_c = _populate(parent)

            app = _Harness(initial=parent)
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                tree = screen.query_one(DirectoryTree)
                await pilot.pause()
                file_node = self._find_node(tree, file_c)
                self.assertIsNotNone(file_node, "file node not loaded into tree")
                tree.move_cursor(file_node)
                await pilot.pause()
                tree.action_select_cursor()
                await pilot.pause()
                # selected should NOT be the file (the screen filters file nodes)
                self.assertIsNone(screen.selected)
                screen.action_open()
                await pilot.pause()
                # screen still mounted because there is nothing to open
                self.assertIsInstance(app.screen, WorkspacePickerScreen)

            self.assertEqual(app.picked, [])

    async def test_initial_defaults_to_home(self):
        app = _Harness(initial=None)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            tree = screen.query_one(DirectoryTree)
            root_path = screen.root_path
            self.assertEqual(root_path, Path.home())


if __name__ == "__main__":
    unittest.main()
