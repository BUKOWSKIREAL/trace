"""
TextHandler — 文本类文件的 diff / 摘要
==========================================
处理 .py / .txt / .md / .json / .csv 等纯文本文件。

# AI 辅助生成（Claude 4.7 协助）
# 人工修正：
#   - difflib.ndiff 输出含 '? ' 提示行（位置 hint），要过滤掉
#   - errors='replace' 已在基类 _safe_decode 里统一了，这里直接复用
#   - describe_change 统计行数时只数 '+ ' 和 '- ' 开头，不含 '  ' '? '
"""
from __future__ import annotations

import difflib
import logging

from core.handlers.base import DiffLine, FileHandler, HandlerRegistry

logger = logging.getLogger("trace.handlers.text")


class TextHandler(FileHandler):
    """
    文本文件 handler，做行级 diff。
    """

    extensions = [".py", ".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".toml", ".ini", ".sh"]

    def extract_text(self, blob: bytes) -> str | None:
        """返回 UTF-8 解码后的字符串；遇到非 UTF-8 字节用替换符不抛异常。"""
        return self._safe_decode(blob)

    def describe_change(self, old_blob: bytes, new_blob: bytes) -> str:
        """
        返回 "+X 行 / -Y 行"。
        # 人工注释：用 ndiff 比对，统计 '+ ' 和 '- ' 开头的行；
        # '? ' 是 difflib 的内嵌位置提示（不是真正的变更行），必须过滤。
        """
        old_lines = self._safe_decode(old_blob).splitlines(keepends=False)
        new_lines = self._safe_decode(new_blob).splitlines(keepends=False)
        added = removed = 0
        for line in difflib.ndiff(old_lines, new_lines):
            if line.startswith("+ "):
                added += 1
            elif line.startswith("- "):
                removed += 1
            # '  ' 是未变化、'? ' 是 hint，都忽略

        if added == 0 and removed == 0:
            # 内容字节不同（hash 不同才会调本函数），但行级一致——
            # 可能是行尾符 / 末尾换行差异
            return "仅空白/换行差异（行级一致）"
        return f"+{added} 行 / -{removed} 行"

    def render_diff(self, old_blob: bytes, new_blob: bytes) -> list[DiffLine]:
        """
        返回 [(tag, content)] 列表给 UI 渲染。tag ∈ {normal, added, removed}。
        # 人工注释：故意跳过 '? ' hint 行——它们是 diff 算法的内部输出，
        # 给 UI 展示反而干扰阅读；用户想要的是清晰的"加了什么 / 减了什么"。
        """
        old_lines = self._safe_decode(old_blob).splitlines(keepends=False)
        new_lines = self._safe_decode(new_blob).splitlines(keepends=False)

        result: list[DiffLine] = []
        for line in difflib.ndiff(old_lines, new_lines):
            tag2 = line[:2]
            content = line[2:]
            if tag2 == "  ":
                result.append(("normal", content))
            elif tag2 == "+ ":
                result.append(("added", content))
            elif tag2 == "- ":
                result.append(("removed", content))
            # '? ' 行跳过

        return result


# 模块导入时自动注册
HandlerRegistry.register(TextHandler())
