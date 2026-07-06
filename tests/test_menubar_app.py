"""
TraceApp 业务层测试
====================
TraceApp 把 Tray、daemon、ipc 三者粘起来：构建菜单、定时刷新标题、
处理菜单点击回调。

测试策略：用 mock 注入 tray + scan_agents，避免依赖真实 NSApplication
和 psutil 系统调用。

# 人工编写（TDD：测试先于实现）
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from menubar.app import (  # noqa: E402
    ElectronLaunch,
    TraceApp,
    _bundled_electron_executable,
    _choose_workspace_for_menubar,
    _electron_bridge_env,
    _launch_electron_process,
)
from models.agent import AgentInstance  # noqa: E402


def make_electron_launch(proc=None, *, external=False):
    if proc is None:
        proc = MagicMock()
    return ElectronLaunch(proc=proc, external=external)


def make_app(
    forced_agent=None,
    paused=False,
    active_agents=None,
    electron_launcher=None,
    workspace_picker=None,
):
    """构造一个完全 mocked TraceApp 用于测试。"""
    tray = MagicMock()
    scan = MagicMock(return_value=active_agents or [])
    daemon = MagicMock()
    daemon.workspace = Path("/tmp/test_ws")
    daemon.repo = MagicMock()
    daemon.batcher = MagicMock()
    daemon.observer = MagicMock()
    daemon.handler = MagicMock()
    app = TraceApp(
        daemon=daemon,
        tray=tray,
        scan_agents=scan,
        electron_launcher=electron_launcher,
        workspace_picker=workspace_picker,
    )
    app._paused = paused
    app._forced_agent = forced_agent
    return app, tray, scan


class TestTraceAppInit(unittest.TestCase):
    def test_uses_injected_tray(self):
        app, tray, _ = make_app()
        self.assertIs(app.tray, tray)

    def test_initial_state(self):
        app, _, _ = make_app()
        self.assertFalse(app._paused)
        self.assertIsNone(app._forced_agent)

    def test_default_tray_uses_icon_without_title(self):
        daemon = MagicMock()
        daemon.workspace = Path("/tmp/test_ws")
        with patch("menubar.app.make_tray") as mock_make_tray:
            TraceApp(daemon=daemon)
        (name,) = mock_make_tray.call_args.args
        self.assertEqual(name, "")
        self.assertEqual(mock_make_tray.call_args.kwargs["icon_path"].name, "icon.png")


class TestTraceAppStart(unittest.TestCase):
    def test_start_builds_menu_schedules_poll_timer_and_runs(self):
        launcher = MagicMock(return_value=make_electron_launch())
        app, tray, _ = make_app(electron_launcher=launcher)
        app.start()
        tray.set_menu.assert_called_once()
        self.assertEqual(tray.schedule_periodic.call_count, 1)
        launcher.assert_called_once_with(app.workspace)
        tray.run.assert_called_once()

    def test_start_auto_launches_electron(self):
        launcher = MagicMock(return_value=make_electron_launch())
        app, _, _ = make_app(electron_launcher=launcher)
        app.start()
        launcher.assert_called_once_with(app.workspace)
        self.assertIsNone(app._electron_proc)

    def test_start_stops_electron_on_exit(self):
        proc = MagicMock()
        proc.pid = 999
        proc.poll.return_value = None
        launcher = MagicMock(return_value=make_electron_launch(proc))
        app, tray, _ = make_app(electron_launcher=launcher)
        tray.run.side_effect = lambda: None
        with patch("menubar.app._terminate_process_tree") as mock_stop:
            app.start()
        mock_stop.assert_called_once_with(proc)
        self.assertIsNone(app._electron_proc)

    def test_on_quit_stops_electron(self):
        proc = MagicMock()
        proc.poll.return_value = None
        app, _, _ = make_app()
        app._electron_proc = proc
        with patch.object(app, "_stop_electron") as mock_stop:
            app.on_quit()
        mock_stop.assert_called_once()

    def test_quit_menu_item_has_callback(self):
        app, _, _ = make_app()
        menu = app._build_menu()
        self.assertEqual(menu[-1].get("callback"), app.on_quit)


class TestTraceAppMenuStructure(unittest.TestCase):
    @staticmethod
    def _labels(menu_items):
        return [item.get("label") for item in menu_items if "label" in item]

    def test_menu_has_change_workspace(self):
        app, _, _ = make_app()
        menu = app._build_menu()
        self.assertIn("更换工作区...", self._labels(menu))

    def test_menu_pause_label_when_running(self):
        app, _, _ = make_app(paused=False)
        menu = app._build_menu()
        self.assertIn("暂停跟踪", self._labels(menu))

    def test_menu_continue_label_when_paused(self):
        app, _, _ = make_app(paused=True)
        menu = app._build_menu()
        self.assertIn("继续跟踪", self._labels(menu))

    def test_menu_has_agent_radios_for_supported_cli_agents(self):
        app, _, _ = make_app()
        menu = app._build_menu()
        radios = [item for item in menu if item.get("type") == "radio"]
        self.assertEqual(len(radios), 7)
        radio_labels = [r["label"] for r in radios]
        self.assertIn("自动检测", radio_labels)
        self.assertIn("Claude Code", radio_labels)
        self.assertIn("Codex CLI", radio_labels)
        self.assertIn("OpenClaw", radio_labels)
        self.assertIn("OpenCode", radio_labels)
        self.assertIn("Hermes", radio_labels)
        self.assertIn("Kimi Code", radio_labels)

    def test_radio_auto_checked_when_no_forced_agent(self):
        app, _, _ = make_app(forced_agent=None)
        menu = app._build_menu()
        auto = next(r for r in menu if r.get("label") == "自动检测")
        claude = next(r for r in menu if r.get("label") == "Claude Code")
        self.assertTrue(auto["checked"])
        self.assertFalse(claude["checked"])

    def test_radio_claude_checked_when_forced_to_claude(self):
        app, _, _ = make_app(forced_agent="claude")
        menu = app._build_menu()
        auto = next(r for r in menu if r.get("label") == "自动检测")
        claude = next(r for r in menu if r.get("label") == "Claude Code")
        self.assertFalse(auto["checked"])
        self.assertTrue(claude["checked"])

    def test_menu_ends_with_quit(self):
        app, _, _ = make_app()
        menu = app._build_menu()
        self.assertEqual(menu[-1].get("type"), "quit")

    def test_menu_has_open_console(self):
        """菜单应当含操作台项。"""
        app, _, _ = make_app()
        menu = app._build_menu()
        labels = self._labels(menu)
        self.assertIn("打开操作台 ⚡", labels)

    def test_menu_items_have_symbol_icons(self):
        """下拉菜单应给主要操作和 agent radio 提供 macOS SF Symbol 图标名。"""
        app, _, _ = make_app()
        menu = app._build_menu()
        by_label = {item.get("label"): item for item in menu if "label" in item}
        self.assertEqual(by_label["更换工作区..."]["icon"], "folder")
        self.assertEqual(by_label["打开操作台 ⚡"]["icon"], "terminal")
        self.assertEqual(by_label["暂停跟踪"]["icon"], "pause.circle")
        self.assertEqual(by_label["自动检测"]["icon"], "sparkles")
        self.assertEqual(by_label["Claude Code"]["icon"], "brain")
        self.assertEqual(
            by_label["Codex CLI"]["icon"], "chevron.left.forwardslash.chevron.right"
        )
        self.assertEqual(by_label["OpenClaw"]["icon"], "wand.and.stars")
        self.assertEqual(by_label["OpenCode"]["icon"], "curlybraces")
        self.assertEqual(by_label["Hermes"]["icon"], "paperplane")
        self.assertEqual(by_label["Kimi Code"]["icon"], "moon.stars")

    def test_continue_menu_item_uses_play_icon(self):
        app, _, _ = make_app(paused=True)
        menu = app._build_menu()
        item = next(i for i in menu if i.get("label") == "继续跟踪")
        self.assertEqual(item["icon"], "play.circle")

    def test_quit_menu_item_has_icon(self):
        app, _, _ = make_app()
        menu = app._build_menu()
        self.assertEqual(menu[-1].get("icon"), "power")


class TestTraceAppOpenElectron(unittest.TestCase):
    """Electron 操作台打包态走内嵌 app，开发态回退 npx electron。"""

    def test_first_call_launches_electron_process(self):
        proc = MagicMock()
        proc.pid = 1234
        launcher = MagicMock(return_value=make_electron_launch(proc))
        app, _, _ = make_app(electron_launcher=launcher)
        app.on_open_electron()
        launcher.assert_called_once_with(app.workspace)
        self.assertIs(app._electron_proc, proc)

    def test_second_call_does_not_launch_duplicate_if_running(self):
        proc = MagicMock()
        proc.poll.return_value = None
        launcher = MagicMock()
        app, _, _ = make_app(electron_launcher=launcher)
        app._electron_proc = proc
        app.on_open_electron()
        launcher.assert_not_called()

    def test_launch_electron_uses_bundled_app_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            bundled = Path(tmp) / "Trace Console"
            bundled.write_text("#!/bin/sh\n", encoding="utf-8")
            bundled.chmod(0o755)
            proc = MagicMock()
            with (
                patch("menubar.app._bundled_electron_executable", return_value=bundled),
                patch.object(sys, "platform", "win32"),
                patch("menubar.app.subprocess.Popen", return_value=proc) as mock_popen,
            ):
                out = _launch_electron_process(ws)
            self.assertIs(out.proc, proc)
            self.assertFalse(out.external)
            argv = mock_popen.call_args.args[0]
            kwargs = mock_popen.call_args.kwargs
            self.assertEqual(argv, [str(bundled), f"--workspace={ws}"])
            self.assertIsNone(kwargs["cwd"])
            self.assertTrue(kwargs.get("start_new_session"))

    def test_launch_electron_marks_macos_bundled_as_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            bundled = Path(tmp) / "Trace Console.app" / "Contents" / "MacOS" / "Trace Console"
            bundled.parent.mkdir(parents=True)
            bundled.write_text("#!/bin/sh\n", encoding="utf-8")
            bundled.chmod(0o755)
            proc = MagicMock()
            with (
                patch.object(sys, "platform", "darwin"),
                patch("menubar.app._bundled_electron_executable", return_value=bundled),
                patch("menubar.app.subprocess.Popen", return_value=proc) as mock_popen,
            ):
                out = _launch_electron_process(ws)
            self.assertIs(out.proc, proc)
            self.assertTrue(out.external)
            argv = mock_popen.call_args.args[0]
            self.assertEqual(argv, [str(bundled), f"--workspace={ws}"])
            self.assertTrue(mock_popen.call_args.kwargs.get("start_new_session"))

    def test_bundled_electron_executable_finds_windows_portable_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "Trace"
            electron_dir = app_dir / "electron"
            electron_dir.mkdir(parents=True)
            exe = app_dir / "Trace.exe"
            exe.write_text("", encoding="utf-8")
            console = electron_dir / "Trace Console.exe"
            console.write_text("", encoding="utf-8")
            with (
                patch.object(sys, "platform", "win32"),
                patch.object(sys, "executable", str(exe)),
                patch.object(sys, "frozen", True, create=True),
            ):
                self.assertEqual(_bundled_electron_executable(), console.resolve())

    def test_windows_frozen_electron_bridge_uses_trace_bridge_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "Trace"
            app_dir.mkdir()
            exe = app_dir / "Trace.exe"
            exe.write_text("", encoding="utf-8")
            with (
                patch.object(sys, "platform", "win32"),
                patch.object(sys, "executable", str(exe)),
                patch.object(sys, "frozen", True, create=True),
            ):
                env = _electron_bridge_env(app_dir)
            self.assertEqual(
                env["TRACE_PYTHON_EXECUTABLE"],
                str((app_dir / "TraceBridge.exe").resolve()),
            )
            self.assertEqual(env["TRACE_PYTHON_BRIDGE_MODE"], "bridge-exe")
            self.assertNotIn("PYTHONPATH", env)

    def test_launch_electron_uses_windows_bridge_env_when_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "Trace"
            electron_dir = app_dir / "electron"
            electron_dir.mkdir(parents=True)
            exe = app_dir / "Trace.exe"
            exe.write_text("", encoding="utf-8")
            console = electron_dir / "Trace Console.exe"
            console.write_text("", encoding="utf-8")
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            proc = MagicMock()
            with (
                patch.object(sys, "platform", "win32"),
                patch.object(sys, "executable", str(exe)),
                patch.object(sys, "frozen", True, create=True),
                patch("menubar.app.subprocess.Popen", return_value=proc) as mock_popen,
            ):
                out = _launch_electron_process(ws)
            self.assertIs(out.proc, proc)
            self.assertFalse(out.external)
            argv = mock_popen.call_args.args[0]
            kwargs = mock_popen.call_args.kwargs
            self.assertEqual(argv, [str(console.resolve()), f"--workspace={ws}"])
            self.assertIsNone(kwargs["cwd"])
            self.assertEqual(
                kwargs["env"]["TRACE_PYTHON_EXECUTABLE"],
                str((app_dir / "TraceBridge.exe").resolve()),
            )
            self.assertEqual(kwargs["env"]["TRACE_PYTHON_BRIDGE_MODE"], "bridge-exe")

    def test_launch_electron_falls_back_to_npx_in_dev(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            proc = MagicMock()
            with (
                patch("menubar.app._bundled_electron_executable", return_value=None),
                patch("menubar.app.subprocess.Popen", return_value=proc) as mock_popen,
            ):
                out = _launch_electron_process(ws)
            self.assertIs(out.proc, proc)
            self.assertFalse(out.external)
            argv = mock_popen.call_args.args[0]
            kwargs = mock_popen.call_args.kwargs
            self.assertEqual(
                argv, ["npx", "electron", ".", f"--workspace={ws}"]
            )
            self.assertTrue(str(kwargs["cwd"]).endswith("electron_app"))
            self.assertEqual(
                kwargs["env"]["TRACE_PYTHON_MODULE"], "core.electron_diff_bridge"
            )
            self.assertIn("PYTHONPATH", kwargs["env"])

    def test_stop_electron_clears_proc_when_already_exited(self):
        proc = MagicMock()
        proc.poll.return_value = 0
        app, _, _ = make_app()
        app._electron_proc = proc
        with patch("menubar.app._quit_external_electron_console") as mock_quit:
            app._stop_electron()
        self.assertIsNone(app._electron_proc)
        proc.terminate.assert_not_called()
        mock_quit.assert_called_once_with(app.workspace)

    def test_stop_electron_quits_external_console_on_macos_bundle(self):
        proc = MagicMock()
        proc.poll.return_value = None
        app, _, _ = make_app()
        app._electron_proc = proc
        app._electron_external = True
        with (
            patch("menubar.app._terminate_process_tree") as mock_tree,
            patch("menubar.app._quit_external_electron_console") as mock_quit,
        ):
            app._stop_electron()
        mock_tree.assert_called_once_with(proc)
        mock_quit.assert_called_once_with(app.workspace)
        self.assertFalse(app._electron_external)


class TestTraceAppCallbacks(unittest.TestCase):
    def test_on_toggle_pause_flips_state(self):
        app, tray, _ = make_app(paused=False)
        app.on_toggle_pause()
        self.assertTrue(app._paused)
        tray.set_menu.assert_called()

    def test_on_toggle_pause_twice_returns_to_running(self):
        app, _, _ = make_app(paused=False)
        app.on_toggle_pause()
        app.on_toggle_pause()
        self.assertFalse(app._paused)

    def test_set_forced_agent_updates_state_and_rebuilds(self):
        app, tray, _ = make_app()
        app._set_forced_agent("codex")
        self.assertEqual(app._forced_agent, "codex")
        tray.set_menu.assert_called()

    # Task 4.2：callback 同时写到 handler 字段
    def test_on_toggle_pause_writes_handler_paused(self):
        app, _, _ = make_app(paused=False)
        app.on_toggle_pause()
        self.assertTrue(app.handler.paused)
        app.on_toggle_pause()
        self.assertFalse(app.handler.paused)

    def test_set_forced_agent_writes_handler_override(self):
        app, _, _ = make_app()
        app._set_forced_agent("claude")
        self.assertEqual(app.handler.override_agent, "claude")
        # 切回自动应该把 override 清空
        app._set_forced_agent(None)
        self.assertIsNone(app.handler.override_agent)


class TestTraceAppPoll(unittest.TestCase):
    def test_poll_clears_exited_electron_proc(self):
        proc = MagicMock()
        proc.poll.return_value = 0
        app, tray, scan = make_app()
        app._electron_proc = proc
        app._poll()
        self.assertIsNone(app._electron_proc)
        scan.assert_not_called()
        tray.set_title.assert_not_called()

    def test_poll_drains_ipc_without_scanning_agents(self):
        app, tray, scan = make_app(active_agents=[])
        app._poll()
        scan.assert_not_called()
        tray.set_title.assert_not_called()


class TestTraceAppChangeWorkspace(unittest.TestCase):
    def test_cancelled_does_nothing(self):
        picker = MagicMock(return_value=None)
        app, _, _ = make_app()
        app._workspace_picker = picker
        with patch("menubar.app.save_last_workspace") as mock_save:
            app.on_change_workspace()
            picker.assert_called_once_with(app.workspace)
            mock_save.assert_not_called()
            # 没切换：daemon.restart 不应被调
            app.daemon.restart.assert_not_called()

    def test_picked_saves_state(self):
        new_ws = Path("/tmp/new_ws")
        picker = MagicMock(return_value=new_ws)
        app, _, _ = make_app(workspace_picker=picker)
        with patch("menubar.app.save_last_workspace") as mock_save:
            app.on_change_workspace()
            picker.assert_called_once_with(app.workspace)
            mock_save.assert_called_once_with(new_ws)

    # Phase 2：on_change_workspace 真正热切 daemon
    def test_picked_triggers_daemon_restart(self):
        """选了新工作区 → daemon.restart(new_ws) 被调，真切。"""
        new_ws = Path("/tmp/new_ws")
        picker = MagicMock(return_value=new_ws)
        app, _, _ = make_app(workspace_picker=picker)
        with patch("menubar.app.save_last_workspace"):
            app.on_change_workspace()
            app.daemon.restart.assert_called_once_with(new_ws)

    def test_picking_same_workspace_does_not_restart(self):
        """选了同一个工作区不重启 daemon——避免无意义抖动。"""
        # daemon.workspace 在 make_app 里是 /tmp/test_ws
        picker = MagicMock(return_value=Path("/tmp/test_ws"))
        app, _, _ = make_app(workspace_picker=picker)
        with patch("menubar.app.save_last_workspace"):
            app.on_change_workspace()
            app.daemon.restart.assert_not_called()

    def test_restart_failure_recovers_old_workspace(self):
        """daemon.restart 失败时尝试恢复旧 workspace，不留半残态。"""
        new_ws = Path("/tmp/new_ws")
        picker = MagicMock(return_value=new_ws)
        app, _, _ = make_app(workspace_picker=picker)
        old_ws = app.workspace
        app.daemon.restart.side_effect = RuntimeError("synthetic restart fail")
        with patch("menubar.app.save_last_workspace"):
            app.on_change_workspace()  # 不应抛
            # 应当尝试用旧 workspace 调 start 恢复
            app.daemon.start.assert_called_with(old_ws)

    def test_change_workspace_relaunches_running_electron_console(self):
        """Electron 已打开时，切工作区应重启它，让前端绑定新 workspace。"""
        new_ws = Path("/tmp/new_ws")
        old_proc = MagicMock()
        old_proc.pid = 111
        old_proc.poll.return_value = None
        old_proc.wait.return_value = 0
        new_proc = MagicMock()
        new_proc.pid = 222
        launcher = MagicMock(return_value=make_electron_launch(new_proc))
        picker = MagicMock(return_value=new_ws)

        app, _, _ = make_app(
            electron_launcher=launcher,
            workspace_picker=picker,
        )
        app._electron_proc = old_proc

        with patch("menubar.app.save_last_workspace"):
            with (
                patch("menubar.app._terminate_process_tree") as mock_stop,
                patch("menubar.app._quit_external_electron_console"),
            ):
                app.on_change_workspace()

        mock_stop.assert_called_once_with(old_proc)
        launcher.assert_called_once_with(new_ws)
        self.assertIs(app._electron_proc, new_proc)

    def test_change_workspace_does_not_open_electron_when_it_was_closed(self):
        """用户没开 Electron 操作台时，切工作区不应突然弹一个新窗口。"""
        new_ws = Path("/tmp/new_ws")
        launcher = MagicMock()
        picker = MagicMock(return_value=new_ws)
        app, _, _ = make_app(
            electron_launcher=launcher,
            workspace_picker=picker,
        )

        with patch("menubar.app.save_last_workspace"):
            app.on_change_workspace()

        launcher.assert_not_called()
        self.assertIsNone(app._electron_proc)


@unittest.skipUnless(sys.platform == "darwin", "macOS only")
class TestChooseWorkspaceForMenubar(unittest.TestCase):
    def test_macos_picker_activates_front_app_before_choosing_folder(self):
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "/tmp/new workspace\n"
        completed.stderr = ""

        with (
            patch("menubar.app.sys.platform", "darwin"),
            patch("menubar.app.subprocess.run", return_value=completed) as mock_run,
        ):
            chosen = _choose_workspace_for_menubar(Path("/tmp/current workspace"))

        self.assertEqual(chosen, Path("/tmp/new workspace").resolve())
        argv = mock_run.call_args.args[0]
        self.assertEqual(argv[:2], ["osascript", "-e"])
        script = argv[2]
        self.assertIn('tell application "Finder" to activate', script)
        self.assertIn("choose folder", script)
        self.assertIn("default location (POSIX file", script)

    def test_macos_picker_escapes_quotes_in_default_location(self):
        completed = MagicMock()
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "cancelled"

        with (
            patch("menubar.app.sys.platform", "darwin"),
            patch("menubar.app.subprocess.run", return_value=completed) as mock_run,
        ):
            chosen = _choose_workspace_for_menubar(Path('/tmp/ws "quoted"'))

        self.assertIsNone(chosen)
        script = mock_run.call_args.args[0][2]
        self.assertIn('ws \\"quoted\\"', script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
