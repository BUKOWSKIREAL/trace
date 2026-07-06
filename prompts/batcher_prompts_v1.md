# CommitBatcher 提示词 — v1

> 用于驱动 AI 生成 `code/daemon/batcher.py` 的结构化提示词。
> **版本 v1 — 实现每 agent 独立 timer 的防抖合并**。
> 后续 v2 会增加按文件去重、v3 会增加 agent 切换主动 flush。

---

## 完整提示词（直接复制粘贴给 AI 即可）

```
<role>
你是一位有 Python 多线程经验的后端工程师，熟悉 threading.Timer、
threading.Lock 的语义，能避免常见的并发陷阱（race condition、死锁、
timer 重入）。
</role>

<task>
请实现 CommitBatcher 类，做以下事：
1. 接收来自 watcher 的 (file_path, attribution) 事件流
2. 按 agent 维度暂存到 pending dict
3. 同一 agent 在 IDLE_WINDOW 秒内若无新事件，则把它的 pending 项一次性
   提交（commit）到 repository
4. 提供 force_flush_all() 接口供守护进程退出时清空待提交
</task>

<context>
项目背景：
- 工具叫"Trace"，监听一个工作目录里的文件变化，按 agent 颗粒度自动 commit
- CLI agent（如 Claude Code）一次任务通常 1-2 秒内连续修改十几个文件
- 如果每次文件变化都立刻 commit，提交记录会被淹没——所以要"防抖合并"

关键设计决策（必须遵守）：
- **每个 agent 一个独立 timer**（不能用单全局 timer），否则 A agent 的
  待提交会被 B agent 的新事件不断推迟，永远不落库
- 同一 agent 的 timer 被新事件重置时只取消"自己的"，不影响其他 agent
- pending dict 和 timers dict 必须用同一把 Lock 保护

数据契约：
- Attribution 已定义（参见 models/agent.py 的 AgentAttribution）
- Repository 已实现，提供 .commit(agent: str, files: list[Path], attribution: AgentAttribution) -> int

参数：
- IDLE_WINDOW_SECONDS = 2.0   （类常量）
- repository: Repository 实例    （构造时传入）
</context>

<constraints>
1. 必须保证线程安全：用 threading.Lock 保护 pending 和 timers
2. Timer 回调里不能直接持锁太久——避免和 add_change() 死锁
3. 同一文件多次修改 → flush 时只取最后一次（用 dict[file_path] → last_change
   做去重）
4. force_flush_all() 必须能在守护退出时被安全调用，不抛异常
5. 用 logging.getLogger("trace.batcher")
6. 中文注释
7. 不要写 if __name__ == "__main__" 测试块
</constraints>

<reasoning>
请在写代码前先在脑子里推演几个 race 场景，确保你的设计能应对：
- 场景 1：A agent 事件 1 进来，启 timer。1 秒后 A agent 事件 2 进来，
  应取消旧 timer 启新 timer。
- 场景 2：A agent 事件 1 进来，启 timer。1 秒后 B agent 事件 1 进来，
  B 启自己的 timer，A 的 timer 不动。2 秒后 A 的 timer 触发 → 只 flush A。
- 场景 3：用户 Ctrl+C 退出，pending 里有 A 和 B 两个 agent 各 5 个文件
  → force_flush_all 应该把它俩都落库。
- 场景 4：force_flush_all 期间正好有新事件进来 → 不能让新事件丢失。

如果你觉得场景 4 用 Lock 处理起来很别扭，请坦率指出并提建议。
</reasoning>

<format>
完整可运行的 Python 文件，包含：
1. 模块 docstring
2. import（threading, time, logging, pathlib, typing 等按需）
3. 一个 Change dataclass（封装 file_path / event_time / attribution）
4. CommitBatcher 类
5. 不要写 main 块

输出样例：
```python
\"\"\"模块说明\"\"\"

import threading, time, logging
from dataclasses import dataclass
from pathlib import Path
...

logger = logging.getLogger("trace.batcher")

@dataclass
class Change:
    ...

class CommitBatcher:
    IDLE_WINDOW_SECONDS = 2.0
    def __init__(self, repository): ...
    def add_change(self, file_path, attribution): ...
    def _flush_agent(self, agent): ...
    def force_flush_all(self): ...
```
</format>

<防幻觉>
- 不要编造 threading.Timer 的 API（它只有 .start() / .cancel() / .is_alive()）
- 不要用 asyncio——本项目是同步 + 线程模型
- 不要把 Lock 当 RLock 用——本类不需要重入锁
- 如果你不确定 macOS 上 threading.Timer 是否有平台差异，直说不确定
</防幻觉>
```

---

## 这个提示词的关键设计决策

| 章节 | 设计意图 |
|------|---------|
| `<task>` 第 3 条 | 用"IDLE_WINDOW 秒内无新事件"这个词，明确防抖语义不是"固定窗口" |
| `<context>` 关键设计 | 把"每 agent 独立 timer"这个**最容易写错**的点上升到设计约束，AI 跑偏会立即被注意 |
| `<reasoning>` | 用 4 个具体场景强迫 AI 在脑子里推演 race condition。**这是 v1 比 v0 最大的改进**——直接写"考虑并发"AI 经常糊弄，但给出具体场景就糊弄不过去 |
| `<format>` 第 3 条 | 显式要求把 Change 提到独立 dataclass，避免 AI 用 tuple 凑合 |

---

## 预期 AI 输出（人工初步审查清单）

应该看到的：
- ✅ `self.pending: dict[str, list[Change]]`
- ✅ `self.timers: dict[str, threading.Timer]`
- ✅ `self.lock = threading.Lock()`
- ✅ `add_change` 里只 cancel **自己**的 timer
- ✅ `_flush_agent` 里 dedup file_path（取 last）
- ✅ `force_flush_all` 里复制 keys 后再迭代（避免边迭代边改）

**人工修正常见点**：
- AI 可能漏 force_flush_all 的 thread-safety（复制 keys 时也要拿锁）→ 人工修
- AI 可能在 `_flush_agent` 里 commit 失败时崩溃 → 加 try/except 兜底
- AI 可能没在 flush 后清空 `self.timers.pop(agent, None)` → 检查并补

---

## 迭代历史

- **v1（本版）**：每 agent 独立 timer + force_flush_all。这是设计上发现"全局单 timer 会饿死 A agent"后修正的。
