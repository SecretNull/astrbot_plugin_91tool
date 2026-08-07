"""压缩服务：把原片压到发送上限内，缓存压缩产物。返回 (path|None, reason)。"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from . import compress, video_source
from .media_cache import ASSET_ORIGINAL, ASSET_ORIGINAL_COMPRESSED, MediaCache

# 最低可编码总码率(视频 100kbps + 音频 48kbps)；低于此说明原片过长，压不到目标内
_MIN_TOTAL_BITRATE = 148_000


class CompressService:
    """按 video_id 压缩原片到目标大小，产物写回同一 media_cache bundle。"""

    def __init__(self, media_cache: MediaCache, video_dir: str, timeout: float = 300.0):
        self.cache = media_cache
        self.video_dir = video_dir
        self.timeout = timeout

    async def compress_original(
        self, video_id: str, target_bytes: int
    ) -> tuple[str | None, str]:
        """把原片压到 target_bytes 内；返回 (路径或 None, 原因说明)。"""
        cached = self.cache.get_asset(video_id, ASSET_ORIGINAL_COMPRESSED)
        if cached and os.path.exists(cached) and os.path.getsize(cached) <= target_bytes:
            return cached, "命中已有压缩版"

        original = self.cache.get_asset(video_id, ASSET_ORIGINAL)
        if not original or not os.path.exists(original):
            return None, "原片未就绪，请先 prepare_video"

        try:
            probe = await video_source.probe_video(Path(original))
        except (video_source.VideoSourceError, OSError) as exc:
            return None, f"探测原片失败：{exc}"

        if probe.duration > 0 and target_bytes * 8 / probe.duration < _MIN_TOTAL_BITRATE:
            return None, (
                f"原片约 {probe.duration:.0f} 秒过长，压到 {target_bytes} 字节内"
                "会低于可编码码率（建议改发预览 preview_mosaic）"
            )

        output_path = os.path.join(
            self.video_dir, f"{video_id}_compressed_{uuid.uuid4().hex[:8]}.mp4"
        )
        try:
            await asyncio.to_thread(
                compress.compress_video,
                original, output_path, probe.duration, target_bytes, self.timeout,
            )
        except (compress.CompressError, OSError) as exc:
            return None, f"压缩失败：{exc}"

        if not os.path.exists(output_path):
            return None, "压缩未产出文件"
        actual = os.path.getsize(output_path)
        if actual > target_bytes:
            return None, f"压缩后 {actual} 字节仍超过上限 {target_bytes}"

        self.cache.add_assets(video_id, {ASSET_ORIGINAL_COMPRESSED: output_path})
        return output_path, "已压缩"
