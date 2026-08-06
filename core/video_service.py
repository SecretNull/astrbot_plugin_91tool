"""视频准备服务：可信校验下载原视频并写入共享媒体缓存。

这是 core 层里唯一会触发详情页访问的服务（通过 video_source 模块）。
"""
from __future__ import annotations

import os
import uuid

from . import video_source
from .config import VideoConfig
from .media_cache import ASSET_ORIGINAL, MediaCache
from .query_service import QueryService


class VideoService:
    """按 video_id 准备原视频：缓存命中直返，否则校验下载后写缓存。"""

    def __init__(
        self,
        http_client,
        media_cache: MediaCache,
        query_service: QueryService,
        config: VideoConfig,
        video_dir: str,
    ):
        self.http_client = http_client
        self.cache = media_cache
        self.query = query_service
        self.config = config
        self.video_dir = video_dir

    async def prepare(self, *, video_id=None, result_id=None, index=None) -> dict:
        """准备原视频，返回结构化结果。

        缓存命中或下载成功都返回 ready=True；找不到视频或缺少可信 source_id
        时返回 ready=False 并给出 error。下载路径走 ID 匹配 + 时长双校验。
        """
        item = self._resolve(video_id, result_id, index)
        if item is None:
            return {
                "ready": False,
                "error": "找不到对应视频，请确认 video_id 或 (result_id, index)",
            }
        if not item.source_id or not item.source_id.isdigit():
            return {
                "ready": False,
                "video_id": item.video_id,
                "error": "该视频缺少可信 source_id，无法校验下载",
            }

        cached = self.cache.get_asset(item.video_id, ASSET_ORIGINAL)
        if cached:
            return self._build(item, cached, cached=True, refreshes=0)

        async with self.cache.lock_for(item.video_id):
            cached = self.cache.get_asset(item.video_id, ASSET_ORIGINAL)
            if cached:
                return self._build(item, cached, cached=True, refreshes=0)
            output_path = os.path.join(
                self.video_dir, f"{item.video_id}_{uuid.uuid4().hex[:8]}.mp4"
            )
            delay = self.config.video_source_refresh_delay
            source = await video_source.fetch_matching_video_source(
                self.http_client,
                item.page_url,
                item.source_id,
                max_refreshes=self.config.video_source_max_refreshes,
                proxy=self.config.proxy,
                retry_delay_min=delay,
                retry_delay_max=delay,
            )
            probe = await video_source.download_video_source(
                self.http_client,
                source,
                item.page_url,
                output_path,
                timeout=self.config.video_download_timeout,
                proxy=self.config.proxy,
            )
            self.cache.replace(item.video_id, {ASSET_ORIGINAL: output_path})
            return self._build(
                item, output_path, cached=False, refreshes=source.refreshes, probe=probe
            )

    def _resolve(self, video_id, result_id, index):
        """按 video_id 或 (result_id, index) 定位 VideoItem。"""
        if video_id:
            return self.query.find_by_video_id(video_id)
        if result_id and index is not None:
            return self.query.find_item(result_id, index)
        return None

    def _build(self, item, path, cached, refreshes, probe=None) -> dict:
        """组装面向 AI 的结构化结果。"""
        return {
            "ready": True,
            "video_id": item.video_id,
            "cached": cached,
            "verified": True,
            "refreshes": refreshes,
            "path": path,
            "size_bytes": os.path.getsize(path) if os.path.exists(path) else 0,
            "duration_sec": probe.duration if probe else None,
            "width": probe.width if probe else None,
            "height": probe.height if probe else None,
        }
