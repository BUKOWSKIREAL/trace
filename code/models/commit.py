"""
Commit 数据模型
=====================
一次自动提交的描述，对应 commits 表 1 行。

# 人工编写
"""
from dataclasses import dataclass, field


@dataclass
class Commit:
    """一次自动提交记录。"""
    time: str                          # ISO 8601 时间串
    author_agent: str                  # 归属的 agent 名
    detection_method: str = "auto"
    confidence: float = 1.0
    candidates: list[str] = field(default_factory=list)
    summary: str = ""                  # 简短描述
    id: int = 0                        # 落库后由 SQLite 自增填入
