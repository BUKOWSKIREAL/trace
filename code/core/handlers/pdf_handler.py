"""
PdfHandler — PDF 文件的 diff / 摘要
======================================
用 PyMuPDF (fitz) 抽取每页文本，按页为语义单位做行级比对：
- extract_text：逐页拼接，并加 "=== Page i ===" 分隔标题
- describe_change：统计变更页数，输出"修改 X 页（共 Y 页）"
- render_diff：基于解析后的文本走 ndiff，复用 Text 风格的标签着色

# AI 辅助生成（Claude 4.7 协助）
# 人工修正：
#   - PyMuPDF 对损坏 PDF 抛 FileDataError，必须捕获——不然 UI 端会崩
#   - 一律 try/finally 关 doc，避免内存/句柄泄漏
#   - 页头标记 "=== Page N ===" 让 diff 视图能看出"变化发生在哪一页"
"""
from __future__ import annotations

import difflib
import logging

import fitz  # PyMuPDF

from core.handlers.base import DiffLine, FileHandler, HandlerRegistry

logger = logging.getLogger("trace.handlers.pdf")


class PdfHandler(FileHandler):
    """PDF 文件 handler，按页提取文本后做行级 diff。"""

    extensions = [".pdf"]

    # ------------ 内部工具 ------------

    def _pages_text(self, blob: bytes) -> list[str] | None:
        """
        返回每页的文本列表；失败返回 None。
        # 人工注释：单独拆出来给 extract_text / describe_change / render_diff 复用，
        # 也方便统一捕获 FileDataError 这种"打不开"的异常。
        """
        doc = None
        try:
            doc = fitz.open(stream=blob, filetype="pdf")
            return [page.get_text() for page in doc]
        except Exception as e:
            logger.warning("PDF 解析失败: %s", e)
            return None
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    def _render_text(self, pages: list[str]) -> str:
        """把每页文本按 '=== Page i ===' 分隔拼成一段。"""
        parts: list[str] = []
        for i, txt in enumerate(pages):
            parts.append(f"=== Page {i + 1} ===")
            parts.append(txt)
        return "\n".join(parts)

    # ------------ 抽象方法实现 ------------

    def extract_text(self, blob: bytes) -> str | None:
        """抽取所有页文本；损坏的 PDF 返回 None（与 BinaryHandler 一致语义）。"""
        pages = self._pages_text(blob)
        if pages is None:
            return None
        return self._render_text(pages)

    def describe_change(self, old_blob: bytes, new_blob: bytes) -> str:
        """
        摘要："修改 X 页（共 Y 页）"。
        # 人工注释：以"页"为语义单位最贴合用户对 PDF 的心智模型；
        # 文本 handler 用"行"，PDF 用"页"，PPT 用"幻灯片"——同一抽象不同粒度。
        """
        old_pages = self._pages_text(old_blob)
        new_pages = self._pages_text(new_blob)

        if old_pages is None or new_pages is None:
            return "[文件解析失败：PDF 无法读取]"

        # 以新版总页数作为"共 Y 页"——用户更关心当前文档的样子
        total = len(new_pages)

        # 比较每页文本是否相同；长度不一致也算变更
        max_len = max(len(old_pages), len(new_pages))
        changed = 0
        for i in range(max_len):
            old_t = old_pages[i] if i < len(old_pages) else None
            new_t = new_pages[i] if i < len(new_pages) else None
            if old_t != new_t:
                changed += 1

        if changed == 0:
            return f"内容无变化（共 {total} 页）"
        return f"修改 {changed} 页（共 {total} 页）"

    def render_diff(self, old_blob: bytes, new_blob: bytes) -> list[DiffLine]:
        """
        行级 diff——和 TextHandler 一样跳过 '? ' hint 行。
        损坏 PDF 返回 meta 行而不是抛异常（保护 UI）。
        """
        if not old_blob and not new_blob:
            return []

        if not old_blob:
            new_pages = self._pages_text(new_blob)
            if new_pages is None:
                return [("meta", "[文件解析失败：PDF 无法读取，已跳过 diff]")]
            return self._text_as_diff(self._render_text(new_pages), "added")

        if not new_blob:
            old_pages = self._pages_text(old_blob)
            if old_pages is None:
                return [("meta", "[文件解析失败：PDF 无法读取，已跳过 diff]")]
            return self._text_as_diff(self._render_text(old_pages), "removed")

        old_pages = self._pages_text(old_blob)
        new_pages = self._pages_text(new_blob)

        if old_pages is None or new_pages is None:
            return [("meta", "[文件解析失败：PDF 无法读取，已跳过 diff]")]

        old_lines = self._render_text(old_pages).splitlines(keepends=False)
        new_lines = self._render_text(new_pages).splitlines(keepends=False)

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
            # '? ' 行跳过（diff 算法的内部提示，不展示给用户）

        return result


# 模块导入时自动注册
HandlerRegistry.register(PdfHandler())
