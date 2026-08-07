"""发送服务：解析待发媒体路径并套用发送策略，产出 SendDecision。

发包动作（依赖 astrbot event）在 main 的 tool handler 里执行；本服务只决策。
"""
from __future__ import annotations

import os

from .media_cache import (
    ASSET_GIF_CLEAN,
    ASSET_GIF_MOSAIC,
    ASSET_ORIGINAL,
    ASSET_PREVIEW_CLEAN,
    ASSET_PREVIEW_MOSAIC,
    MediaCache,
)
from .media_sender import SendConfig, SendDecision, decide

# send 用的 asset 名 → media_cache 产物常量
_ASSET_TO_CACHE = {
    "original": ASSET_ORIGINAL,
    "preview_clean": ASSET_PREVIEW_CLEAN,
    "preview_mosaic": ASSET_PREVIEW_MOSAIC,
    "gif_clean": ASSET_GIF_CLEAN,
    "gif_mosaic": ASSET_GIF_MOSAIC,
}


class SendService:
    """按 video_id+asset 或直接 path 解析文件，交 media_sender 决策。"""

    def __init__(self, media_cache: MediaCache, config: SendConfig):
        self.cache = media_cache
        self.config = config

    def plan(
        self,
        *,
        video_id: str | None = None,
        asset: str | None = None,
        path: str | None = None,
        uncensored: bool = False,
        as_file: bool = False,
    ) -> SendDecision:
        """解析路径并决策，返回 SendDecision（action=reject 时含 reason）。"""
        resolved = self._resolve_path(video_id, asset, path)
        if isinstance(resolved, str):
            return SendDecision(
                action="reject",
                kind="image",
                asset=asset or "",
                path="",
                size_bytes=0,
                effective_level=self.config.default_level,
                as_file=as_file,
                reason=resolved,
            )

        file_path, asset_name = resolved
        if not os.path.exists(file_path):
            return SendDecision(
                action="reject",
                kind="image",
                asset=asset_name,
                path=file_path,
                size_bytes=0,
                effective_level=self.config.default_level,
                as_file=as_file,
                reason=f"文件不存在：{file_path}",
            )
        size_bytes = os.path.getsize(file_path)
        return decide(
            asset=asset_name,
            path=file_path,
            size_bytes=size_bytes,
            uncensored=uncensored,
            as_file=as_file,
            config=self.config,
        )

    def _resolve_path(self, video_id, asset, path):
        """返回 (path, asset_name) 或错误字符串。"""
        if path:
            asset_name = asset or "render_image"
            return path, asset_name
        if video_id and asset:
            cache_asset = _ASSET_TO_CACHE.get(asset)
            if cache_asset is None:
                return f"未知产物类型 {asset}，可选：{' '.join(_ASSET_TO_CACHE)}"
            file_path = self.cache.get_asset(video_id, cache_asset)
            if not file_path:
                return f"产物 {asset} 未就绪，请先调用 prepare_video/prepare_preview 生成"
            return file_path, asset
        return "请提供 path，或 video_id + asset 来定位待发媒体"
