"""预览采样服务：基于已下载原片生成 MP4/GIF 预览，写回同一媒体缓存包。

不进详情页：原片由 VideoService 负责，本服务只读本地原片并用 FFmpeg 采样。
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from . import preview, video_source
from .config import PreviewConfig
from .media_cache import (
    ASSET_GIF_CLEAN,
    ASSET_GIF_MOSAIC,
    ASSET_PREVIEW_CLEAN,
    ASSET_PREVIEW_MOSAIC,
    MediaCache,
)
from .query_service import QueryService
from .video_service import VideoService


def asset_for(format_: str, mosaic: bool) -> str:
    """按格式与是否打码映射到缓存产物名。"""
    if format_ == "gif":
        return ASSET_GIF_MOSAIC if mosaic else ASSET_GIF_CLEAN
    return ASSET_PREVIEW_MOSAIC if mosaic else ASSET_PREVIEW_CLEAN


class PreviewService:
    """按 video_id 生成预览：缓存命中直返，否则确保原片就绪后采样。"""

    def __init__(
        self,
        query_service: QueryService,
        video_service: VideoService,
        media_cache: MediaCache,
        config: PreviewConfig,
        video_dir: str,
    ):
        self.query = query_service
        self.video = video_service
        self.cache = media_cache
        self.config = config
        self.video_dir = video_dir

    async def prepare_preview(
        self,
        *,
        video_id=None,
        result_id=None,
        index=None,
        format="mp4",
        mosaic=False,
    ) -> dict:
        """生成预览，返回结构化结果；缓存命中或生成成功返回 ready=True。"""
        fmt = (format or "mp4").strip().lower()
        if fmt not in ("mp4", "gif"):
            return {"ready": False, "error": f"不支持的格式 {format}，可选 mp4 或 gif"}
        mosaic = bool(mosaic)

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
                "error": "该视频缺少可信 source_id，无法准备原片",
            }

        asset_name = asset_for(fmt, mosaic)
        cached = self.cache.get_asset(item.video_id, asset_name)
        if cached:
            return self._build(item, cached, fmt, mosaic, cached=True)

        async with self.cache.lock_for(item.video_id):
            cached = self.cache.get_asset(item.video_id, asset_name)
            if cached:
                return self._build(item, cached, fmt, mosaic, cached=True)
            original = await self.video.ensure_original_path(item)
            if not original:
                return {
                    "ready": False,
                    "video_id": item.video_id,
                    "error": "原视频准备失败，无法生成预览",
                }
            try:
                assets = await self._generate(item.video_id, original, asset_name)
            except (
                preview.PreviewError,
                video_source.VideoSourceError,
                ValueError,
                RuntimeError,
            ) as exc:
                return {
                    "ready": False,
                    "video_id": item.video_id,
                    "error": f"预览生成失败：{exc}",
                }
            self.cache.add_assets(item.video_id, assets)
            return self._build(item, assets[asset_name], fmt, mosaic, cached=False)

    async def _generate(self, video_id, original, asset_name) -> dict:
        """按依赖链生成目标产物，返回 {asset: path}（含中间产物）。

        依赖链：original → preview_clean → (preview_mosaic) → gif。
        mosaic_block<=1 时不打码，mosaic 产物直接复用 clean。
        """
        assets: dict[str, str] = {}
        timeout = self.config.preview_generation_timeout

        clean = self.cache.get_asset(video_id, ASSET_PREVIEW_CLEAN)
        if not clean:
            clean = self._new_path(video_id, "preview_clean", ".mp4")
            duration = await self._probe_duration(original)
            await preview.generate_preview_video(original, clean, duration, timeout)
        assets[ASSET_PREVIEW_CLEAN] = clean

        if asset_name == ASSET_PREVIEW_CLEAN:
            return assets

        block = self.config.mosaic_block
        if asset_name == ASSET_PREVIEW_MOSAIC:
            if block <= 1:
                assets[ASSET_PREVIEW_MOSAIC] = clean
            else:
                mosaic_path = self._new_path(video_id, "preview_mosaic", ".mp4")
                await preview.generate_mosaic_video(clean, mosaic_path, block, timeout)
                assets[ASSET_PREVIEW_MOSAIC] = mosaic_path
            return assets

        if asset_name == ASSET_GIF_CLEAN:
            gif_path = self._new_path(video_id, "gif_clean", ".gif")
            await preview.generate_preview_gif(
                clean,
                gif_path,
                self.config.preview_gif_width,
                self.config.preview_gif_fps,
                timeout,
            )
            assets[ASSET_GIF_CLEAN] = gif_path
            return assets

        # ASSET_GIF_MOSAIC：输入是打码 MP4
        mosaic_source = self.cache.get_asset(video_id, ASSET_PREVIEW_MOSAIC)
        if not mosaic_source:
            if block <= 1:
                mosaic_source = clean
            else:
                mosaic_source = self._new_path(video_id, "preview_mosaic", ".mp4")
                await preview.generate_mosaic_video(clean, mosaic_source, block, timeout)
                assets[ASSET_PREVIEW_MOSAIC] = mosaic_source
        gif_path = self._new_path(video_id, "gif_mosaic", ".gif")
        await preview.generate_preview_gif(
            mosaic_source,
            gif_path,
            self.config.preview_gif_width,
            self.config.preview_gif_fps,
            timeout,
        )
        assets[ASSET_GIF_MOSAIC] = gif_path
        return assets

    async def _probe_duration(self, original: str) -> float:
        """探测原片时长，供采样分段使用。"""
        probe = await video_source.probe_video(Path(original))
        return probe.duration

    def _resolve(self, video_id, result_id, index):
        """按 video_id 或 (result_id, index) 定位 VideoItem。"""
        if video_id:
            return self.query.find_by_video_id(video_id)
        if result_id and index is not None:
            return self.query.find_item(result_id, index)
        return None

    def _new_path(self, video_id, kind, ext) -> str:
        """生成唯一的产物输出路径。"""
        return os.path.join(
            self.video_dir, f"{video_id}_{kind}_{uuid.uuid4().hex[:8]}{ext}"
        )

    def _build(self, item, path, fmt, mosaic, cached) -> dict:
        """组装面向 AI 的结构化结果。"""
        return {
            "ready": True,
            "video_id": item.video_id,
            "format": fmt,
            "mosaic": mosaic,
            "cached": cached,
            "path": path,
            "size_bytes": os.path.getsize(path) if os.path.exists(path) else 0,
        }
