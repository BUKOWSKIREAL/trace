"""
Tray 抽象层测试
==================
锁定 Tray ABC 的契约：5 个抽象方法必须实现；make_tray 按 sys.platform 分发。
Task 1（5/25）：ABC + 工厂 + 平台分发。
Task 2（5/25）：RumpsTray 真正用 rumps 实装；测试用 mock 模拟 rumps API。
PystrayTray 用 pystray 实装，测试用 mock 模拟 Windows/Linux 托盘 API。

# 人工编写（TDD：测试先于实现）
"""
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from menubar.tray_base import Tray, make_tray  # noqa: E402
import menubar.tray_pystray as tray_pystray_module  # noqa: E402
from menubar.tray_pystray import PystrayTray  # noqa: E402


def _import_rumps_tray():
    try:
        from menubar.tray_rumps import RumpsTray

        return RumpsTray
    except ImportError:
        return None


RumpsTray = _import_rumps_tray()


class FakePystrayMenuItem:
    """Tiny pystray.MenuItem test double."""

    def __init__(self, text, action, checked=None, radio=False):
        self.text = text
        self.action = action
        self._checked = checked if callable(checked) else (lambda _: checked)
        self.radio = radio

    @property
    def checked(self):
        return self._checked(self)


class FakePystrayMenu:
    """Tiny pystray.Menu test double."""

    SEPARATOR = object()

    def __init__(self, *items):
        self.items = list(items)


class FakePystrayIcon:
    """Tiny pystray.Icon test double."""

    instances = []

    def __init__(self, name, icon=None, title=None, menu=None):
        self.name = name
        self.icon = icon
        self.title = title
        self.menu = menu
        self.visible = False
        self.stopped = False
        self.run_called = False
        self.update_menu_call_count = 0
        FakePystrayIcon.instances.append(self)

    def run(self, setup=None):
        self.run_called = True
        if setup is not None:
            setup(self)

    def stop(self):
        self.stopped = True

    def update_menu(self):
        self.update_menu_call_count += 1


def fake_pystray_module():
    FakePystrayIcon.instances.clear()
    return SimpleNamespace(
        Icon=FakePystrayIcon,
        Menu=FakePystrayMenu,
        MenuItem=FakePystrayMenuItem,
    )


class TestTrayABC(unittest.TestCase):
    """Tray 抽象基类必须强制子类实现全部 5 个方法。"""

    def test_cannot_instantiate_abc_directly(self):
        """直接 Tray(...) 应被 ABC 阻止。"""
        with self.assertRaises(TypeError):
            Tray("Trace")

    def test_concrete_subclass_with_all_methods_can_be_instantiated(self):
        """5 个抽象方法都实现的子类可以正常实例化。"""

        class GoodSubclass(Tray):
            def set_title(self, text): pass
            def set_menu(self, items): pass
            def run(self): pass
            def stop(self): pass
            def schedule_periodic(self, interval, callback): pass

        t = GoodSubclass("test")
        self.assertEqual(t.name, "test")
        self.assertIsNone(t.icon_path)

    def test_subclass_missing_method_cannot_be_instantiated(self):
        """只实现一部分方法的子类，ABC 应阻止实例化。"""

        class IncompleteSubclass(Tray):
            def set_title(self, text): pass
            # 故意漏掉 set_menu / run / stop / schedule_periodic

        with self.assertRaises(TypeError):
            IncompleteSubclass("test")

    def test_subclass_missing_schedule_periodic_cannot_be_instantiated(self):
        """schedule_periodic 是 Tray ABC 的第 5 个抽象方法（Task 3 引入）。"""

        class AlmostComplete(Tray):
            def set_title(self, text): pass
            def set_menu(self, items): pass
            def run(self): pass
            def stop(self): pass
            # 故意漏 schedule_periodic

        with self.assertRaises(TypeError):
            AlmostComplete("test")

    def test_subclass_inherits_init_with_name_and_icon(self):
        """子类继承基类的 __init__，存 name 和 icon_path 两个字段。"""

        class GoodSubclass(Tray):
            def set_title(self, text): pass
            def set_menu(self, items): pass
            def run(self): pass
            def stop(self): pass
            def schedule_periodic(self, interval, callback): pass

        icon = Path("/tmp/icon.png")
        t = GoodSubclass("Trace", icon)
        self.assertEqual(t.name, "Trace")
        self.assertEqual(t.icon_path, icon)


class TestMakeTrayFactory(unittest.TestCase):
    """make_tray 按 sys.platform 自动分发到对应实现类。"""

    @unittest.skipUnless(sys.platform == "darwin", "macOS only")
    def test_macos_returns_rumps_tray(self):
        with patch.object(sys, "platform", "darwin"):
            # RumpsTray 构造会 import 真实 rumps；本测试环境已装。
            RumpsTray = _import_rumps_tray()
            t = make_tray("Trace")
            self.assertIsInstance(t, RumpsTray)

    def test_windows_returns_pystray_tray(self):
        with patch.object(sys, "platform", "win32"):
            t = make_tray("Trace")
            self.assertIsInstance(t, PystrayTray)

    def test_linux_returns_pystray_tray(self):
        with patch.object(sys, "platform", "linux"):
            t = make_tray("Trace")
            self.assertIsInstance(t, PystrayTray)

    @unittest.skipUnless(sys.platform == "darwin", "macOS only")
    def test_factory_passes_icon_path_to_constructor(self):
        # 工厂测试只验证 dispatch，不依赖 rumps 真实行为——patch 掉 rumps
        # 避免 rumps.App 在拿到 icon path 时去真磁盘加载文件而崩
        with patch.object(sys, "platform", "darwin"), \
                patch("menubar.tray_rumps.rumps"):
            icon = Path("/tmp/icon.png")
            t = make_tray("Trace", icon)
            self.assertEqual(t.icon_path, icon)
            self.assertEqual(t.name, "Trace")


@unittest.skipUnless(sys.platform == "darwin", "macOS only")
class TestRumpsTrayImpl(unittest.TestCase):
    """Task 2：RumpsTray 用 rumps 真实落地 Tray 契约。
    通过 patch('menubar.tray_rumps.rumps') 把 rumps 模块替换成 mock，
    断言我们对 rumps API 的调用形式正确——不依赖真实 NSApplication 跑起来。"""

    def test_init_creates_rumps_app_with_name(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            RumpsTray("Trace")
            mock_rumps.App.assert_called_once_with("Trace", icon=None, quit_button=None)

    def test_init_passes_icon_path_as_string(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            icon = Path("/tmp/icon.png")
            RumpsTray("Trace", icon)
            mock_rumps.App.assert_called_once_with(
                "Trace",
                icon=str(icon),
                template=True,
                quit_button=None,
            )

    def test_init_with_loadable_icon_still_passes_path_to_rumps(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps, \
                patch("menubar.tray_rumps.NSImage") as mock_nsimage:
            icon = Path("/tmp/icon.png")
            mock_nsimage.alloc.return_value.initWithContentsOfFile_.return_value = MagicMock()

            RumpsTray("Trace", icon)

            mock_rumps.App.assert_called_once_with(
                "Trace",
                icon=str(icon),
                template=True,
                quit_button=None,
            )

    def test_set_title_updates_app_title(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            t.set_title("Claude Code")
            self.assertEqual(mock_rumps.App.return_value.title, "Claude Code")

    def test_set_menu_empty_just_clears(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            t.set_menu([])
            mock_rumps.App.return_value.menu.clear.assert_called_once()

    def test_set_menu_item_creates_menu_item_with_label(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            cb = MagicMock()
            t.set_menu([{"type": "item", "label": "更换工作区", "callback": cb}])
            # 验证 rumps.MenuItem 被调用，第一个参数是 label
            mock_rumps.MenuItem.assert_called()
            args, kwargs = mock_rumps.MenuItem.call_args
            self.assertEqual(args[0], "更换工作区")
            # 验证菜单被 add
            mock_rumps.App.return_value.menu.add.assert_called()

    def test_set_menu_item_applies_sf_symbol_icon(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps, \
                patch("menubar.tray_rumps.NSImage") as mock_nsimage:
            menu_item_instance = MagicMock()
            mock_rumps.MenuItem.return_value = menu_item_instance
            image = MagicMock()
            mock_nsimage.imageWithSystemSymbolName_accessibilityDescription_.return_value = image

            t = RumpsTray("Trace")
            t.set_menu([
                {"type": "item", "label": "更换工作区", "icon": "folder",
                 "callback": MagicMock()},
            ])

            mock_nsimage.imageWithSystemSymbolName_accessibilityDescription_.assert_called_once_with(
                "folder", None,
            )
            image.setTemplate_.assert_called_once_with(True)
            menu_item_instance._menuitem.setImage_.assert_called_once_with(image)

    def test_set_menu_quit_applies_icon(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps, \
                patch("menubar.tray_rumps.NSImage") as mock_nsimage:
            menu_item_instance = MagicMock()
            mock_rumps.MenuItem.return_value = menu_item_instance
            image = MagicMock()
            mock_nsimage.imageWithSystemSymbolName_accessibilityDescription_.return_value = image

            t = RumpsTray("Trace")
            t.set_menu([{"type": "quit", "icon": "power"}])

            mock_nsimage.imageWithSystemSymbolName_accessibilityDescription_.assert_called_once_with(
                "power", None,
            )
            menu_item_instance._menuitem.setImage_.assert_called_once_with(image)

    def test_set_menu_separator_uses_rumps_separator(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            t.set_menu([{"type": "separator"}])
            mock_rumps.App.return_value.menu.add.assert_called_with(mock_rumps.separator)

    def test_set_menu_radio_sets_checked_state(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            # 让 MenuItem 实例可以被赋值 .state
            menu_item_instance = MagicMock()
            mock_rumps.MenuItem.return_value = menu_item_instance

            t = RumpsTray("Trace")
            cb = MagicMock()
            t.set_menu([
                {"type": "radio", "label": "Claude", "group": "agent",
                 "checked": True, "callback": cb},
            ])
            # checked=True 应该设 state=1
            self.assertEqual(menu_item_instance.state, 1)

    def test_set_menu_radio_unchecked_state_zero(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            menu_item_instance = MagicMock()
            mock_rumps.MenuItem.return_value = menu_item_instance

            t = RumpsTray("Trace")
            t.set_menu([
                {"type": "radio", "label": "Codex", "group": "agent",
                 "checked": False, "callback": MagicMock()},
            ])
            self.assertEqual(menu_item_instance.state, 0)

    def test_set_menu_quit_creates_quit_item(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            t.set_menu([{"type": "quit"}])
            # 应当至少调用过 MenuItem 来创建退出项
            mock_rumps.MenuItem.assert_called()
            # 标签是"退出"
            args = [c.args for c in mock_rumps.MenuItem.call_args_list]
            labels = [a[0] for a in args]
            self.assertIn("退出", labels)

    def test_set_menu_user_callback_invoked_when_menu_item_triggered(self):
        """rumps 的 callback 签名是 cb(sender)，我们的 schema 是 cb()。
        中间应该有适配层，让用户的零参 callback 被正确触发。"""
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            user_cb = MagicMock()
            t.set_menu([{"type": "item", "label": "X", "callback": user_cb}])

            # 拿到我们传给 rumps.MenuItem 的适配 callback
            _, kwargs = mock_rumps.MenuItem.call_args
            wrapped = kwargs["callback"]

            # 模拟 rumps 用 sender 参数调它
            wrapped(MagicMock())
            user_cb.assert_called_once_with()

    def test_set_menu_called_twice_clears_each_time(self):
        """重复 set_menu 应该每次都先 clear，不会叠加。"""
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            t.set_menu([])
            t.set_menu([])
            self.assertEqual(mock_rumps.App.return_value.menu.clear.call_count, 2)

    def test_run_calls_app_run(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            t.run()
            mock_rumps.App.return_value.run.assert_called_once()

    def test_stop_calls_quit_application(self):
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            t.stop()
            mock_rumps.quit_application.assert_called_once()

    def test_schedule_periodic_creates_rumps_timer_and_starts(self):
        """schedule_periodic 应当用 rumps.Timer 包用户 callback，
        并立刻 start() 让它在主线程跑。"""
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            cb = MagicMock()
            t.schedule_periodic(0.5, cb)
            # rumps.Timer(callback, interval) 被调用
            mock_rumps.Timer.assert_called_once()
            args, _ = mock_rumps.Timer.call_args
            # 第二个参数是 interval
            self.assertEqual(args[1], 0.5)
            # start() 被调
            mock_rumps.Timer.return_value.start.assert_called_once()

    def test_schedule_periodic_user_callback_adapted_to_rumps_signature(self):
        """rumps.Timer 的 callback 也是 cb(sender)，要适配零参用户 callback。"""
        with patch("menubar.tray_rumps.rumps") as mock_rumps:
            t = RumpsTray("Trace")
            user_cb = MagicMock()
            t.schedule_periodic(1.0, user_cb)
            args, _ = mock_rumps.Timer.call_args
            wrapped = args[0]
            # 模拟 rumps 用 sender 参数调它
            wrapped(MagicMock())
            user_cb.assert_called_once_with()


class TestPystrayTrayImpl(unittest.TestCase):
    """PystrayTray 用 pystray 真实落地 Tray 契约。

    当前测试环境是 macOS，不导入真实 pystray；用 test double 锁定我们对
    pystray.Icon / Menu / MenuItem 的调用形状。
    """

    def test_set_title_updates_tooltip_before_icon_exists(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            t.set_title("Claude Code")
            t.set_menu([])
            self.assertEqual(FakePystrayIcon.instances[0].title, "Claude Code")

    def test_set_title_updates_existing_icon_tooltip(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            t.set_menu([])
            icon = FakePystrayIcon.instances[0]
            t.set_title("Codex CLI")
            self.assertEqual(icon.title, "Codex CLI")

    def test_set_menu_empty_creates_icon_with_empty_menu(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            t.set_menu([])
            icon = FakePystrayIcon.instances[0]
            self.assertEqual(icon.name, "Trace")
            self.assertEqual(icon.menu.items, [])

    def test_set_menu_item_creates_pystray_menu_item_with_label(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            cb = MagicMock()
            t.set_menu([{"type": "item", "label": "更换工作区", "callback": cb}])
            item = FakePystrayIcon.instances[0].menu.items[0]
            self.assertEqual(item.text, "更换工作区")
            self.assertFalse(item.radio)
            self.assertIsNone(item.checked)

    def test_set_menu_user_callback_invoked_when_menu_item_triggered(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            user_cb = MagicMock()
            t.set_menu([{"type": "item", "label": "X", "callback": user_cb}])
            item = FakePystrayIcon.instances[0].menu.items[0]
            item.action(MagicMock(), item)
            user_cb.assert_called_once_with()

    def test_set_menu_separator_uses_pystray_separator(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            t.set_menu([{"type": "separator"}])
            self.assertIs(FakePystrayIcon.instances[0].menu.items[0], fake.Menu.SEPARATOR)

    def test_set_menu_radio_sets_checked_and_radio_flags(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            t.set_menu([
                {"type": "radio", "label": "Claude", "group": "agent",
                 "checked": True, "callback": MagicMock()},
            ])
            item = FakePystrayIcon.instances[0].menu.items[0]
            self.assertEqual(item.text, "Claude")
            self.assertTrue(item.checked)
            self.assertTrue(item.radio)
            self.assertTrue(callable(item._checked))

    def test_set_menu_radio_unchecked_state_false(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            t.set_menu([
                {"type": "radio", "label": "Codex", "group": "agent",
                 "checked": False, "callback": MagicMock()},
            ])
            item = FakePystrayIcon.instances[0].menu.items[0]
            self.assertFalse(item.checked)
            self.assertTrue(item.radio)

    def test_set_menu_quit_creates_stop_callback(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            t.set_menu([{"type": "quit"}])
            icon = FakePystrayIcon.instances[0]
            item = icon.menu.items[0]
            self.assertEqual(item.text, "退出")
            item.action(icon, item)
            self.assertTrue(icon.stopped)

    def test_set_menu_called_while_running_updates_menu(self):
        fake = fake_pystray_module()
        with patch("menubar.tray_pystray.importlib.import_module", return_value=fake):
            t = PystrayTray("Trace")
            t.set_menu([])
            icon = FakePystrayIcon.instances[0]
            t._running = True
            t.set_menu([{"type": "separator"}])
            self.assertEqual(icon.update_menu_call_count, 1)

    def test_run_calls_icon_run_and_starts_scheduled_tasks(self):
        fake = fake_pystray_module()
        with patch.object(tray_pystray_module.importlib, "import_module", return_value=fake), \
                patch.object(tray_pystray_module, "_PeriodicTask") as task_cls:
            task = task_cls.return_value
            t = PystrayTray("Trace")
            t.schedule_periodic(0.5, MagicMock())
            t.run()
            icon = FakePystrayIcon.instances[0]
            self.assertTrue(icon.run_called)
            self.assertTrue(icon.visible)
            task.start.assert_called_once_with()
            task.cancel.assert_called_once_with()

    def test_stop_calls_icon_stop_and_cancels_tasks(self):
        fake = fake_pystray_module()
        with patch.object(tray_pystray_module.importlib, "import_module", return_value=fake), \
                patch.object(tray_pystray_module, "_PeriodicTask") as task_cls:
            task = task_cls.return_value
            t = PystrayTray("Trace")
            t.schedule_periodic(0.5, MagicMock())
            t.set_menu([])
            icon = FakePystrayIcon.instances[0]
            t.stop()
            self.assertTrue(icon.stopped)
            task.cancel.assert_called_once_with()

    def test_schedule_periodic_rejects_non_positive_interval(self):
        t = PystrayTray("Trace")
        with self.assertRaises(ValueError):
            t.schedule_periodic(0, lambda: None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
