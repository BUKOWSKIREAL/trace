# Agent Detector 提示词 — v1

> 用于驱动 AI 生成 `code/daemon/detectors/cli_detector.py` 的结构化提示词。
> **版本 v1 — 仅覆盖类别 1（CLI agents）的进程枚举功能**。
> 后续 v2 会增加多类别支持、v3 会增加多 agent 歧义裁决、v4 会改成主动采样架构。

---

## 完整提示词（直接复制粘贴给 Claude / Codex / GPT 即可）

```
<role>
你是一位有 5 年 macOS 系统编程经验的 Python 后端工程师。你熟悉
psutil 库的常用 API，了解进程的 cwd、open_files、cmdline 等概念，
能写出健壮的、对异常友好的代码。
</role>

<task>
请实现一个函数 scan_cli_agents(workspace: Path) -> list[AgentInstance]，
枚举当前在 workspace 目录里活跃的所有已知 CLI AI agent 进程。

返回的 AgentInstance 列表会被上层调用，用于判定"某个文件被改时是哪个
agent 干的"。
</task>

<context>
项目背景：
- 工具叫"Trace"（Trace），目标是追踪多个 AI agent 协作时的修改归属。
- CLI agent 是项目最容易识别的类别（类别 1），本任务只处理这类。
- 已知的 CLI agent 进程名清单（写死即可）：
    KNOWN_CLI_AGENTS = {
        "claude":   {"display_name": "Claude Code", "color": "#D97757"},
        "codex":    {"display_name": "Codex CLI",   "color": "#10A37F"},
        "openclaw": {"display_name": "OpenClaw",    "color": "#5E6AD2"},
    }
- 进程的 cwd 必须在 workspace 内（或等于 workspace），否则不算"在这个项目里活动"。
- 用户可能在多个项目里同时跑 claude，所以必须用 cwd 过滤。

数据类参考（已定义在 models/agent.py）：
    @dataclass
    class AgentInstance:
        name: str             # 'claude' / 'codex' / 'openclaw'
        display_name: str
        category: str         # 这里恒为 'cli'
        pid: int = 0
        cwd: str = ""
        started_at: float = 0.0
</context>

<constraints>
1. 必须用 psutil.process_iter(['pid', 'name', 'cwd', 'create_time']) 一次性
   取所有字段；不要在循环里再单独调 Process(pid).cwd() 之类的二次查询。
2. psutil.AccessDenied 和 psutil.NoSuchProcess 必须用 try/except 静默吞掉
   并 continue（macOS 上枚举系统进程会经常碰到，不能让单进程错误中断扫描）。
3. 工作目录比对必须支持嵌套场景：例如 workspace=/code，进程 cwd=/code/sub
   也算在工作目录内。提示用 Path 的 .parents 属性或 is_relative_to。
4. 不要假设进程名字有路径前缀，psutil 在 macOS 上 .name() 返回的就是
   命令短名（'claude' 而不是 '/usr/local/bin/claude'）。
5. 性能：本函数会被每秒调用 1 次。在 1000 进程的机器上耗时应 < 50ms。
   不能对每个进程都做 IO（比如读 /proc）。
6. 不要使用 sudo / 高权限 API。
7. 中文注释。
</constraints>

<防幻觉>
- 如果你不确定 psutil 某个 API 是否存在，请直说"不确定，需要查文档"，
  不要编造 API 名（比如 psutil.Process.workdir() 是不存在的，正确的是 .cwd()）。
- 如果你不确定 macOS 下进程 cwd 拿不到时会抛什么异常，请直说，不要编造异常名。
- 如果上述 KNOWN_CLI_AGENTS 字典里有项目实际不需要的字段（比如 color 在
  本函数里其实用不到），可以指出，但不要擅自删除。
</防幻觉>

<format>
请输出一个完整可运行的 Python 文件：
1. 文件顶部用 """ ... """ 三引号文档字符串说明模块用途
2. 必要的 import
3. KNOWN_CLI_AGENTS 字典（全局常量，全大写）
4. scan_cli_agents 函数（含 type hint 和 docstring）
5. 如果你想加 logger，请用 logging.getLogger("trace.detector.cli")
6. 不要写 if __name__ == "__main__" 测试块（测试单独写）

输出格式样例：
```python
\"\"\"docstring\"\"\"

import logging
from pathlib import Path
...

logger = logging.getLogger("trace.detector.cli")

KNOWN_CLI_AGENTS = { ... }

def scan_cli_agents(workspace: Path) -> list[AgentInstance]:
    \"\"\"docstring\"\"\"
    ...
```
</format>
```

---

## 这个提示词为什么这么写（人工设计的取舍）

| 章节 | 设计意图 |
|------|---------|
| `<role>` | 给 AI 一个具体的工程师身份。"5 年经验"约束它产出有"成熟感"的代码，而不是教科书式的简化版 |
| `<task>` | 一句话说清交付。强调"上层会调用"让 AI 注意返回值的契约 |
| `<context>` | 把上下游设计、数据类、特殊业务规则（cwd 过滤）全交代清楚。**v1 这里只讲了类别 1，所以输出只覆盖 CLI；v2 加 GUI 时会扩这里** |
| `<constraints>` | 6 条硬约束，每条都是真实工程坑点：性能、异常、API 误用等 |
| 防幻觉 | 明确允许 AI 说"不确定"，并举出常见编造例子（`.workdir()` 是经典误用） |
| `<format>` | 强制输出形态，避免 AI 配 "首先我们..." 之类的废话散文 |

---

## 预期 AI 输出（人工初步审查清单）

跑完这个提示词，应该得到的代码具备：
- ✅ 全函数被 try/except 包住
- ✅ 用 `psutil.process_iter(['pid', 'name', 'cwd', 'create_time'])` 一次拿字段
- ✅ 工作目录比对用 `Path.is_relative_to` 或 `parents`
- ✅ 中文注释
- ✅ `logger.debug(...)` 在异常处吞日志

**人工修正常见点**（v1 阶段大概率要改）：
- AI 可能漏写 `psutil.ZombieProcess` 异常（macOS 偶尔会冒）→ 人工补
- AI 可能用 `os.path.commonpath` 而非 `Path.is_relative_to` → 看情况是否换
- 函数 docstring 可能写得太短 → 补完整
- 默认 logger 名可能不一致 → 改成约定的 `"trace.detector.cli"`

---

## 迭代历史（这一节为空，将在 v2/v3 写完后补充）

- **v0（调研阶段）**：放弃 ESF（Endpoint Security Framework）方案，因为需要 Apple 开发者证书 + entitlement + root，学生项目门槛过高。决定用 psutil 做"会话级归属"。
- **v1（本版）**：仅 CLI 类别，被动查询。AI 第一次产出已能跑通基本场景。

