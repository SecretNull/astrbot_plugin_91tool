"""结构化查询服务：抓取 → 解析 → 转 VideoItem → 本地筛选 → 存入 ResultStore。"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import replace
from typing import Callable, Protocol

from .config import QueryConfig
from .crawler import VideoRecord
from .models import (
    QueryFilter,
    QueryResult,
    VideoItem,
    extract_viewkey,
    matches_filter,
    parse_duration_text,
)
from .result_store import ResultStore


class ListFetcher(Protocol):
    """查询服务依赖的抓取接口，便于测试注入假实现。"""

    async def fetch(
        self, category: str, keyword: str, page: int, *, first: bool = False
    ) -> list[VideoRecord]:
        ...


def stable_video_id(source_id: str, viewkey: str, page_url: str) -> str:
    """生成稳定 video_id：source_id 优先，viewkey 次之，最后用详情页链接哈希。"""
    if source_id:
        return source_id
    if viewkey:
        return "v_" + viewkey
    digest = hashlib.sha1((page_url or "").encode("utf-8")).hexdigest()[:12]
    return "h_" + digest


class QueryService:
    """查询与筛选的纯业务编排，依赖可注入的 fetcher、store 与时钟。"""

    def __init__(
        self,
        fetcher: ListFetcher,
        config: QueryConfig,
        store: ResultStore,
        now: Callable[[], float] | None = None,
    ):
        self.fetcher = fetcher
        self.config = config
        self.store = store
        self._now = now or time.time

    async def query(
        self,
        *,
        category: str | None = None,
        keyword: str = "",
        page: int = 1,
        page_size: int | None = None,
        min_duration: float | None = None,
        max_duration: float | None = None,
        hd: bool | None = None,
        result_id: str | None = None,
    ) -> QueryResult:
        """执行一次查询，返回带 result_id 的结构化结果。

        result_id 命中时直接返回已有快照，用于 AI 复用同一结果；
        否则抓取指定页、本地筛选、按 page_size 截断、登记新 result_id。
        """
        category = category or self.config.default_category
        keyword = (keyword or "").strip()
        if page < 1:
            raise ValueError("page 不能小于 1")
        if page_size is not None and page_size < 0:
            raise ValueError("page_size 不能为负")

        if result_id:
            cached = self.store.get(result_id)
            if cached is not None:
                return cached

        flt = QueryFilter(min_duration=min_duration, max_duration=max_duration, hd=hd)
        records = await self.fetcher.fetch(category, keyword, page, first=True)

        kept: list[VideoItem] = []
        filtered_out = 0
        for record in records:
            item = self._record_to_item(record, category)
            if matches_filter(item, flt):
                kept.append(item)
            else:
                filtered_out += 1

        truncated = 0
        if page_size is not None and len(kept) > page_size:
            truncated = len(kept) - page_size
            kept = kept[:page_size]
        items = tuple(replace(item, index=index + 1) for index, item in enumerate(kept))

        result = QueryResult(
            result_id=uuid.uuid4().hex,
            category=category,
            keyword=keyword,
            page=page,
            page_size=page_size if page_size is not None else len(items),
            items=items,
            raw_total=len(records),
            filtered_out=filtered_out,
            truncated=truncated,
            created_at=self._now(),
        )
        self.store.put(result)
        return result

    def find_item(self, result_id: str, index: int) -> VideoItem | None:
        """按 (result_id, index) 取条目，index 为 1-based。"""
        result = self.store.get(result_id)
        if result is None or index < 1 or index > len(result.items):
            return None
        return result.items[index - 1]

    def find_video_id(self, result_id: str, index: int) -> str | None:
        """按 (result_id, index) 取稳定 video_id。"""
        item = self.find_item(result_id, index)
        return item.video_id if item else None

    def _record_to_item(self, record: VideoRecord, category: str) -> VideoItem:
        """把抓取层的 VideoRecord 转为面向 AI 的 VideoItem。"""
        viewkey = extract_viewkey(record.link)
        return VideoItem(
            video_id=stable_video_id(record.source_id, viewkey, record.link),
            index=0,
            title=record.title,
            duration_text=record.duration,
            duration_sec=parse_duration_text(record.duration),
            hd=record.hd,
            page_url=record.link,
            cover_url=record.image_url,
            source_id=record.source_id,
            viewkey=viewkey,
            category=category,
        )
