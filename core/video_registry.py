"""video_id 到 VideoItem 的全局注册表，支持跨 result 按 video_id 查找。"""
from __future__ import annotations

import time
from typing import Callable

from .models import VideoItem


class VideoRegistry:
    """按稳定 video_id 索引 VideoItem，带 TTL 与容量上限。

    查询服务把每次返回的条目登记进来，后续即可仅凭 video_id 取回，
    不必依赖某个具体的 result_id。
    """

    def __init__(
        self,
        max_entries: int = 500,
        ttl_seconds: float = 24 * 3600,
        now: Callable[[], float] | None = None,
    ):
        if max_entries <= 0:
            raise ValueError("max_entries 必须大于 0")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._now = now or time.time
        self._items: dict[str, VideoItem] = {}
        self._timestamps: dict[str, float] = {}

    def put(self, item: VideoItem) -> None:
        """登记或更新一个条目，刷新其时间戳；超额时淘汰最旧。"""
        self._items[item.video_id] = item
        self._timestamps[item.video_id] = self._now()
        while len(self._items) > self.max_entries:
            self._evict_oldest()

    def get(self, video_id: str) -> VideoItem | None:
        """按 video_id 取条目；命中但已过期则移除并返回 None。"""
        if video_id not in self._items:
            return None
        if self._now() - self._timestamps[video_id] > self.ttl_seconds:
            self._discard(video_id)
            return None
        return self._items[video_id]

    def evict_expired(self) -> int:
        """主动清理过期条目，返回清理数量。"""
        cutoff = self._now() - self.ttl_seconds
        expired = [vid for vid, ts in self._timestamps.items() if ts < cutoff]
        for vid in expired:
            self._discard(vid)
        return len(expired)

    def __len__(self) -> int:
        return len(self._items)

    def _discard(self, video_id: str) -> None:
        self._items.pop(video_id, None)
        self._timestamps.pop(video_id, None)

    def _evict_oldest(self) -> None:
        if not self._timestamps:
            return
        oldest = min(self._timestamps, key=lambda vid: self._timestamps[vid])
        self._discard(oldest)
