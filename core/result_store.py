"""result_id 到 QueryResult 的内存存储，带 TTL 与容量上限。"""
from __future__ import annotations

import time
from typing import Callable

from .models import QueryResult


class ResultStore:
    """查询结果存储：按 result_id 索引，超额淘汰最旧，过期按 TTL 清理。"""

    def __init__(
        self,
        max_results: int = 100,
        ttl_seconds: float = 24 * 3600,
        now: Callable[[], float] | None = None,
    ):
        if max_results <= 0:
            raise ValueError("max_results 必须大于 0")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        self.max_results = max_results
        self.ttl_seconds = ttl_seconds
        self._now = now or time.time
        self._entries: dict[str, QueryResult] = {}

    def put(self, result: QueryResult) -> str:
        """登记一个查询结果，返回其 result_id；超额时淘汰最旧。"""
        self._entries[result.result_id] = result
        while len(self._entries) > self.max_results:
            self._evict_oldest()
        return result.result_id

    def get(self, result_id: str) -> QueryResult | None:
        """按 result_id 取结果；命中但已过期则移除并返回 None。"""
        result = self._entries.get(result_id)
        if result is None:
            return None
        if self._now() - result.created_at > self.ttl_seconds:
            self._entries.pop(result_id, None)
            return None
        return result

    def evict_expired(self) -> int:
        """主动清理所有过期结果，返回清理数量。"""
        cutoff = self._now() - self.ttl_seconds
        expired = [rid for rid, result in self._entries.items() if result.created_at < cutoff]
        for rid in expired:
            self._entries.pop(rid, None)
        return len(expired)

    def __len__(self) -> int:
        return len(self._entries)

    def _evict_oldest(self) -> None:
        """淘汰 created_at 最小的结果。"""
        if not self._entries:
            return
        oldest_id = min(self._entries, key=lambda rid: self._entries[rid].created_at)
        self._entries.pop(oldest_id, None)
