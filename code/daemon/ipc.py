"""
IPC — 守护线程 ↔ 主线程 UI 的事件管道
======================================
基于 queue.Queue 的线程安全消息桥，用于把后台事件投递给系统托盘和操作台。

设计哲学（参见项目计划核心五）：
    后台线程绝不能直接调 Tk / rumps API → 用 queue 投递事件给主线程
    主线程用 rumps.Timer / root.after 周期性 drain 队列


"""

import logging
import queue
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("trace.ipc")


@dataclass
class UIEvent:
    """投递给 UI 主线程的事件。"""

    type: str  # 'new_commit' / 'agent_changed' / 'error' 等
    payload: dict[str, Any] = field(default_factory=dict)


# 守护进程 → UI 的事件队列（全局单例）。
# UI 启动后从这里 get_nowait()；后台线程任意时刻 put()。
ui_queue: "queue.Queue[UIEvent]" = queue.Queue()


def emit(event_type: str, **payload) -> None:
    """守护线程任何时候都能用这个函数往 UI 队列投递事件，不阻塞。"""
    try:
        ui_queue.put_nowait(UIEvent(type=event_type, payload=payload))
        logger.debug("UI 事件投递: %s %s", event_type, payload)
    except queue.Full:
        # 队列满（默认无限大，理论不发生；防御代码）
        logger.warning("UI 事件队列已满，丢弃: %s", event_type)


def drain() -> list[UIEvent]:
    """
    主线程调用：把队列里所有事件取出来。非阻塞。
    UI 在 root.after / rumps.Timer 里周期性调这个函数。
    """
    events: list[UIEvent] = []
    while True:
        try:
            events.append(ui_queue.get_nowait())
        except queue.Empty:
            break
    return events
