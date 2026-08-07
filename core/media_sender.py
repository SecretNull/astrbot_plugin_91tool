"""媒体发送策略层：审核等级 + 容量检查，纯逻辑，不依赖 astrbot。

单一全局策略（不按平台分支）：默认 mosaic_only，用户明确 uncensored 才发无码；
图/视频容量超限 reject，compress/segment 接口预留。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# 当作视频发送的产物（视频消息 / 文件形式）
VIDEO_ASSETS = {"original", "preview_clean", "preview_mosaic"}
# 当作图片发送的产物（长图 / 封面 / GIF 当图）
IMAGE_ASSETS = {"render_image", "cover", "gif_clean", "gif_mosaic"}
# 无码（未打码）产物：默认 mosaic_only 时拒绝，需 uncensored
UNCENSORED_ASSETS = {"original", "preview_clean", "gif_clean"}

LEVEL_MOSAIC_ONLY = "mosaic_only"
LEVEL_UNCENSORED = "uncensored"

ACTION_SEND = "send"
ACTION_REJECT = "reject"


@dataclass
class SendConfig:
    """发送策略的全局配置（单一，不分平台）。"""

    image_max_bytes: int = 9961472  # 9.5MB，QQ 实测 10MB 硬限留 0.5MB 余量
    video_max_bytes: int = 9961472  # 9.5MB
    default_level: str = LEVEL_MOSAIC_ONLY

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "SendConfig":
        """从 AstrBot 配置映射构造，非法值回退默认值。"""
        source = mapping or {}

        def pick(key: str, cast, default):
            value = source.get(key, default)
            if value in (None, ""):
                return default
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        level = pick("default_send_level", str, cls.default_level)
        if level not in (LEVEL_MOSAIC_ONLY, LEVEL_UNCENSORED):
            level = cls.default_level
        return cls(
            image_max_bytes=pick("image_max_bytes", int, cls.image_max_bytes),
            video_max_bytes=pick("video_max_bytes", int, cls.video_max_bytes),
            default_level=level,
        )


@dataclass
class SendDecision:
    """发送策略对单个媒体文件的决策。"""

    action: str
    kind: str
    asset: str
    path: str
    size_bytes: int
    effective_level: str
    as_file: bool
    reason: str = ""
    compressed: bool = False


def classify_kind(asset: str) -> str:
    """按产物名归为 image 或 video。"""
    if asset in VIDEO_ASSETS:
        return "video"
    return "image"


def decide(
    *,
    asset: str,
    path: str,
    size_bytes: int,
    uncensored: bool,
    as_file: bool,
    config: SendConfig,
) -> SendDecision:
    """对一个待发媒体作决策：审核等级 + 容量检查。

    mosaic_only 默认下拒绝无码产物（original/preview_clean/gif_clean）；
    uncensored=True 时放开。容量超 image/video 上限拒绝。
    """
    kind = classify_kind(asset)
    effective_level = LEVEL_UNCENSORED if uncensored else config.default_level

    if effective_level != LEVEL_UNCENSORED and asset in UNCENSORED_ASSETS:
        return SendDecision(
            action=ACTION_REJECT,
            kind=kind,
            asset=asset,
            path=path,
            size_bytes=size_bytes,
            effective_level=effective_level,
            as_file=as_file,
            reason="默认仅发送打码版；如需无和谐请在调用时明确 uncensored=true",
        )

    max_bytes = config.image_max_bytes if kind == "image" else config.video_max_bytes
    if size_bytes > max_bytes:
        return SendDecision(
            action=ACTION_REJECT,
            kind=kind,
            asset=asset,
            path=path,
            size_bytes=size_bytes,
            effective_level=effective_level,
            as_file=as_file,
            reason=(
                f"{kind} 文件 {size_bytes} 字节超过上限 {max_bytes} 字节"
            ),
        )

    return SendDecision(
        action=ACTION_SEND,
        kind=kind,
        asset=asset,
        path=path,
        size_bytes=size_bytes,
        effective_level=effective_level,
        as_file=as_file,
    )
