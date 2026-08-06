"""91tool_video_info：纯本地文字详情，不进详情页、不下载。"""
from __future__ import annotations

from typing import Any

from ..core.query_service import QueryService


def parse_params(raw: dict[str, Any]) -> dict[str, Any]:
    """把 tool 入参规整为定位关键字：优先 video_id，其次 (result_id, index)。"""
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
    }


def build_output(item) -> dict[str, Any]:
    """把 VideoItem 的完整字段转为面向 AI 的输出。"""
    return {
        "found": True,
        "video_id": item.video_id,
        "index": item.index,
        "title": item.title,
        "duration_text": item.duration_text,
        "duration_sec": item.duration_sec,
        "hd": item.hd,
        "category": item.category,
        "page_url": item.page_url,
        "cover_url": item.cover_url,
        "source_id": item.source_id,
        "viewkey": item.viewkey,
    }


async def run_video_info(
    service: QueryService, raw_params: dict[str, Any]
) -> dict[str, Any]:
    """按 video_id 或 (result_id,index) 取条目，返回完整字段；纯本地，不访问网络。

    video_id 优先；未提供 video_id 时退回 (result_id, index)。
    index 是该条目在最近一次所属查询结果中的 1-based 位置，仅作参考。
    """
    params = parse_params(raw_params)
    item = None
    if params["video_id"]:
        item = service.find_by_video_id(params["video_id"])
    elif params["result_id"] and params["index"] is not None:
        item = service.find_item(params["result_id"], params["index"])
    if item is None:
        return {
            "found": False,
            "reason": "找不到对应视频，请确认 video_id 或 (result_id, index)",
        }
    return build_output(item)
