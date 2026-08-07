"""91tool_send_media：发送决策（原片超限自动压缩），实际发包在 main handler 执行。"""
from __future__ import annotations

from typing import Any

from ..core.send_service import SendService


def parse_params(raw: dict[str, Any]) -> dict[str, Any]:
    """把 tool 入参规整为 SendService.resolve_send 的关键字参数。"""
    def opt_str(key: str) -> str | None:
        value = raw.get(key)
        return value or None

    return {
        "video_id": opt_str("video_id"),
        "asset": opt_str("asset"),
        "path": opt_str("path"),
        "uncensored": _parse_bool(raw.get("uncensored")),
        "as_file": _parse_bool(raw.get("as_file")),
    }


def _parse_bool(value) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


async def run_send_media(service: SendService, raw_params: dict[str, Any]) -> dict[str, Any]:
    """解析参数并产出发送决策字典（含原片压缩补救）。

    action=send 时 main handler 按 kind/as_file 发包；action=reject 时直接回文字。
    compressed=True 表示发出的是压缩版原片。
    """
    params = parse_params(raw_params)
    decision = await service.resolve_send(**params)
    return {
        "action": decision.action,
        "kind": decision.kind,
        "asset": decision.asset,
        "path": decision.path,
        "size_bytes": decision.size_bytes,
        "effective_level": decision.effective_level,
        "as_file": decision.as_file,
        "compressed": decision.compressed,
        "reason": decision.reason,
    }
