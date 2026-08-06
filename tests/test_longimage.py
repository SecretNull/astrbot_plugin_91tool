"""longimage 纯函数测试：换行、空文本、字体回退。"""
from PIL import Image, ImageDraw, ImageFont

from astrbot_plugin_91tool.core import longimage
from astrbot_plugin_91tool.core.config import RenderConfig


def test_wrap_returns_lines():
    canvas = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    lines = longimage._wrap("hello world foo bar", font, 30, draw)
    assert isinstance(lines, list)
    assert len(lines) >= 1
    assert "".join(lines) == "hello world foo bar"


def test_wrap_empty():
    canvas = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    assert longimage._wrap("", font, 30, draw) == []


def test_load_font_returns_font():
    font = longimage._load_font(RenderConfig(), 20)
    assert font is not None
