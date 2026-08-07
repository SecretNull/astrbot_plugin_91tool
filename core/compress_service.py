"""压缩服务：把原片压到发送上限内，缓存压缩产物避免重复压缩。"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from . import compress, video_source
from .media_cache import ASSET_ORIGINAL, ASSET_ORIGINAL_COMPRESSED, MediaCache


class CompressService:
    """按 video_id 压缩原片到目标大小，产物写回同一 media_cache bundle。"""

    def __init__(self, media_cache: MediaCache, video_dir: str, timeout: float = 300.0):
        self.cache = media_cache
        self.video_dir = video_dir
        self.timeout = timeout

    async def compress_original(self, video_id: str, target_bytes: int) -> str | None:
        """把原片压到 target_bytes 内，返回压缩版路径；不可行时返回 None。

        缓存命中(且未超 target)直接复用；否则探测时长后 2-pass 压缩并登记。
        """
        cached = self.cache.get_asset(video_id, ASSET_ORIGINAL_COMPRESSED)
        if cached and os.path.exists(cached) and os.path.getsize(cached) <= target_bytes:
            return cached

        original = self.cache.get_asset(video_id, ASSET_ORIGINAL)
        if not original or not os.path.exists(original):
            return None
        try:
            probe = await video_source.probe_video(Path(original))
            output_path = os.path.join(
                self.video_dir, f"{video_id}_compressed_{uuid.uuid4().hex[:8]}.mp4"
            )
            await asyncio.to_thread(
                compress.compress_video,
                original, output_path, probe.duration, target_bytes, self.timeout,
            )
        except (compress.CompressError, video_source.VideoSourceError, OSError, ValueError):
            return None
        if not os.path.exists(output_path) or os.path.getsize(output_path) > target_bytes:
            return None
        self.cache.add_assets(video_id, {ASSET_ORIGINAL_COMPRESSED: output_path})
        return output_path
