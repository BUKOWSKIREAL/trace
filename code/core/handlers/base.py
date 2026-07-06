"""
FileHandler 抽象基类 + HandlerRegistry
=========================================
按文件类型分发"如何显示 diff / 摘要变化"的策略。
**仅展示层**——存储层一律按字节 SHA-256 处理，与文件类型无关。

HandlerRegistry 负责按扩展名分发到文本、Office、PDF、图片或二进制兜底 handler。

# AI 辅助生成（Claude 4.7 协助）
# 人工修正：
#   - HandlerRegistry 改为 dict 注册（不用 if-elif 链），符合开闭原则
#   - 加 _safe_decode() 工具方法在 base，让 Text/Docx/Pdf 等都能复用
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger("trace.handlers")


# diff 行的标签——前端按此着色：
#   normal  = 未变化的上下文
#   added   = 新增的行（绿色 / +）
#   removed = 删除的行（红色 / -）
#   meta    = 元信息（"二进制不可 diff" / "文件被重命名" 等）
DiffTag = str
DiffLine = tuple[DiffTag, str]


class FileHandler(ABC):
    """
    所有 handler 的抽象基类。

    子类必须声明 `extensions: list[str]` 类属性（小写、含点，例如 ['.py', '.txt']），
    并实现 3 个抽象方法。
    """

    extensions: ClassVar[list[str]] = []

    @abstractmethod
    def extract_text(self, blob: bytes) -> str | None:
        """
        从 blob 字节里提取可比对的文本。
        - 文本类 handler 返回解码后的字符串
        - 二进制 handler 返回 None（表示"这不是文本，没法做内容 diff"）
        """

    @abstractmethod
    def describe_change(self, old_blob: bytes, new_blob: bytes) -> str:
        """
        返回一行人类可读的变更摘要。

        示例：
        - 文本："+12 行 / -3 行"
        - 二进制："大小 1.2KB → 1.5KB, 哈希 a1b2c3d4 → e5f6g7h8"
        """

    @abstractmethod
    def render_diff(self, old_blob: bytes, new_blob: bytes) -> list[DiffLine]:
        """
        返回 [(tag, line)] 列表给 UI 渲染。
        tag 取值见模块顶部 DiffTag 注释。
        """

    # ------- 工具方法（基类共享，避免子类重复造轮子）-------

    @staticmethod
    def _safe_decode(data: bytes) -> str:
        """
        统一的安全 UTF-8 解码——文件可能是 UTF-16 / GBK / 损坏，
        errors='replace' 保证不抛异常，无效字节变成替换符 U+FFFD。
        # 人工注释：这是文本类 handler 都要踩的坑，所以放基类。
        """
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _size_human(n: int) -> str:
        """字节数转人类可读，如 1234 → '1.2KB'。"""
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
            n /= 1024  # type: ignore[assignment]
        return f"{n:.1f}TB"

    @staticmethod
    def _text_as_diff(text: str, tag: DiffTag) -> list[DiffLine]:
        """把整段提取文本按行标成 added/removed，用于新增/删除文件。"""
        return [(tag, line) for line in text.splitlines()]


class HandlerRegistry:
    """
    按文件扩展名分发到具体 handler。
    **加新类型只需要调一次 register()——不动 for_path 的代码**（开闭原则）。
    """

    # 类级注册表，模块导入时由各 handler 文件自填
    _by_ext: dict[str, FileHandler] = {}
    _fallback: FileHandler | None = None  # BinaryHandler 兜底实例

    @classmethod
    def register(cls, handler: FileHandler) -> None:
        """把 handler 的所有 extensions 注册到 _by_ext。"""
        for ext in handler.extensions:
            ext_lower = ext.lower()
            if ext_lower in cls._by_ext:
                logger.warning(
                    "扩展名 %s 已被 %s 注册，将被 %s 覆盖",
                    ext_lower,
                    type(cls._by_ext[ext_lower]).__name__,
                    type(handler).__name__,
                )
            cls._by_ext[ext_lower] = handler

    @classmethod
    def register_fallback(cls, handler: FileHandler) -> None:
        """设置兜底 handler——查不到匹配扩展名时返回它。"""
        cls._fallback = handler

    @classmethod
    def for_path(cls, path: Path) -> FileHandler:
        """
        按 path 的扩展名查 handler；查不到返回 fallback（BinaryHandler）。
        """
        ext = path.suffix.lower()
        h = cls._by_ext.get(ext)
        if h is not None:
            return h
        if cls._fallback is None:
            raise RuntimeError(
                "HandlerRegistry 未设置 fallback；请确保 binary_handler 模块被 import"
            )
        return cls._fallback

    @classmethod
    def known_extensions(cls) -> list[str]:
        """供 UI 显示"已支持哪些类型"。"""
        return sorted(cls._by_ext.keys())
