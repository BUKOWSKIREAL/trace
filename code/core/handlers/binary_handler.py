"""
BinaryHandler — 兜底处理任意未知/二进制类型
==============================================
任何 .zip / .png / .pptx / .xlsx / 未知扩展名都走这里：
- 能存能恢复（因为 storage 按字节 SHA-256 处理，与类型无关）
- 不做语义 diff，只显示"大小变化、hash 变化"
- 给用户清晰的"我知道它变了，但不知道变了什么内容"反馈

文本、Office、PDF、图片等可识别类型会走专用 handler；识别不了仍掉到这里——
**始终有兜底**。

# AI 辅助生成（Claude 4.7 协助）
# 人工修正：
#   - hash 只显示前 8 字符（完整 64 字符占屏太长）
#   - extensions 设为空列表——通过 register_fallback 而非 register 注册
"""
from __future__ import annotations

import hashlib
import logging

from core.handlers.base import DiffLine, FileHandler, HandlerRegistry

logger = logging.getLogger("trace.handlers.binary")


class BinaryHandler(FileHandler):
    """
    兜底 handler。不绑定扩展名——通过 HandlerRegistry.register_fallback 注册。
    """

    extensions: list[str] = []  # 不绑定具体扩展名

    def extract_text(self, blob: bytes) -> str | None:
        """二进制没有"文本"概念，返回 None。"""
        return None

    def describe_change(self, old_blob: bytes, new_blob: bytes) -> str:
        """
        格式："大小 {old_size} → {new_size}，哈希 {old_hash[:8]} → {new_hash[:8]}"
        # 人工注释：hash 只取前 8 字符——既能让用户感知"变了"，
        # 又不会让一行摘要被 64 字符的 SHA-256 占满。
        """
        old_size = len(old_blob)
        new_size = len(new_blob)
        old_hash = hashlib.sha256(old_blob).hexdigest()[:8]
        new_hash = hashlib.sha256(new_blob).hexdigest()[:8]
        return (
            f"大小 {self._size_human(old_size)} → {self._size_human(new_size)}，"
            f"哈希 {old_hash} → {new_hash}"
        )

    def render_diff(self, old_blob: bytes, new_blob: bytes) -> list[DiffLine]:
        """二进制不做内容 diff，返回单行 meta 信息让 UI 显示。"""
        return [("meta", "二进制文件，未做内容 diff。请用对应的应用程序打开查看。")]


# 模块导入时自动设为兜底
HandlerRegistry.register_fallback(BinaryHandler())
