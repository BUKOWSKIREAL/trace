"""
RumpsTray — macOS 菜单栏实装（rumps）
========================================
用 rumps 把抽象 Tray 接口落地到 macOS 状态栏。

设计要点：
- `import rumps` 放在模块顶部——测试可以用 `patch("menubar.tray_rumps.rumps")`
  整体替换；同时保证导入失败时立刻报错而不是延后
- rumps.App 的 `quit_button=None` 关掉默认的"Quit" 菜单项，我们用自己的 quit 项
- callback 适配：rumps 的 callback 签名是 `cb(sender)`，我们的 schema 是
  `cb()`——用闭包包一层
- radio 项：rumps 没有原生 radio 支持，用 `MenuItem.state`（1=选中、0=未选）
  模拟；mutual exclusion 由调用方管理（点 radio → 调 set_menu 重画）

# 人工编写
"""
import logging

from AppKit import NSImage
import rumps

from menubar.tray_base import Tray

logger = logging.getLogger("trace.tray.rumps")


class RumpsTray(Tray):
    """macOS 菜单栏托盘（rumps 实装）。"""

    def __init__(self, name, icon_path=None):
        super().__init__(name, icon_path)
        # quit_button=None 关掉 rumps 默认的"Quit"项——
        # 我们的菜单 schema 用 {'type': 'quit'} 自己声明
        kwargs = {"icon": str(icon_path) if icon_path else None}
        if icon_path:
            kwargs["template"] = True
        self._app = rumps.App(name, quit_button=None, **kwargs)

    # ---- Tray ABC 实装 ----

    def set_title(self, text: str) -> None:
        """更新状态栏文字。线程安全：rumps 内部通过主线程刷 NSStatusItem。"""
        self._app.title = text

    def set_menu(self, items: list[dict]) -> None:
        """
        清空当前菜单，按 items 列表重新构建。
        items 的每项 dict 见 tray_base.py 的 schema 文档。
        """
        self._app.menu.clear()
        for item in items:
            t = item.get("type")
            if t == "item":
                m = rumps.MenuItem(
                    item["label"],
                    callback=self._adapt_callback(item["callback"]),
                )
                self._apply_symbol_icon(m, item.get("icon"))
                self._app.menu.add(m)
            elif t == "separator":
                self._app.menu.add(rumps.separator)
            elif t == "radio":
                # rumps 没原生 radio；用 state 模拟
                m = rumps.MenuItem(
                    item["label"],
                    callback=self._adapt_callback(item["callback"]),
                )
                m.state = 1 if item.get("checked") else 0
                self._apply_symbol_icon(m, item.get("icon"))
                self._app.menu.add(m)
            elif t == "quit":
                quit_cb = item.get("callback")
                def _quit(_sender, _quit_cb=quit_cb):
                    if _quit_cb is not None:
                        _quit_cb()
                    rumps.quit_application()

                m = rumps.MenuItem("退出", callback=_quit)
                self._apply_symbol_icon(m, item.get("icon"))
                self._app.menu.add(m)
            else:
                logger.warning("未知菜单项 type=%r，跳过: %r", t, item)

    def run(self) -> None:
        """阻塞主线程跑 rumps run loop。必须在主线程调用。"""
        self._app.run()

    def stop(self) -> None:
        """优雅退出 rumps run loop。"""
        rumps.quit_application()

    def schedule_periodic(self, interval: float, callback) -> None:
        """
        用 rumps.Timer 包用户的零参 callback，立刻 start 让它在主线程跑。
        rumps.Timer 的 callback 签名也是 cb(sender)，用闭包适配。
        """
        timer = rumps.Timer(self._adapt_callback(callback), interval)
        timer.start()

    # ---- 内部工具 ----

    @staticmethod
    def _adapt_callback(user_cb):
        """
        rumps 的 callback 签名是 cb(sender)，我们的 schema 约定 cb()。
        用闭包包一层适配——让用户的 callback 不需要关心 rumps 内部。
        """
        def wrapped(_sender):
            user_cb()

        return wrapped

    @staticmethod
    def _apply_symbol_icon(menu_item, symbol_name: str | None) -> None:
        """给 rumps.MenuItem 设置 macOS SF Symbol 模板图标。"""
        if not symbol_name:
            return
        try:
            image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol_name,
                None,
            )
        except Exception as exc:
            logger.debug("加载菜单图标失败: %s (%s)", symbol_name, exc)
            return
        if image is None:
            logger.debug("未找到菜单图标 SF Symbol: %s", symbol_name)
            return
        try:
            image.setTemplate_(True)
            menu_item._menuitem.setImage_(image)
        except Exception as exc:
            logger.debug("设置菜单图标失败: %s (%s)", symbol_name, exc)
