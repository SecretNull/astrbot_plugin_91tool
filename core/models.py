"""Tool-first 架构的领域模型，纯数据，不依赖 astrbot 与网络。"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


def parse_duration_text(text: str) -> float | None:
    """把 "12:34" 或 "1:02:03" 形式的时长文本解析为秒数，无法解析返回 None。"""
    if not text:
        return None
    parts = text.strip().split(":")
    if len(parts) > 3 or not all(part.isdigit() for part in parts):
        return None
    values = [int(part) for part in parts]
    if len(values) == 1:
        return float(values[0])
    if len(values) == 2:
        return float(values[0] * 60 + values[1])
    return float(values[0] * 3600 + values[1] * 60 + values[2])


def extract_viewkey(page_url: str) -> str:
    """从详情页 URL 提取 viewkey 参数，没有则返回空串。"""
    query = urlparse(page_url or "").query
    return parse_qs(query).get("viewkey", [""])[0]


@dataclass(frozen=True)
class VideoItem:
    """列表中单个视频的结构化条目。"""

    video_id: str
    index: int
    title: str
    duration_text: str
    duration_sec: float | None
    hd: bool
    page_url: str
    cover_url: str
    source_id: str
    viewkey: str
    category: str


@dataclass(frozen=True)
class QueryFilter:
    """对查询结果的本地筛选条件。"""

    min_duration: float | None = None
    max_duration: float | None = None
    hd: bool | None = None  # True 仅 HD，False 仅非 HD，None 不限


@dataclass(frozen=True)
class QueryResult:
    """一次查询的结构化快照，由 result_id 稳定引用。"""

    result_id: str
    category: str
    keyword: str
    page: int
    page_size: int
    items: tuple[VideoItem, ...]
    raw_total: int
    filtered_out: int
    truncated: int
    created_at: float


def matches_filter(item: VideoItem, flt: QueryFilter) -> bool:
    """判断条目是否满足筛选条件。

    时长未知且设置了时长门槛时视为不满足，避免把无法判断时长的条目混入结果。
    """
    if flt.hd is True and not item.hd:
        return False
    if flt.hd is False and item.hd:
        return False
    if flt.min_duration is not None and (
        item.duration_sec is None or item.duration_sec < flt.min_duration
    ):
        return False
    if flt.max_duration is not None and (
        item.duration_sec is None or item.duration_sec > flt.max_duration
    ):
        return False
    return True
