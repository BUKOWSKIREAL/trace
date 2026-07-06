"""
ImageHandler 单元测试
========================
覆盖 ImageHandler 的核心契约：
- extract_text 始终 None
- describe_change 摘要格式 / 区分变化与无变化
- render_diff 元信息 meta 行
- 损坏 blob 不崩
- HandlerRegistry 路由正确

# 人工编写
"""
import sys
import unittest
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.handlers import HandlerRegistry  # noqa: E402
from core.handlers.image_handler import ImageHandler  # noqa: E402


def _make_image_blob(
    size: tuple[int, int] = (10, 20),
    color: str = "red",
    mode: str = "RGB",
    fmt: str = "PNG",
) -> bytes:
    """构造一张真实的图像字节流——不依赖 fixture 文件。"""
    img = Image.new(mode, size, color=color)
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class TestExtractText(unittest.TestCase):
    def setUp(self):
        self.h = ImageHandler()

    def test_extract_text_returns_none_on_valid_png(self):
        blob = _make_image_blob()
        self.assertIsNone(self.h.extract_text(blob))

    def test_extract_text_returns_none_on_corrupt(self):
        # 哪怕字节不是合法图像，也不能抛异常——返回 None
        self.assertIsNone(self.h.extract_text(b"definitely not an image"))


class TestDescribeChange(unittest.TestCase):
    def setUp(self):
        self.h = ImageHandler()

    def test_describe_change_dimensions_differ(self):
        old = _make_image_blob(size=(10, 20))
        new = _make_image_blob(size=(40, 30))
        desc = self.h.describe_change(old, new)
        self.assertIn("10x20", desc)
        self.assertIn("40x30", desc)
        self.assertIn("尺寸", desc)
        self.assertIn("大小", desc)
        self.assertIn("格式", desc)
        self.assertIn("PNG", desc)

    def test_describe_change_same_dims_diff_color(self):
        # 同尺寸不同颜色——字节不同但尺寸/格式相同
        old = _make_image_blob(size=(8, 8), color="red")
        new = _make_image_blob(size=(8, 8), color="blue")
        desc = self.h.describe_change(old, new)
        # 摘要里两个尺寸应当一致
        self.assertIn("8x8", desc)
        # PNG → PNG
        self.assertIn("PNG", desc)

    def test_describe_change_format_change(self):
        old = _make_image_blob(size=(20, 20), fmt="PNG")
        new = _make_image_blob(size=(20, 20), fmt="JPEG")
        desc = self.h.describe_change(old, new)
        self.assertIn("PNG", desc)
        self.assertIn("JPEG", desc)

    def test_describe_change_corrupt_blob_returns_meta(self):
        good = _make_image_blob()
        bad = b"not an image at all"
        desc = self.h.describe_change(good, bad)
        # 不应抛异常，必须返回带"文件解析失败"的字符串
        self.assertIn("文件解析失败", desc)


class TestRenderDiff(unittest.TestCase):
    def setUp(self):
        self.h = ImageHandler()

    def test_render_diff_returns_meta_lines(self):
        old = _make_image_blob(size=(10, 20))
        new = _make_image_blob(size=(40, 30))
        out = self.h.render_diff(old, new)
        self.assertGreater(len(out), 0)
        # 全部应当是 meta（图像不做内容 diff）
        for tag, _ in out:
            self.assertEqual(tag, "meta")

    def test_render_diff_contains_key_attrs(self):
        old = _make_image_blob(size=(10, 20))
        new = _make_image_blob(size=(40, 30))
        out = self.h.render_diff(old, new)
        joined = "\n".join(line for _, line in out)
        self.assertIn("尺寸", joined)
        self.assertIn("10x20", joined)
        self.assertIn("40x30", joined)
        self.assertIn("模式", joined)
        self.assertIn("格式", joined)
        self.assertIn("大小", joined)
        self.assertIn("SHA-256", joined)

    def test_render_diff_hash_prefix_visible(self):
        import hashlib
        old = _make_image_blob(size=(5, 5), color="red")
        new = _make_image_blob(size=(5, 5), color="green")
        old_h = hashlib.sha256(old).hexdigest()[:8]
        new_h = hashlib.sha256(new).hexdigest()[:8]
        out = self.h.render_diff(old, new)
        joined = "\n".join(line for _, line in out)
        self.assertIn(old_h, joined)
        self.assertIn(new_h, joined)


class TestRegistry(unittest.TestCase):
    def test_png_routes_to_image_handler(self):
        h = HandlerRegistry.for_path(Path("photo.png"))
        self.assertIsInstance(h, ImageHandler)

    def test_jpg_and_jpeg_route(self):
        for name in ("a.jpg", "b.jpeg", "C.JPG"):
            with self.subTest(name=name):
                h = HandlerRegistry.for_path(Path(name))
                self.assertIsInstance(h, ImageHandler)

    def test_all_registered_extensions(self):
        # 每个声明的扩展名都应路由到 ImageHandler
        for ext in ImageHandler.extensions:
            with self.subTest(ext=ext):
                h = HandlerRegistry.for_path(Path(f"x{ext}"))
                self.assertIsInstance(h, ImageHandler)


class TestRobustness(unittest.TestCase):
    def setUp(self):
        self.h = ImageHandler()

    def test_both_corrupt_blobs_do_not_crash(self):
        # 双侧损坏也必须返回字符串，不能抛
        desc = self.h.describe_change(b"\x00\x01\x02", b"\x99\x98\x97")
        self.assertIsInstance(desc, str)
        self.assertIn("文件解析失败", desc)

    def test_render_diff_corrupt_blob_has_failure_meta(self):
        out = self.h.render_diff(b"junk", _make_image_blob())
        self.assertGreater(len(out), 0)
        joined = "\n".join(line for _, line in out)
        # 至少一行应反映旧文件解析失败
        self.assertIn("旧文件解析失败", joined)
        # 即便如此，依然给出 SHA-256（fallback 信息）
        self.assertIn("SHA-256", joined)


class TestPixelDiff(unittest.TestCase):
    """追踪盲区修复：尺寸/格式没变但内容变了，要能看出像素差异。"""

    def setUp(self):
        self.h = ImageHandler()

    @staticmethod
    def _half_split(size, left, right) -> bytes:
        """左半边 left 色、右半边 right 色——便于精确控制差异比例。"""
        w, hgt = size
        img = Image.new("RGB", size, color=left)
        for x in range(w // 2, w):
            for y in range(hgt):
                img.putpixel((x, y), Image.new("RGB", (1, 1), right).getpixel((0, 0)))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_identical_images_zero_percent(self):
        a = _make_image_blob(size=(20, 20), color="blue")
        b = _make_image_blob(size=(20, 20), color="blue")
        # 完全相同 → 像素差异 0%；但字节相同时 DiffView 根本不会调 handler，
        # 这里直接验证 describe 不会谎报内容变化
        desc = self.h.describe_change(a, b)
        self.assertIn("像素差异", desc)
        self.assertIn("0.0%", desc)

    def test_content_change_same_size_visible(self):
        # 同尺寸、纯色 → 全红改全绿：100% 像素不同
        a = _make_image_blob(size=(20, 20), color="red")
        b = _make_image_blob(size=(20, 20), color="green")
        desc = self.h.describe_change(a, b)
        self.assertIn("像素差异", desc)
        contents = " ".join(c for _, c in self.h.render_diff(a, b))
        self.assertIn("像素差异", contents)

    def test_partial_change_ratio_reasonable(self):
        # 左半边相同(red)、右半边 red→blue：约 50% 像素不同
        a = self._half_split((20, 20), "red", "red")
        b = self._half_split((20, 20), "red", "blue")
        ratio = self.h._pixel_diff_ratio(a, b)
        self.assertIsNotNone(ratio)
        self.assertTrue(40 <= ratio <= 60, f"期望约 50%，实际 {ratio}")

    def test_different_size_no_pixel_ratio(self):
        a = _make_image_blob(size=(20, 20), color="red")
        b = _make_image_blob(size=(40, 40), color="red")
        self.assertIsNone(self.h._pixel_diff_ratio(a, b))
        contents = " ".join(c for _, c in self.h.render_diff(a, b))
        self.assertIn("尺寸不同", contents)

    def test_corrupt_blob_no_crash(self):
        self.assertIsNone(self.h._pixel_diff_ratio(b"garbage", b"more garbage"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
