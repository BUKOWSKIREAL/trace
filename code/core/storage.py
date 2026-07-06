"""
Blob 存储层
=================
按 SHA-256 哈希存任意字节流到 .trace/objects/ 下。
任意文件类型一视同仁——文本、图片、PPT、二进制都是字节。

布局（仿 git 风格）：
    .trace/objects/
        1a/
            2b3c4d5e6f...  (62 字符)
        ef/
            ...

"""

import hashlib
import logging
import os
import tempfile
from pathlib import Path

from utils.hasher import blob_subpath, hash_bytes

logger = logging.getLogger("trace.storage")


# 流式读写时的块大小（64KB 是经验值，比 4K 快、比 1MB 省内存）
_CHUNK = 64 * 1024


class BlobStorage:
    """按内容哈希存储字节块；相同内容自动去重。"""

    def __init__(self, objects_dir: Path):
        # # 评审 ：不在构造函数里 mkdir，避免 Repository(...) 一构造
        # # 就在磁盘留痕，让 init_if_needed 里的 first_time 判断永远是 False。
        # # 目录创建由 ensure_dir() 显式负责，init_if_needed 调用一次即可。
        self.objects_dir = objects_dir

    def ensure_dir(self) -> None:
        """显式创建 objects_dir；由 Repository.init_if_needed 调用。"""
        self.objects_dir.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        """
        把字节流写入 blob 存储，返回它的 SHA-256 哈希。
        相同内容只存一份（已存在则不重写）。

        适合小数据（已经在内存里的 bytes）。大文件请用 put_file。
        """
        sha = hash_bytes(data)
        prefix, rest = blob_subpath(sha)
        path = self.objects_dir / prefix / rest
        if path.exists():
            logger.debug("blob 已存在，跳过写入: %s", sha[:8])
            return sha
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.debug("写入 blob: %s (%d 字节)", sha[:8], len(data))
        return sha

    def get(self, sha: str) -> bytes:
        """按哈希取回字节流。"""
        prefix, rest = blob_subpath(sha)
        path = self.objects_dir / prefix / rest
        return path.read_bytes()

    def has(self, sha: str) -> bool:
        prefix, rest = blob_subpath(sha)
        return (self.objects_dir / prefix / rest).exists()

    def put_file(self, file_path: Path) -> str:
        """
        流式 hash + 写盘，避免大文件一次读进内存。

        # 修正：原版 read_bytes() 把整个文件读进内存，
        # 几十 MB 的 .pptx 会让每次 commit 内存涨一个文件大小。
        # 改用"先写临时文件 + 算 hash，再原子 rename 到最终路径"。
        """
        h = hashlib.sha256()
        # tempfile 放在 objects_dir 下确保和最终位置同分区（rename 必须同分区）
        fd, tmp_str = tempfile.mkstemp(
            prefix=".tmp_", suffix=".blob", dir=self.objects_dir
        )
        tmp_path = Path(tmp_str)
        try:
            with os.fdopen(fd, "wb") as dst, open(file_path, "rb") as src:
                while True:
                    chunk = src.read(_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
                    dst.write(chunk)

            sha = h.hexdigest()
            prefix, rest = blob_subpath(sha)
            final = self.objects_dir / prefix / rest

            if final.exists():
                # 已有同内容 blob，删 tmp 直接复用现有
                tmp_path.unlink()
                logger.debug("blob 已存在，复用: %s", sha[:8])
            else:
                final.parent.mkdir(parents=True, exist_ok=True)
                # 原子 rename：要么完全成功要么完全失败，无中间状态
                os.replace(tmp_path, final)
                logger.debug("写入 blob (流式): %s", sha[:8])
            return sha
        except Exception:
            # 任何异常都要清理 tmp，避免堆积垃圾
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise
