"""发送服务：解析待发媒体、套用发送策略，原片超限时自动压缩补救。

发包动作（依赖 astrbot event）在 main 的 tool handler 里执行；本服务只决策。
"""
from __future__ import annotations

import os
from dataclasses import replace

from .media_cache import (
    ASSET_GIF_CLEAN,
    ASSET_GIF_MOSAIC,
    ASSET_ORIGINAL,
    ASSET_PREVIEW_CLEAN,
    ASSET_PREVIEW_MOSAIC,
    MediaCache,
)
from .media_sender import ACTION_REJECT, SendConfig, SendDecision, decide

_ASSET_TO_CACHE = {
    "original": ASSET_ORIGINAL,
    "preview_clean": ASSET_PREVIEW_CLEAN,
    "preview_mosaic": ASSET_PREVIEW_MOSAIC,
    "gif_clean": ASSET_GIF_CLEAN,
    "gif_mosaic": ASSET_GIF_MOSAIC,
}


class SendService:
    """按 video_id+asset 或 path 解析文件并决策；original 超上限时压缩补救。"""

    def __init__(self, media_cache: MediaCache, config: SendConfig, compress_service=None):
        self.cache = media_cache
        self.config = config
        self.compress = compress_service

    async def resolve_send(
        self,
        *,
        video_id: str | None = None,
        asset: str | None = None,
        path: str | None = None,
        uncensored: bool = False,
        as_file: bool = False,
    ) -> SendDecision:
        """解析路径、决策；original 超过 video 上限时尝试压缩补救。"""
        resolved = self._resolve_path(video_id, asset, path)
        if isinstance(resolved, str):
            return self._reject(resolved, asset or "", "")
        file_path, asset_name = resolved
        if not os.path.exists(file_path):
            return self._reject(f"文件不存在：{file_path}", asset_name, file_path)

        decision = decide(
            asset=asset_name,
            path=file_path,
            size_bytes=os.path.getsize(file_path),
            uncensored=uncensored,
            as_file=as_file,
            config=self.config,
        )
        if (
            decision.action == ACTION_REJECT
            and asset_name == "original"
            and decision.kind == "video"
            and video_id
            and "超过上限" in decision.reason
            and self.compress is not None
        ):
            compressed, comp_reason = await self.compress.compress_original(
                video_id, self.config.video_max_bytes
            )
            if compressed and os.path.exists(compressed):
                remedied = decide(
                    asset=asset_name,
                    path=compressed,
                    size_bytes=os.path.getsize(compressed),
                    uncensored=uncensored,
                    as_file=as_file,
                    config=self.config,
                )
                if remedied.action != ACTION_REJECT:
                    return replace(remedied, compressed=True)
            return replace(
                decision,
                reason=f"原片超上限，压缩未成功：{comp_reason}；建议改发预览(preview_mosaic/gif_mosaic)",
            )
        return decision

    def _reject(self, reason: str, asset: str, path: str) -> SendDecision:
        return SendDecision(
            action=ACTION_REJECT,
            kind="image",
            asset=asset,
            path=path,
            size_bytes=0,
            effective_level=self.config.default_level,
            as_file=False,
            reason=reason,
        )

    def _resolve_path(self, video_id, asset, path):
        """返回 (path, asset_name) 或错误字符串。"""
        if path:
            return path, asset or "render_image"
        if video_id and asset:
            cache_asset = _ASSET_TO_CACHE.get(asset)
            if cache_asset is None:
                return f"未知产物类型 {asset}，可选：{' '.join(_ASSET_TO_CACHE)}"
            file_path = self.cache.get_asset(video_id, cache_asset)
            if not file_path:
                return f"产物 {asset} 未就绪，请先调用 prepare_video/prepare_preview 生成"
            return file_path, asset
        return "请提供 path，或 video_id + asset 来定位待发媒体"
