"""
Change — 一次待提交的文件变化
================================
batcher 和 repository 都要引用这个类型；放在 models/ 层避免
core ↔ daemon 的层级倒置。

# 人工编写（评审 #2 重构：从 daemon/batcher.py 抽出来，加 kind 字段）
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from models.agent import AgentAttribution


@dataclass
class Change:
    """
    一次待提交的文件变化记录。

    kind 区分两种事件：
        - "upsert"：文件被新建或修改 → commit 时读字节、算 hash、写 blob、入 manifest
        - "delete"：文件被删除         → commit 时不读字节，仅在 new_manifest 里删除该 path
    """

    file_path: Path
    event_time: float
    attribution: AgentAttribution
    kind: Literal["upsert", "delete"] = "upsert"
