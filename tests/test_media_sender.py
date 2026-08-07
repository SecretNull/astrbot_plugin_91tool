"""media_sender 策略层测试：审核等级、容量、asset 分类、配置解析。"""
import pytest

from astrbot_plugin_91tool.core.media_sender import (
    ACTION_REJECT,
    ACTION_SEND,
    LEVEL_MOSAIC_ONLY,
    LEVEL_UNCENSORED,
    SendConfig,
    classify_kind,
    decide,
)


def _decide(asset, size=100, uncensored=False, as_file=False, config=None):
    return decide(
        asset=asset, path="/tmp/x", size_bytes=size,
        uncensored=uncensored, as_file=as_file, config=config or SendConfig(),
    )


def test_classify_kind():
    assert classify_kind("original") == "video"
    assert classify_kind("preview_mosaic") == "video"
    assert classify_kind("render_image") == "image"
    assert classify_kind("gif_clean") == "image"
    assert classify_kind("cover") == "image"


def test_mosaic_only_rejects_uncensored_asset():
    decision = _decide("original")
    assert decision.action == ACTION_REJECT
    assert "uncensored" in decision.reason
    assert decision.effective_level == LEVEL_MOSAIC_ONLY


def test_mosaic_only_allows_mosaic_asset():
    decision = _decide("preview_mosaic")
    assert decision.action == ACTION_SEND


def test_uncensored_releases_original():
    decision = _decide("original", uncensored=True)
    assert decision.action == ACTION_SEND
    assert decision.effective_level == LEVEL_UNCENSORED


def test_image_over_limit_rejected():
    config = SendConfig(image_max_bytes=100, video_max_bytes=1000)
    decision = _decide("render_image", size=200, config=config)
    assert decision.action == ACTION_REJECT
    assert "超过上限" in decision.reason


def test_video_over_limit_rejected():
    config = SendConfig(image_max_bytes=100, video_max_bytes=1000)
    decision = _decide("preview_mosaic", size=2000, config=config)
    assert decision.action == ACTION_REJECT


def test_as_file_passthrough():
    decision = _decide("preview_mosaic", as_file=True)
    assert decision.action == ACTION_SEND
    assert decision.as_file is True


def test_send_config_from_mapping():
    config = SendConfig.from_mapping({
        "image_max_bytes": "5242880",
        "video_max_bytes": "52428800",
        "default_send_level": "uncensored",
    })
    assert config.image_max_bytes == 5242880
    assert config.video_max_bytes == 52428800
    assert config.default_level == LEVEL_UNCENSORED


def test_send_config_invalid_level_falls_back():
    config = SendConfig.from_mapping({"default_send_level": "weird"})
    assert config.default_level == LEVEL_MOSAIC_ONLY


def test_send_config_empty_uses_defaults():
    config = SendConfig.from_mapping({})
    assert config.image_max_bytes == SendConfig().image_max_bytes
    assert config.default_level == LEVEL_MOSAIC_ONLY
