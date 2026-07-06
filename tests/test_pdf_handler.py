"""
PdfHandler 单元测试
======================
覆盖 extract_text / describe_change / render_diff / 注册 / 健壮性。
通过 PyMuPDF 在内存里构造真实 PDF blob，不依赖任何外部 fixture 文件。

# 人工编写
"""
import sys
import unittest
from pathlib import Path

# 让 tests/ 也能 import core.*
ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

import fitz  # PyMuPDF

from core.handlers import HandlerRegistry  # noqa: E402
from core.handlers.pdf_handler import PdfHandler  # noqa: E402  触发注册


def _make_pdf(pages: list[str]) -> bytes:
    """构造一个 N 页 PDF，每页写一行指定的文本。返回 bytes blob。"""
    doc = fitz.open()
    try:
        for text in pages:
            page = doc.new_page()
            page.insert_text((72, 72), text)
        return doc.tobytes()
    finally:
        doc.close()


class TestExtractText(unittest.TestCase):
    def setUp(self):
        self.h = PdfHandler()

    def test_extract_single_page(self):
        blob = _make_pdf(["Hello PDF World"])
        out = self.h.extract_text(blob)
        self.assertIsInstance(out, str)
        self.assertIn("=== Page 1 ===", out)
        self.assertIn("Hello PDF World", out)

    def test_extract_multi_page_with_separators(self):
        blob = _make_pdf(["First page", "Second page", "Third page"])
        out = self.h.extract_text(blob)
        self.assertIn("=== Page 1 ===", out)
        self.assertIn("=== Page 2 ===", out)
        self.assertIn("=== Page 3 ===", out)
        self.assertIn("First page", out)
        self.assertIn("Second page", out)
        self.assertIn("Third page", out)

    def test_extract_corrupt_returns_none(self):
        out = self.h.extract_text(b"this is not a pdf, just junk")
        self.assertIsNone(out)


class TestDescribeChange(unittest.TestCase):
    def setUp(self):
        self.h = PdfHandler()

    def test_describe_no_change(self):
        # 同样内容生成两个 blob——PyMuPDF 可能在元数据里加时间戳，
        # 但 _pages_text 比的只是 page 文本，所以应判定为无变化。
        old = _make_pdf(["alpha", "beta"])
        new = _make_pdf(["alpha", "beta"])
        desc = self.h.describe_change(old, new)
        self.assertIn("无变化", desc)
        self.assertIn("共 2 页", desc)

    def test_describe_one_page_modified(self):
        old = _make_pdf(["alpha", "beta", "gamma"])
        new = _make_pdf(["alpha", "BETA CHANGED", "gamma"])
        desc = self.h.describe_change(old, new)
        self.assertEqual(desc, "修改 1 页（共 3 页）")

    def test_describe_page_added(self):
        old = _make_pdf(["alpha"])
        new = _make_pdf(["alpha", "beta"])
        desc = self.h.describe_change(old, new)
        # 新增了一页——共 2 页，1 页变化
        self.assertIn("共 2 页", desc)
        self.assertIn("修改 1 页", desc)


class TestRenderDiff(unittest.TestCase):
    def setUp(self):
        self.h = PdfHandler()

    def test_render_diff_has_expected_tags(self):
        old = _make_pdf(["keep me", "old line"])
        new = _make_pdf(["keep me", "new line"])
        out = self.h.render_diff(old, new)
        tags = [t for t, _ in out]
        self.assertIn("added", tags)
        self.assertIn("removed", tags)
        # 不应出现 difflib 的 '? ' hint
        self.assertNotIn("?", tags)

    def test_render_diff_contains_content(self):
        old = _make_pdf(["page one before"])
        new = _make_pdf(["page one after"])
        out = self.h.render_diff(old, new)
        contents = " ".join(c for _, c in out)
        # 应当能在某个 diff 行里看到关键词
        self.assertTrue("before" in contents or "after" in contents)
        # 也应当含 page 头
        self.assertTrue(any("=== Page 1 ===" in c for _, c in out))

    def test_render_diff_for_new_pdf_treats_all_text_as_added(self):
        new = _make_pdf(["new pdf text"])
        out = self.h.render_diff(b"", new)

        self.assertTrue(out)
        self.assertTrue(all(tag == "added" for tag, _ in out))
        contents = " ".join(c for _, c in out)
        self.assertIn("=== Page 1 ===", contents)
        self.assertIn("new pdf text", contents)

    def test_render_diff_for_deleted_pdf_treats_all_text_as_removed(self):
        old = _make_pdf(["old pdf text"])
        out = self.h.render_diff(old, b"")

        self.assertTrue(out)
        self.assertTrue(all(tag == "removed" for tag, _ in out))
        contents = " ".join(c for _, c in out)
        self.assertIn("=== Page 1 ===", contents)
        self.assertIn("old pdf text", contents)


class TestRegistry(unittest.TestCase):
    def test_pdf_extension_routes_to_pdf_handler(self):
        h = HandlerRegistry.for_path(Path("foo.pdf"))
        self.assertIsInstance(h, PdfHandler)

    def test_pdf_extension_case_insensitive(self):
        h = HandlerRegistry.for_path(Path("REPORT.PDF"))
        self.assertIsInstance(h, PdfHandler)

    def test_pdf_in_known_extensions(self):
        self.assertIn(".pdf", HandlerRegistry.known_extensions())


class TestRobustness(unittest.TestCase):
    """损坏 / 异常输入不能让 UI 崩。"""

    def setUp(self):
        self.h = PdfHandler()

    def test_describe_change_on_corrupt_blob_returns_meta_message(self):
        good = _make_pdf(["ok"])
        bad = b"\x00\x01\x02 totally not a pdf"
        desc = self.h.describe_change(good, bad)
        # 应当是失败提示而不是抛异常
        self.assertIn("解析失败", desc)

    def test_render_diff_on_corrupt_blob_returns_meta_line(self):
        good = _make_pdf(["ok"])
        bad = b"junk bytes ~~~"
        out = self.h.render_diff(good, bad)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], "meta")
        self.assertIn("解析失败", out[0][1])

    def test_empty_blob_does_not_crash(self):
        # 完全空的 blob——extract_text 不应抛
        out = self.h.extract_text(b"")
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
