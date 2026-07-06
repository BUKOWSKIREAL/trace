"""
handlers 包入口
====================
import 这个包就触发所有 handler 注册到 HandlerRegistry。
对外 API：from core.handlers import HandlerRegistry

# 人工编写
"""
from core.handlers.base import FileHandler, HandlerRegistry  # noqa: F401
from core.handlers import binary_handler  # noqa: F401  注册 fallback
from core.handlers import text_handler  # noqa: F401    注册 text
from core.handlers import docx_handler  # noqa: F401    注册 docx
from core.handlers import pptx_handler  # noqa: F401    注册 pptx
from core.handlers import xlsx_handler  # noqa: F401    注册 xlsx
from core.handlers import pdf_handler  # noqa: F401     注册 pdf
from core.handlers import image_handler  # noqa: F401   注册 image
