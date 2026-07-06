"""
Project 数据模型
======================
一个被追踪的工作目录的元信息。当前版本按单工作区创建一个 Project。

# 人工编写
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Project:
    name: str               # 项目显示名（默认取目录名）
    workspace: Path         # 工作目录绝对路径
    trace_dir: Path         # .trace/ 目录路径

    @classmethod
    def from_workspace(cls, workspace: Path) -> "Project":
        """从工作目录路径推 Project 元信息。"""
        ws = workspace.expanduser().resolve()
        return cls(
            name=ws.name,
            workspace=ws,
            trace_dir=ws / ".trace",
        )
