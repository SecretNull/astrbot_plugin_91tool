"""长图合成：把 VideoItem 列表拼成单列长图（封面+序号+标题/时长/链接，自动换行）。

纯模块，不依赖 astrbot。支持任意条目子集，不再绑死整页。
"""
import asyncio
import io
import os
import uuid

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from .models import VideoItem

# 插件自带精简中文字体（子集化自 Noto Sans CJK），位于项目根 fonts/
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_BUNDLED_FONT = os.path.normpath(os.path.join(_PKG_DIR, "..", "fonts", "noto-sc.ttf"))
# 系统字体候选（备选）
_FONT_REG_CANDS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
]

# 排版常量
PAD = 16
GAP = 10
LH_TITLE = 30
LH_META = 24
FIELD_GAP = 6
TEXT_TOP = 8
TEXT_BOTTOM = 8
BG = (244, 244, 246)
CARD_BG = (255, 255, 255)
NUM_BG = (214, 36, 36)
NUM_FG = (255, 255, 255)
TITLE_C = (28, 28, 32)
DUR_C = (12, 120, 200)
LINK_C = (96, 96, 100)


def _load_font(config, size):
    """加载字体：插件自带 > config.font_regular > 系统候选 > PIL 默认。"""
    cands = [_BUNDLED_FONT, getattr(config, "font_regular", "") or ""] + _FONT_REG_CANDS
    for path in cands:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(text, font, max_w, draw):
    """按宽度逐字符测量换行，返回行列表。"""
    if not text:
        return []
    text = " ".join(str(text).splitlines())
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _process_image(im, target_w, max_h, mosaic_block):
    """等比缩放到 target_w 宽（超高再按 max_h 缩）；mosaic_block<=1 时用原图，否则打码。"""
    ratio = target_w / im.width
    nw, nh = target_w, int(im.height * ratio)
    if nh > max_h:
        ratio = max_h / im.height
        nw, nh = int(im.width * ratio), max_h
    im = im.resize((nw, nh), Image.LANCZOS)
    block = int(mosaic_block)
    if block <= 1:
        return im
    small = im.resize((max(1, nw // block), max(1, nh // block)), Image.BOX)
    return small.resize((nw, nh), Image.NEAREST)


def _compose(items, images, config, out_path, mosaic_block):
    """同步 PIL 合成长图。items 与 images 同序，images[i] 为 None 表示下载失败。"""
    width = int(config.longimage_width)
    max_h = int(config.cover_max_height)
    img_w = width - 2 * PAD
    max_text_w = width - 2 * PAD

    font_num = _load_font(config, 30)
    font_title = _load_font(config, 21)
    font_meta = _load_font(config, 17)

    meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    proc = [_process_image(im, img_w, max_h, mosaic_block) if im else None for im in images]

    # 第一遍：算每条文字行与高度
    rows = []
    for idx, it in enumerate(items):
        ih = proc[idx].height if proc[idx] else max_h
        meta = it.duration_text + ("   [HD]" if it.hd else "")
        fields = []
        if meta.strip():
            fields.append((_wrap(meta, font_meta, max_text_w, meas), LH_META, DUR_C, font_meta))
        fields.append((_wrap(it.title, font_title, max_text_w, meas), LH_TITLE, TITLE_C, font_title))
        fields.append((_wrap(it.page_url, font_meta, max_text_w, meas), LH_META, LINK_C, font_meta))
        text_h = TEXT_TOP + sum(len(lines) * lh for lines, lh, *_ in fields) \
            + FIELD_GAP * max(0, len(fields) - 1) + TEXT_BOTTOM
        rows.append({"ih": ih, "fields": fields, "rh": ih + text_h})

    total_h = sum(r["rh"] for r in rows) + GAP * len(rows) + 2 * PAD
    canvas = Image.new("RGB", (width, total_h), BG)
    draw = ImageDraw.Draw(canvas)

    # 第二遍：画
    y = PAD
    for idx, it in enumerate(items):
        r = rows[idx]
        draw.rectangle([PAD - 6, y - 3, width - PAD + 6, y + r["rh"] + 3], fill=CARD_BG)
        x = PAD
        im = proc[idx]
        if im:
            canvas.paste(im, (x, y))
        else:
            draw.text((x, y), "[封面下载失败]", fill=(200, 0, 0), font=font_meta)
        # 序号贴封面左上角红底白字，用条目在结果中的 index
        num = str(it.index)
        nb = draw.textbbox((0, 0), num, font=font_num)
        nw_ = nb[2] - nb[0] + 18
        nh_ = nb[3] - nb[1] + 12
        draw.rectangle([x, y, x + nw_, y + nh_], fill=NUM_BG)
        draw.text((x + 9, y - 1), num, fill=NUM_FG, font=font_num)
        ty = y + r["ih"] + TEXT_TOP
        for lines, lh, color, font in r["fields"]:
            for ln in lines:
                draw.text((x, ty), ln, fill=color, font=font)
                ty += lh
            ty += FIELD_GAP
        y += r["rh"] + GAP

    canvas.save(out_path, "JPEG", quality=85)


async def download_covers(http_client, items, referer, proxy=None):
    """并发下载封面，返回与 items 同序的 Image 列表（失败位为 None）。"""
    async def dl(it: VideoItem):
        try:
            async with http_client.get(
                it.cover_url, headers={"Referer": referer}, proxy=proxy
            ) as r:
                if r.status != 200:
                    return None
                data = await r.read()
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            return None

    return list(await asyncio.gather(*[dl(it) for it in items]))


async def build_longimage_from_items(
    items, http_client, config, out_path, mosaic_block, proxy=None
):
    """下载封面并合成长图，返回 jpg 路径。"""
    referer = "https://91porn.com/"
    images = await download_covers(http_client, items, referer, proxy)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    await asyncio.to_thread(_compose, items, images, config, out_path, mosaic_block)
    return out_path
