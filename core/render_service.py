"""长图渲染服务：把 VideoItem 子集合成单列长图。

不进详情页：封面图地址来自列表 VideoItem.cover_url，只下载封面。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import replace

from . import longimage
from .config import RenderConfig
from .query_service import QueryService


class RenderService:
    """按 result_id(+indices) 或 video_ids 取条目子集，渲染成单列长图。"""

    def __init__(
        self,
        query_service: QueryService,
        http_client,
        config: RenderConfig,
        video_dir: str,
    ):
        self.query = query_service
        self.http_client = http_client
        self.config = config
        self.video_dir = video_dir

    async def render(
        self,
        *,
        result_id=None,
        indices=None,
        video_ids=None,
        mosaic=None,
    ) -> dict:
        """渲染长图，返回结构化结果（含本地路径，不发送）。

        mosaic=None 或 True 时打码（用 config.mosaic_block）；mosaic=False 时无和谐。
        """
        items = self._resolve_items(result_id, indices, video_ids)
        if not items:
            return {
                "ready": False,
                "error": "没有可渲染的条目，请确认 result_id/indices 或 video_ids",
            }
        if video_ids:
            # 跨 result 合并/选定子集：序号重排为连续 1..N，每张长图自洽
            items = [replace(it, index=i + 1) for i, it in enumerate(items)]

        block = 1 if mosaic is False else self.config.mosaic_block
        out_path = os.path.join(self.video_dir, f"render_{uuid.uuid4().hex[:8]}.jpg")
        try:
            await longimage.build_longimage_from_items(
                items, self.http_client, self.config, out_path, block, self.config.proxy
            )
        except (ValueError, RuntimeError, OSError) as exc:
            return {"ready": False, "error": f"长图渲染失败：{exc}"}

        return {
            "ready": True,
            "image_path": out_path,
            "width": self.config.longimage_width,
            "item_count": len(items),
            "mosaic_applied": block > 1,
            "video_ids": [it.video_id for it in items],
        }

    def _resolve_items(self, result_id, indices, video_ids):
        """按 video_ids 或 result_id(+indices) 解析出 VideoItem 子集。"""
        if video_ids:
            items = []
            for vid in video_ids:
                item = self.query.find_by_video_id(vid)
                if item is not None:
                    items.append(item)
            return items
        if result_id:
            result = self.query.store.get(result_id)
            if result is None:
                return []
            if indices:
                picked = []
                for position in indices:
                    if 1 <= position <= len(result.items):
                        picked.append(result.items[position - 1])
                return picked
            return list(result.items)
        return []
