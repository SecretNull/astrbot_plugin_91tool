"""压缩服务：把视频压到发送上限内。compress_file 压任意路径不缓存，compress_original 走缓存。"""
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
    """压缩视频到目标大小。compress_file 压任意文件不缓存，compress_original 走 media_cache。"""

    def __init__(self, media_cache: MediaCache, video_dir: str, timeout: float = 300.0):
        self.cache = media_cache
        self.video_dir = video_dir
        self.timeout = timeout

    async def compress_file(
        self, src_path: str, target_bytes: int
    ) -> tuple[str | None, str]:
        """压缩任意视频文件到 target_bytes 内；返回 (path|None, reason)，不缓存。"""
        if not os.path.exists(src_path):
            return None, "源文件不存在"
        try:
            probe = await video_source.probe_video(Path(src_path))
        except (video_source.VideoSourceError, OSError) as exc:
            return None, f"探测原片失败：{exc}"

        if probe.duration > 0 and target_bytes * 8 / probe.duration < _MIN_TOTAL_BITRATE:
            return None, (
                f"原片约 {probe.duration:.0f} 秒过长，压到 {target_bytes} 字节内"
                "会低于可编码码率（建议改发预览）"
            )

        output_path = os.path.join(
            self.video_dir, f"compress_{uuid.uuid4().hex[:8]}.mp4"
        )
        try:
            await asyncio.to_thread(
                compress.compress_video,
                src_path, output_path, probe.duration, target_bytes, self.timeout,
            )
        except (compress.CompressError, OSError) as exc:
            return None, f"压缩失败：{exc}"

        if not os.path.exists(output_path):
            return None, "压缩未产出文件"
        actual = os.path.getsize(output_path)
        if actual > target_bytes:
            return None, f"压缩后 {actual} 字节仍超过上限 {target_bytes}"
        return output_path, "已压缩"

    async def compress_original(
        self, video_id: str, target_bytes: int
    ) -> tuple[str | None, str]:
        """按 video_id 取原片压缩并把产物缓存进 bundle；返回 (path|None, reason)。"""
        cached = self.cache.get_asset(video_id, ASSET_ORIGINAL_COMPRESSED)
        if cached and os.path.exists(cached) and os.path.getsize(cached) <= target_bytes:
            return cached, "命中已有压缩版"

        original = self.cache.get_asset(video_id, ASSET_ORIGINAL)
        if not original or not os.path.exists(original):
            return None, "原片未就绪，请先 prepare_video"

        output, reason = await self.compress_file(original, target_bytes)
        if output is None:
            return None, reason
        self.cache.add_assets(video_id, {ASSET_ORIGINAL_COMPRESSED: output})
        return output, "已压缩(已缓存)"
