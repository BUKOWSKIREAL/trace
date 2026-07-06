"""
utils.state + main.resolve_workspace 单元测试
================================================
锁定工作区四段解析逻辑：CLI --workspace > --choose > 上次记忆沉默用 > 弹 picker.

# 人工编写（5/21 审计后补：把对话里跑过的 5 个 inline 场景固化）
"""
import argparse
import importlib
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))


def _reload_state_module_with_home(fake_home: str):
    """让 utils.state 在 fake HOME 下重新计算 state_dir。"""
    os.environ["HOME"] = fake_home
    import utils.state as state_mod
    importlib.reload(state_mod)
    return state_mod


class TestStatePersistence(unittest.TestCase):

    def setUp(self):
        self._real_home = os.environ.get("HOME")

    def tearDown(self):
        if self._real_home is not None:
            os.environ["HOME"] = self._real_home

    def test_no_state_returns_none(self):
        with tempfile.TemporaryDirectory() as fake_home:
            state = _reload_state_module_with_home(fake_home)
            self.assertIsNone(state.load_last_workspace())

    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as fake_home, \
                tempfile.TemporaryDirectory() as ws:
            state = _reload_state_module_with_home(fake_home)
            state.save_last_workspace(Path(ws))
            self.assertEqual(state.load_last_workspace(),
                             Path(ws).resolve())

    def test_missing_directory_ignored(self):
        """上次工作区目录已被挪走时返回 None（不卡在无效路径上）。"""
        with tempfile.TemporaryDirectory() as fake_home:
            state = _reload_state_module_with_home(fake_home)
            with tempfile.TemporaryDirectory() as ephemeral_ws:
                state.save_last_workspace(Path(ephemeral_ws))
            # 出了 with，ephemeral_ws 已被删
            self.assertIsNone(state.load_last_workspace(),
                              "已删的工作区不应被返回")

    def test_state_dir_path_format_macos(self):
        """macOS 上 state_dir 应在 ~/Library/Application Support/Trace/。"""
        if sys.platform != "darwin":
            self.skipTest("仅 macOS")
        with tempfile.TemporaryDirectory() as fake_home:
            state = _reload_state_module_with_home(fake_home)
            sd = state.state_dir()
            self.assertIn("Library/Application Support/Trace", str(sd))


class TestResolveWorkspace(unittest.TestCase):
    """main.resolve_workspace 的四段优先级。"""

    def setUp(self):
        self._real_home = os.environ.get("HOME")
        # 用临时 HOME 避免污染真实 state
        self._fake_home = tempfile.mkdtemp(prefix="trace_test_home_")
        os.environ["HOME"] = self._fake_home

        import utils.state as state_mod
        importlib.reload(state_mod)
        self.state_mod = state_mod

        import main as main_mod
        importlib.reload(main_mod)
        self.main_mod = main_mod

        self.log = logging.getLogger("test")
        self.log.addHandler(logging.NullHandler())

    def tearDown(self):
        if self._real_home is not None:
            os.environ["HOME"] = self._real_home
        # 清理临时 home
        import shutil
        shutil.rmtree(self._fake_home, ignore_errors=True)

    def _args(self, workspace=None, choose=False):
        return argparse.Namespace(
            workspace=workspace, choose=choose, verbose=False)

    def test_explicit_workspace_wins(self):
        with tempfile.TemporaryDirectory() as td:
            out = self.main_mod.resolve_workspace(
                self._args(workspace=Path(td)), self.log)
            self.assertEqual(out, Path(td).resolve())

    def test_explicit_workspace_nonexistent_returns_none(self):
        out = self.main_mod.resolve_workspace(
            self._args(workspace=Path("/totally/does/not/exist")), self.log)
        self.assertIsNone(out)

    def test_last_memory_used_silently(self):
        with tempfile.TemporaryDirectory() as td:
            self.state_mod.save_last_workspace(Path(td))
            out = self.main_mod.resolve_workspace(self._args(), self.log)
            self.assertEqual(out, Path(td).resolve())

    def test_choose_flag_invokes_picker(self):
        with tempfile.TemporaryDirectory() as chosen:
            with patch.object(
                self.main_mod,
                "_pick_workspace",
                return_value=Path(chosen),
            ) as mock_picker:
                out = self.main_mod.resolve_workspace(
                    self._args(choose=True), self.log)
                self.assertEqual(out.resolve(), Path(chosen).resolve())
                mock_picker.assert_called_once()

    def test_picker_cancelled_returns_none(self):
        """用户在 picker 里点取消 → resolve 返 None → main 优雅退出。"""
        with patch.object(self.main_mod, "_pick_workspace", return_value=None):
            out = self.main_mod.resolve_workspace(
                self._args(choose=True), self.log)
            self.assertIsNone(out)

    def test_no_memory_no_args_invokes_picker(self):
        """既没 --workspace 也没记忆 → 自动弹 picker。"""
        with tempfile.TemporaryDirectory() as chosen:
            with patch.object(
                self.main_mod,
                "_pick_workspace",
                return_value=Path(chosen),
            ) as mock_picker:
                out = self.main_mod.resolve_workspace(self._args(), self.log)
                self.assertEqual(out.resolve(), Path(chosen).resolve())
                mock_picker.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
