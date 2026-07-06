"""
Tray 跨平台抽象层
====================
定义菜单栏托盘的统一接口，运行时按 sys.platform 自动分发到具体实现：
- macOS  → tray_rumps.RumpsTray   （rumps + NSStatusBar）
- 其它   → tray_pystray.PystrayTray（pystray + 系统托盘）

设计动机：业务层只认 Tray schema，平台差异下沉到 rumps / pystray
适配器里，便于 macOS、Windows 和 Linux 共用同一套菜单逻辑。

接口契约（5 个抽象方法）：
- set_title(text)：更新菜单栏图标旁边的文字
- set_menu(items)：用 list[dict] 一次性重构整个菜单（dict schema 见
  下方文档）
- run()：阻塞主线程跑 native run loop（macOS=NSApplication，
  Windows=pystray 内部循环）
- stop()：优雅退出

菜单项 dict schema：
    {'type': 'item',      'label': str, 'callback': Callable[[], None],
                          'icon': str | None}  # 可选 macOS SF Symbol 名
    {'type': 'radio',     'label': str, 'group': str, 'checked': bool,
                          'callback': Callable[[], None],
                          'icon': str | None}
    {'type': 'separator'}
    {'type': 'quit',      'icon': str | None, 'callback': Callable[[], None] | None}

# 人工编写
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Tray(ABC):
    """菜单栏托盘的跨平台抽象基类。"""

    def __init__(self, name: str, icon_path: Path | None = None):
        """
        name: 菜单栏图标旁的初始文字（rumps 的 title / pystray 的 tooltip）
        icon_path: 可选的图标文件路径（.png / .icns）；None 表示用文字图标
        """
        self.name = name
        self.icon_path = icon_path

    @abstractmethod
    def set_title(self, text: str) -> None:
        """更新菜单栏显示文字（如"Claude Code"）。线程安全：必须从主线程调。"""

    @abstractmethod
    def set_menu(self, items: list[dict[str, Any]]) -> None:
        """重新构建整个菜单。items 的 dict schema 见模块 docstring。"""

    @abstractmethod
    def run(self) -> None:
        """阻塞主线程跑 native run loop。**必须在主线程调用**。"""

    @abstractmethod
    def stop(self) -> None:
        """优雅退出 run loop。"""

    @abstractmethod
    def schedule_periodic(self, interval: float, callback) -> None:
        """
        每 interval 秒调一次 callback（零参）。
        用于轮询 daemon ipc.queue、刷新菜单标题等。
        macOS/rumps 路径会在主线程 timer 执行；pystray 路径在 run loop
        ready 后用后台线程轮询，所以 callback 不应直接创建 GUI 窗口。
        """


def make_tray(name: str, icon_path: Path | None = None) -> Tray:
    """
    按 sys.platform 自动分发到对应实现。

    设计取舍：用 lazy import 让 macOS 用户不必装 pystray、Windows
    用户不必装 rumps——具体平台只在被选中时才 import。
    """
    import sys

    if sys.platform == "darwin":
        from menubar.tray_rumps import RumpsTray
        return RumpsTray(name, icon_path)

    # win32 / linux / freebsd / ... 一律走 pystray 路径
    from menubar.tray_pystray import PystrayTray
    return PystrayTray(name, icon_path)
