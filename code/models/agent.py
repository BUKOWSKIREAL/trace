"""
Agent 数据模型
====================
代表一个被识别的 AI agent（CLI/GUI/Web/脚本），可序列化到 agents 表。

# 人工编写
"""

from dataclasses import dataclass, field


@dataclass
class Agent:
    """Agent 注册表条目，对应 agents 表 1 行。"""

    name: str  # 唯一 id, 如 'claude' / 'word-copilot'
    category: str  # 'cli' | 'gui_app' | 'web' | 'local_script'
    match_rules: dict  # 多模式匹配规则
    display_name: str  # 给用户看的名字
    color: str  # 16 进制颜色，如 '#D97757'


@dataclass
class AgentInstance:
    """
    AgentDetector 扫描到的"活跃实例"，是运行时对象（不入库）。
    一个 Agent 类型可能有多个 AgentInstance（比如同时跑两个 claude 进程）。
    """

    name: str
    display_name: str
    category: str
    pid: int = 0
    cwd: str = ""
    started_at: float = 0.0  # Unix timestamp


@dataclass
class AgentAttribution:
    """
    归属决策结果。每次 watchdog 事件触发一次决策，产生一个本类实例。

    # 人工修正：candidates 用 field(default_factory=list) 默认空列表，
    # 而不是 Optional[None] + __post_init__——后者类型注解仍是 None-able，
    # 调用方在类型检查下还得 if is None 判一遍，多余且容易出错。
    """

    agent: str  # 'claude' / 'word-copilot' / 'human' / 'unknown'
    confidence: float  # 0.0 - 1.0
    detection_method: str = "auto"  # 'auto' | 'manual_override' | 'fallback'
    candidates: list[str] = field(default_factory=list)  # ambiguous 时填多个候选
    ambiguous: bool = False
