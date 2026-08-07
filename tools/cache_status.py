"""91tool_cache_status：汇总各缓存层概况，纯本地查询。"""
from __future__ import annotations

from ..core.media_cache import MediaCache
from ..core.result_store import ResultStore
from ..core.video_registry import VideoRegistry


def run_cache_status(
    store: ResultStore, registry: VideoRegistry, media_cache: MediaCache
) -> dict:
    """汇总查询结果、视频索引、媒体缓存的条目数与占用。"""
    media = media_cache.status()
    return {
        "results": len(store),
        "video_ids": len(registry),
        "media_bundles": media["bundles"],
        "total_size_bytes": media["total_size_bytes"],
    }
