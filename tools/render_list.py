"""91tool_render_list：把结果或选定条目渲染成长图，返回路径（不发送）。"""
from __future__ import annotations

from typing import Any

from ..core.render_service import RenderService


def parse_params(raw: dict[str, Any]) -> dict[str, Any]:
    """把 tool 入参规整为 RenderService.render 的关键字参数。"""
    def opt_int_list(key: str) -> list[int] | None:
        value = raw.get(key)
        if value in (None, ""):
            return None
        if isinstance(value, (list, tuple)):
            return [int(v) for v in value]
        return [int(part.strip()) for part in str(value).split(",") if part.strip()]

    def opt_str_list(key: str) -> list[str] | None:
        value = raw.get(key)
        if value in (None, ""):
            return None
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if v]
        return [part.strip() for part in str(value).split(",") if part.strip()]

    return {
        "result_id": raw.get("result_id") or None,
        "indices": opt_int_list("indices"),
        "video_ids": opt_str_list("video_ids"),
        "mosaic": _parse_mosaic(raw.get("mosaic")),
    }


def _parse_mosaic(value) -> bool | None:
    """mosaic 留空用默认(打码)；true 打码；false/无码/无和谐 不打码。"""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "mosaic", "打码"):
        return True
    if text in ("false", "0", "no", "无码", "无和谐"):
        return False
    return None


async def run_render_list(
    service: RenderService, raw_params: dict[str, Any]
) -> dict[str, Any]:
    """解析参数并执行渲染；返回结构化结果，不发送媒体。"""
    params = parse_params(raw_params)
    return await service.render(**params)
