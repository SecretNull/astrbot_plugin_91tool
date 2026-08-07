"""91tool_query：结构化查询。核心逻辑不依赖 astrbot，便于单测。"""
from __future__ import annotations

from typing import Any

from ..core.query_service import QueryService


def parse_params(raw: dict[str, Any]) -> dict[str, Any]:
    """把 tool 入参规整为 QueryService.query 的关键字参数。

    空值、0、空串都视为"不限制"；非法数字或布尔抛 ValueError。
    """
    def opt_int(key: str) -> int | None:
        value = raw.get(key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} 必须是整数") from exc

    def opt_float(key: str) -> float | None:
        value = raw.get(key)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} 必须是数字") from exc

    def opt_bool(key: str) -> bool | None:
        value = raw.get(key)
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "hd"):
            return True
        if text in ("false", "0", "no"):
            return False
        raise ValueError(f"{key} 必须是布尔值")

    return {
        "category": raw.get("category") or None,
        "keyword": raw.get("keyword") or "",
        "page": opt_int("page") or 1,
        "page_size": opt_int("page_size") or None,
        "min_duration": opt_float("min_duration") or None,
        "max_duration": opt_float("max_duration") or None,
        "hd": opt_bool("hd"),
        "result_id": raw.get("result_id") or None,
    }


def _item_dict(item) -> dict[str, Any]:
    return {
        "index": item.index,
        "video_id": item.video_id,
        "title": item.title,
        "duration_text": item.duration_text,
        "duration_sec": item.duration_sec,
        "hd": item.hd,
        "page_url": item.page_url,
    }


def build_output(result) -> dict[str, Any]:
    """把 QueryResult 转为面向 AI 的结构化输出。"""
    return {
        "result_id": result.result_id,
        "query": {
            "category": result.category,
            "keyword": result.keyword,
            "page": result.page,
        },
        "stats": {
            "returned": len(result.items),
            "raw_total": result.raw_total,
            "filtered_out": result.filtered_out,
            "truncated": result.truncated,
        },
        "items": [_item_dict(item) for item in result.items],
        "hint": "列表结果建议用 render_list 渲染长图并以 send_media 发送(图文更直观)，或直接用 list_image 一步发长图；不要逐条文字罗列",
    }


async def run_query(service: QueryService, raw_params: dict[str, Any]) -> dict[str, Any]:
    """解析参数并执行查询，返回结构化输出（不发送任何媒体）。"""
    params = parse_params(raw_params)
    result = await service.query(**params)
    return build_output(result)
