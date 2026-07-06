"""
SHA-256 内容寻址工具
=======================
计算字节流或文件的 SHA-256 哈希，用于 blob 存储和文件唯一标识。

# 人工编写
"""
import hashlib
from pathlib import Path


def hash_bytes(data: bytes) -> str:
    """计算字节流的 SHA-256（十六进制串，64 字符）。"""
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path, chunk_size: int = 64 * 1024) -> str:
    """流式计算文件的 SHA-256，避免一次读入大文件占内存。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def blob_subpath(sha: str) -> tuple[str, str]:
    """
    把哈希拆成"前两字符 + 后 62 字符"，做 git 风格的两级目录。
    例：'1a2b3c...' → ('1a', '2b3c...')
    这样 objects/ 下不会有 1 个超大目录卡死文件系统。
    """
    return sha[:2], sha[2:]
