"""91tool_prepare_preview：预览采样，返回本地路径与信息（不发送）。"""
from __future__ import annotations

from typing import Any

from ..core.preview_service import PreviewService


def parse_params(raw: dict[str, Any]) -> dict[str, Any]:
    """把 tool 入参规整为 PreviewService.prepare_preview 的关键字参数。"""
    def opt_int(key: str) -> int | None:
        value = raw.get(key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} 必须是整数") from exc

    return {
        "video_id": raw.get("video_id") or None,
        "result_id": raw.get("result_id") or None,
        "index": opt_int("index"),
        "format": raw.get("format") or "mp4",
        "mosaic": _parse_mosaic(raw.get("mosaic")),
    }


def _parse_mosaic(value) -> bool:
    """mosaic 默认不打码；true/1/yes/mosaic/打码 视为打码。"""
    if value in (None, ""):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "mosaic", "打码")


async def run_prepare_preview(
    service: PreviewService, raw_params: dict[str, Any]
) -> dict[str, Any]:
    """解析参数并执行预览采样；返回结构化结果，不发送媒体。"""
    params = parse_params(raw_params)
    return await service.prepare_preview(**params)
