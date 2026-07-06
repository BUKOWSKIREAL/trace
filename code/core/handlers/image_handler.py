"""
ImageHandler — 图像类文件的元信息 diff / 摘要
================================================
处理 .png / .jpg / .jpeg / .gif / .bmp / .tiff / .webp 等位图文件。
图像没有"文本"语义，所以：
- extract_text 始终返回 None（与 BinaryHandler 同语义，但更明确）
- describe_change 对比尺寸 / 模式 / 文件大小 / 格式 + 像素差异比例
- render_diff 返回若干 meta 行，并排展示新旧元数据 + SHA-256 前缀 + 像素差异%

# AI 辅助生成（Claude 4.7 协助）
# 人工修正：
#   - Pillow 在损坏字节上抛 UnidentifiedImageError / OSError，必须 try/except
#     兜成 meta 行，否则会冒泡到 UI；
#   - hash 取前 8 字符与 BinaryHandler 风格保持一致，避免一屏被 64 字符占满。
"""
from __future__ import annotations

import functools
import hashlib
import logging
from io import BytesIO
from typing import Optional

from PIL import Image, ImageChops, UnidentifiedImageError

from core.handlers.base import DiffLine, FileHandler, HandlerRegistry

logger = logging.getLogger("trace.handlers.image")


# Pillow 解析失败时可能抛的几类异常——统一兜底
_PIL_ERRORS = (UnidentifiedImageError, OSError, ValueError, SyntaxError)


class _ImageMeta:
    """轻量元信息容器；解析失败时各字段为 None，error 给出失败原因。"""

    __slots__ = ("size", "mode", "format", "byte_len", "sha8", "error")

    def __init__(
        self,
        size: Optional[tuple[int, int]],
        mode: Optional[str],
        format: Optional[str],
        byte_len: int,
        sha8: str,
        error: Optional[str] = None,
    ) -> None:
        self.size = size
        self.mode = mode
        self.format = format
        self.byte_len = byte_len
        self.sha8 = sha8
        self.error = error


class ImageHandler(FileHandler):
    """
    图像 handler，基于 Pillow 提取元信息做对比。
    """

    extensions = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"]

    def extract_text(self, blob: bytes) -> str | None:
        """图像没有文本，永远返回 None。"""
        return None

    def describe_change(self, old_blob: bytes, new_blob: bytes) -> str:
        """
        摘要格式："尺寸 WxH → W2xH2，大小 1.2KB → 1.5KB，格式 PNG → PNG"
        其中任一边解析失败时降级显示 "[文件解析失败：...]"，避免 UI 崩溃。

        # 人工修正（追踪盲区修复）：尺寸/格式都没变、但内容真的改了（如改了图里
        # 某块颜色）时，原版摘要看不出"哪里变了"。补一个像素差异比例——
        # 两图可解码且尺寸相同时，算"约 X% 像素不同"。
        """
        old = self._read_meta(old_blob)
        new = self._read_meta(new_blob)

        # 任一侧损坏——降级返回单行错误摘要
        if old.error is not None or new.error is not None:
            reason = old.error or new.error or "未知错误"
            return f"[文件解析失败：{reason}]"

        old_dims = f"{old.size[0]}x{old.size[1]}" if old.size else "?"
        new_dims = f"{new.size[0]}x{new.size[1]}" if new.size else "?"
        base = (
            f"尺寸 {old_dims} → {new_dims}，"
            f"大小 {self._size_human(old.byte_len)} → {self._size_human(new.byte_len)}，"
            f"格式 {old.format or '?'} → {new.format or '?'}"
        )
        pixel = self._pixel_diff_ratio(old_blob, new_blob)
        if pixel is not None:
            base += f"，像素差异 约 {pixel:.1f}%"
        return base

    def render_diff(self, old_blob: bytes, new_blob: bytes) -> list[DiffLine]:
        """
        返回 meta 行集合，按属性逐项展示 old → new。
        图像内容本身不展开 pixel diff（成本太高、对用户无意义），
        给出关键元数据 + 哈希让用户判断"是否真的变了"。
        """
        old = self._empty_meta() if not old_blob else self._read_meta(old_blob)
        new = self._empty_meta() if not new_blob else self._read_meta(new_blob)

        result: list[DiffLine] = []
        if old.error is not None:
            result.append(("meta", f"[旧文件解析失败：{old.error}]"))
        if new.error is not None:
            result.append(("meta", f"[新文件解析失败：{new.error}]"))

        # 即使解析失败也至少给出字节大小 / hash——保证 UI 始终有可读信息
        old_dims = f"{old.size[0]}x{old.size[1]}" if old.size else "?"
        new_dims = f"{new.size[0]}x{new.size[1]}" if new.size else "?"
        result.append(("meta", f"尺寸：{old_dims} → {new_dims}"))
        result.append(("meta", f"模式：{old.mode or '?'} → {new.mode or '?'}"))
        result.append(("meta", f"格式：{old.format or '?'} → {new.format or '?'}"))
        result.append(("meta", f"大小：{self._size_human(old.byte_len)} → {self._size_human(new.byte_len)}"))
        result.append(("meta", f"SHA-256：{old.sha8} → {new.sha8}"))

        # 像素级内容差异——尺寸/格式没变但图里内容改了时，这是唯一能看出
        # "确实变了 + 变了多少" 的信号。尺寸不同则无法逐像素对齐，给出说明。
        if old.error is None and new.error is None:
            pixel = self._pixel_diff_ratio(old_blob, new_blob)
            if pixel is not None:
                result.append(("meta", f"像素差异：约 {pixel:.1f}% 的像素不同"))
            elif old.size and new.size and old.size != new.size:
                result.append(("meta", "像素差异：尺寸不同，无法逐像素对比"))
        return result

    @staticmethod
    def _pixel_diff_ratio(old_blob: bytes, new_blob: bytes) -> Optional[float]:
        """
        两图都能解码、且尺寸相同时，返回"不同像素占比"的百分比（0~100）。
        无法对比（解码失败 / 尺寸不同）时返回 None。

        # 人工注释：
        #   - 统一 convert("RGBA") 消除模式差异（RGB vs P 调色板等），
        #     否则 ImageChops.difference 会因模式不同抛错；
        #   - 用 difference 的逐通道结果，只要任一通道非零就算这个像素"变了"；
        #   - 不用 diff.getbbox() 做"是否相同"短路——新版 Pillow 的 getbbox 默认
        #     alpha_only=True，对全不透明图只看 alpha 通道，RGB 差异会被漏判成
        #     None（踩过的坑）。一律走直方图统计，0 变化自然得 0.0%。
        """
        try:
            img_a = Image.open(BytesIO(old_blob))
            img_b = Image.open(BytesIO(new_blob))
            try:
                img_a.load()
                img_b.load()
                if img_a.size != img_b.size:
                    return None
                a = img_a.convert("RGBA")
                b = img_b.convert("RGBA")
            finally:
                img_a.close()
                img_b.close()

            total = a.size[0] * a.size[1]
            if total == 0:
                return None
            diff = ImageChops.difference(a, b)
            # 一个像素只要任一通道有差异就算"变了"。把各通道用 lighter（逐像素取最大）
            # 合并成单通道——结果为 0 的像素 = 四通道全无差异。比 convert("L") 更准：
            # 后者用亮度加权，单通道 1 级的小差异可能被四舍五入成 0 漏掉。
            bands = diff.split()
            merged = functools.reduce(ImageChops.lighter, bands)
            hist = merged.histogram()
            unchanged = hist[0]  # 合并后为 0 的像素数 = 完全没变的像素
            changed = total - unchanged
            return 100.0 * changed / total
        except _PIL_ERRORS as e:
            logger.debug("ImageHandler 像素对比失败: %s", e)
            return None

    # ------- 内部工具 -------

    @staticmethod
    def _read_meta(blob: bytes) -> _ImageMeta:
        """
        把字节读成 _ImageMeta；任何异常都在内部捕获，外部拿到 .error。
        # 人工注释：必须 img.load() 触发解码，否则惰性加载会推迟到 size 访问，
        # 行为不稳定；load 完再 close 释放底层文件句柄。
        """
        byte_len = len(blob)
        sha8 = hashlib.sha256(blob).hexdigest()[:8]
        try:
            img = Image.open(BytesIO(blob))
            try:
                img.load()
                size = img.size
                mode = img.mode
                fmt = img.format
            finally:
                img.close()
            return _ImageMeta(size=size, mode=mode, format=fmt, byte_len=byte_len, sha8=sha8)
        except _PIL_ERRORS as e:
            # 不冒泡——日志记一笔，返回带 error 字段的元数据
            logger.debug("ImageHandler 解析失败: %s", e)
            return _ImageMeta(
                size=None, mode=None, format=None, byte_len=byte_len, sha8=sha8,
                error=type(e).__name__,
            )

    @staticmethod
    def _empty_meta() -> _ImageMeta:
        """表示新增/删除文件时不存在的一侧，不把空 blob 当损坏图片。"""
        return _ImageMeta(
            size=None,
            mode=None,
            format="无文件",
            byte_len=0,
            sha8=hashlib.sha256(b"").hexdigest()[:8],
        )


# 模块导入时自动注册
HandlerRegistry.register(ImageHandler())
