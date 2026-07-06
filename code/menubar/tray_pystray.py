"""
PystrayTray — Windows / Linux 菜单栏实装
=======================================
用 pystray 把抽象 Tray 接口落地到 Windows / Linux 系统托盘。

设计要点：
- pystray 按平台 marker 安装，macOS 开发环境可能没有该包；因此保持 lazy import，
  只有真正 set_menu/run 时才加载 pystray。
- pystray.MenuItem 的 callback 签名是 cb(icon, item)，我们的 schema 是 cb()，
  用闭包适配。
- pystray 没有 rumps 那种主线程 Timer；周期任务在托盘 ready 后由 daemon thread
  轮询触发。当前业务回调只刷新内部状态和 tooltip，不创建 Tk UI。
- schema 里的 icon 是 macOS SF Symbol 名；pystray 菜单项不消费它。

# 人工编写（Windows / Linux pystray 实装；Windows 真机仍需最终人工验收）
"""
from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from menubar.tray_base import Tray

logger = logging.getLogger("trace.tray.pystray")


class _PeriodicTask:
    """Small repeat timer used by pystray after the icon run loop is ready."""

    def __init__(self, interval: float, callback: Callable[[], None]):
        if interval <= 0:
            raise ValueError("interval must be positive")
        self.interval = interval
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.callback()
            except Exception:
                logger.exception("pystray periodic callback failed")


class PystrayTray(Tray):
    """Windows / Linux 菜单栏托盘（pystray 实装）。"""

    def __init__(self, name: str, icon_path: Path | None = None):
        super().__init__(name, icon_path)
        self._title = name
        self._pystray = None
        self._icon = None
        self._periodic_tasks: list[_PeriodicTask] = []
        self._running = False

    def set_title(self, text: str) -> None:
        """更新 Windows/Linux 托盘 tooltip。"""
        self._title = text
        if self._icon is not None:
            self._icon.title = text

    def set_menu(self, items: list[dict[str, Any]]) -> None:
        """清空并重建 pystray 菜单。"""
        pystray = self._ensure_pystray()
        icon = self._ensure_icon()
        icon.menu = pystray.Menu(*self._convert_menu_items(items))
        if self._running:
            try:
                icon.update_menu()
            except Exception:
                logger.exception("pystray menu update failed")

    def run(self) -> None:
        """阻塞主线程跑 pystray run loop。"""
        icon = self._ensure_icon()
        self._running = True

        def setup(_icon):
            _icon.visible = True
            for task in self._periodic_tasks:
                task.start()

        try:
            icon.run(setup=setup)
        finally:
            self._running = False
            self._cancel_periodic_tasks()

    def stop(self) -> None:
        """优雅退出 pystray run loop，并停止后台轮询。"""
        self._cancel_periodic_tasks()
        if self._icon is not None:
            self._icon.stop()

    def schedule_periodic(self, interval: float, callback) -> None:
        """注册周期回调；run loop ready 后开始执行。"""
        task = _PeriodicTask(interval, callback)
        self._periodic_tasks.append(task)
        if self._running:
            task.start()

    def _ensure_pystray(self):
        if self._pystray is None:
            self._pystray = importlib.import_module("pystray")
        return self._pystray

    def _ensure_icon(self):
        if self._icon is not None:
            return self._icon
        pystray = self._ensure_pystray()
        self._icon = pystray.Icon(
            self.name,
            icon=self._load_icon_image(),
            title=self._title,
            menu=pystray.Menu(),
        )
        return self._icon

    def _convert_menu_items(self, items: list[dict[str, Any]]) -> list[Any]:
        pystray = self._ensure_pystray()
        converted: list[Any] = []
        for item in items:
            t = item.get("type")
            if t == "item":
                converted.append(pystray.MenuItem(
                    item["label"],
                    self._adapt_callback(item["callback"]),
                ))
            elif t == "separator":
                converted.append(pystray.Menu.SEPARATOR)
            elif t == "radio":
                is_checked = bool(item.get("checked"))
                converted.append(pystray.MenuItem(
                    item["label"],
                    self._adapt_callback(item["callback"]),
                    checked=lambda _item, checked=is_checked: checked,
                    radio=True,
                ))
            elif t == "quit":
                quit_cb = item.get("callback")
                converted.append(pystray.MenuItem(
                    "退出",
                    self._make_quit_callback(quit_cb),
                ))
            else:
                logger.warning("未知菜单项 type=%r，跳过: %r", t, item)
        return converted

    @staticmethod
    def _adapt_callback(user_cb):
        def wrapped(_icon=None, _item=None):
            user_cb()

        return wrapped

    def _make_quit_callback(self, quit_cb):
        def _quit(_icon, _item):
            if quit_cb is not None:
                quit_cb()
            self.stop()

        return _quit

    def _load_icon_image(self) -> Image.Image:
        if self.icon_path is not None:
            try:
                with Image.open(self.icon_path) as image:
                    return image.convert("RGBA").copy()
            except Exception:
                logger.exception("加载托盘图标失败，使用默认图标: %s", self.icon_path)
        return self._default_icon()

    @staticmethod
    def _default_icon() -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(24, 24, 24, 255))
        draw.line((20, 24, 44, 24), fill=(255, 255, 255, 255), width=4)
        draw.line((20, 34, 38, 34), fill=(255, 255, 255, 255), width=4)
        draw.line((20, 44, 32, 44), fill=(255, 255, 255, 255), width=4)
        return image

    def _cancel_periodic_tasks(self) -> None:
        for task in self._periodic_tasks:
            task.cancel()
