"""
Snapshot 数据模型
=======================
一次 commit 里某个文件的 blob 引用，对应 snapshots 表 1 行。

# 人工编写
"""
from dataclasses import dataclass


@dataclass
class Snapshot:
    """一次提交里，某文件指向哪个 blob。"""
    commit_id: int
    file_path: str        # 相对工作目录的路径
    blob_hash: str        # sha256 十六进制
