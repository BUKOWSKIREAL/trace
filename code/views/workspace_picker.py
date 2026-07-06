"""
工作区选择器（Tkinter 一次性对话框）
====================================
对外只有一个函数 pick_workspace(initial=None)。**不起 mainloop()**，
用完销毁——便于将来嵌入 rumps menubar 流程（rumps 已占住 NSApplication
run loop，Tkinter 这里只借窗体不抢 loop）。

# 人工编写
"""
import logging
from pathlib import Path
from tkinter import Tk, filedialog

logger = logging.getLogger("trace.picker")


def pick_workspace(initial: Path | None = None) -> Path | None:
    """
    弹一个文件夹选择对话框，返回用户选的工作目录。
    用户取消返回 None。

    initial：picker 打开时的起始目录（推荐传上次工作区）。

    # 人工注释（实现细节）：
    #   - 用 Tk() + withdraw() 隐藏主窗口，只显示原生 NSOpenPanel 风格的
    #     文件夹选择器；这样既走 Tkinter（满足作业 GUI 要求的一部分），
    #     又不留一个空白主窗口在屏幕上
    #   - finally 里 destroy()：不释放的话进程退出前会有"幽灵 Tk root"
    #     残留，将来嵌入 rumps 时会冲突
    #   - askdirectory 返回空字符串表示用户取消，要显式判
    """
    root = Tk()
    root.withdraw()  # 不显示主窗口
    try:
        initialdir = str(initial) if initial and initial.is_dir() else str(Path.home())
        chosen = filedialog.askdirectory(
            title="Trace — 选择要追踪的工作目录",
            initialdir=initialdir,
            mustexist=True,
        )
    finally:
        root.destroy()

    if not chosen:
        logger.info("用户取消选择工作区")
        return None

    p = Path(chosen).expanduser().resolve()
    if not p.is_dir():
        logger.error("用户选的路径不是有效目录: %s", p)
        return None
    return p
