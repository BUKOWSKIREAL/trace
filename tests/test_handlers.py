"""
handlers 单元测试
====================
覆盖 FileHandler / TextHandler / BinaryHandler / HandlerRegistry 的核心契约。

# 人工编写
"""
import sys
import unittest
from pathlib import Path

# 让 tests/ 也能跑（项目用相对 import 的方式跑 main，这里也对齐）
ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from core.handlers import HandlerRegistry  # noqa: E402
from core.handlers.base import FileHandler  # noqa: E402
from core.handlers.binary_handler import BinaryHandler  # noqa: E402
from core.handlers.text_handler import TextHandler  # noqa: E402


class TestHandlerRegistry(unittest.TestCase):
    def test_text_extensions_register(self):
        h = HandlerRegistry.for_path(Path("foo.py"))
        self.assertIsInstance(h, TextHandler)

        h = HandlerRegistry.for_path(Path("README.md"))
        self.assertIsInstance(h, TextHandler)

    def test_unknown_extension_falls_back_to_binary(self):
        h = HandlerRegistry.for_path(Path("blob.xyz"))
        self.assertIsInstance(h, BinaryHandler)

        # 没扩展名也走兜底
        h = HandlerRegistry.for_path(Path("Makefile"))
        self.assertIsInstance(h, BinaryHandler)

        # 二进制兜底也覆盖压缩包等
        h = HandlerRegistry.for_path(Path("archive.zip"))
        self.assertIsInstance(h, BinaryHandler)

    def test_extension_case_insensitive(self):
        h = HandlerRegistry.for_path(Path("FOO.PY"))
        self.assertIsInstance(h, TextHandler)

    def test_known_extensions_listed(self):
        exts = HandlerRegistry.known_extensions()
        self.assertIn(".py", exts)
        self.assertIn(".md", exts)
        self.assertIn(".csv", exts)


class TestTextHandler(unittest.TestCase):
    def setUp(self):
        self.h = TextHandler()

    def test_extract_text_basic(self):
        self.assertEqual(self.h.extract_text(b"hello"), "hello")

    def test_extract_text_non_utf8_does_not_crash(self):
        # UTF-16 编码的"你好"开头会有 BOM 字节，UTF-8 解不出来——必须不抛
        garbage = b"\xff\xfe\x60\x4f\x7d\x59"  # UTF-16 LE 的"你好"
        out = self.h.extract_text(garbage)
        self.assertIsInstance(out, str)
        # 含替换符（不报错就行）

    def test_describe_change_lines(self):
        old = b"def f():\n    return 1\n"
        new = b"def f():\n    return 2\n"
        desc = self.h.describe_change(old, new)
        self.assertEqual(desc, "+1 行 / -1 行")

    def test_describe_change_pure_add(self):
        old = b"line1\n"
        new = b"line1\nline2\nline3\n"
        desc = self.h.describe_change(old, new)
        self.assertEqual(desc, "+2 行 / -0 行")

    def test_describe_change_whitespace_only(self):
        # 末尾换行不一样，行级一致
        desc = self.h.describe_change(b"a\nb\n", b"a\nb")
        self.assertEqual(desc, "仅空白/换行差异（行级一致）")

    def test_render_diff_tags(self):
        old = b"a\nb\nc\n"
        new = b"a\nX\nc\n"
        out = self.h.render_diff(old, new)
        tags = [t for t, _ in out]
        # 应当看到至少一个 added 和一个 removed
        self.assertIn("added", tags)
        self.assertIn("removed", tags)
        self.assertIn("normal", tags)
        # 不应该出现 difflib 的 '? ' hint 行
        self.assertNotIn("?", tags)
        # 内容应当含 b 和 X
        contents = " ".join(c for _, c in out)
        self.assertIn("b", contents)
        self.assertIn("X", contents)


class TestBinaryHandler(unittest.TestCase):
    def setUp(self):
        self.h = BinaryHandler()

    def test_extract_text_returns_none(self):
        self.assertIsNone(self.h.extract_text(b"\x00\x01\x02"))

    def test_describe_change_format(self):
        desc = self.h.describe_change(b"abc", b"abcdefgh")
        # 应当包含"大小"和"哈希"
        self.assertIn("大小", desc)
        self.assertIn("哈希", desc)
        self.assertIn("3B", desc)
        self.assertIn("8B", desc)
        # hash 前 8 字符可见
        # sha256(abc) 起始 = ba7816bf；sha256(abcdefgh) 起始 = 9c56cc51
        self.assertIn("ba7816bf", desc)
        self.assertIn("9c56cc51", desc)

    def test_render_diff_is_meta_only(self):
        out = self.h.render_diff(b"x", b"y")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], "meta")


class TestFileHandlerHelpers(unittest.TestCase):
    """工具方法的边界。"""

    def test_safe_decode_replace(self):
        # 非 UTF-8 字节序列也能返回字符串
        out = FileHandler._safe_decode(b"\xff\xfe abc")
        self.assertIsInstance(out, str)

    def test_size_human(self):
        self.assertEqual(FileHandler._size_human(0), "0B")
        self.assertEqual(FileHandler._size_human(512), "512B")
        # 1024 B → 1.0KB
        out = FileHandler._size_human(1024)
        self.assertIn("KB", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
