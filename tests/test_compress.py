"""compress 模块测试：码率估算、2-pass 调用、压缩服务缓存与失败处理。"""
import os
from pathlib import Path

import pytest

from astrbot_plugin_91tool.core import compress, video_source
from astrbot_plugin_91tool.core.compress_service import CompressService
from astrbot_plugin_91tool.core.media_cache import (
    ASSET_ORIGINAL,
    ASSET_ORIGINAL_COMPRESSED,
    MediaCache,
)


def test_estimate_video_bitrate_scales_with_target():
    short = compress.estimate_video_bitrate(1 * 1024 * 1024, duration=60.0)
    long_target = compress.estimate_video_bitrate(5 * 1024 * 1024, duration=60.0)
    assert short > 0
    assert long_target > short


def test_estimate_video_bitrate_minimum_floor():
    assert compress.estimate_video_bitrate(1024, duration=600.0) == 200_000


def test_estimate_video_bitrate_invalid_duration():
    with pytest.raises(ValueError):
        compress.estimate_video_bitrate(1024, duration=0)


def test_compress_video_runs_two_passes(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, capture_output=True, timeout=None):
        calls.append(args)
        if args[-1] != "-" :  # pass 2 真写输出文件
            Path(args[-1]).write_bytes(b"mp4")
        return type("R", (), {"returncode": 0, "stderr": b""})()

    monkeypatch.setattr(compress.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(compress.subprocess, "run", fake_run)

    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    compress.compress_video(str(src), str(out), duration=120.0, target_bytes=5 * 1024 * 1024)

    assert len(calls) == 2
    assert "-pass" in calls[0] and calls[0][calls[0].index("-pass") + 1] == "1"
    assert calls[0][-1] == "-"
    assert calls[1][calls[1].index("-pass") + 1] == "2"
    assert out.read_bytes() == b"mp4"


def test_compress_video_requires_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(compress.shutil, "which", lambda name: None)
    with pytest.raises(compress.CompressError):
        compress.compress_video(
            str(tmp_path / "s.mp4"), str(tmp_path / "o.mp4"), 60.0, 1024
        )


async def test_compress_service_uses_cache(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    cached_path = tmp_path / "c.mp4"
    cached_path.write_bytes(b"compressed")
    cache.replace("v1", {ASSET_ORIGINAL_COMPRESSED: str(cached_path)})

    service = CompressService(cache, str(tmp_path))
    result = await service.compress_original("v1", target_bytes=10 * 1024 * 1024)
    assert result == str(cached_path)


async def test_compress_service_compresses_original(tmp_path, monkeypatch):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    original = tmp_path / "orig.mp4"
    original.write_bytes(b"big")
    cache.replace("v1", {ASSET_ORIGINAL: str(original)})

    async def fake_probe(path):
        return video_source.VideoProbe(120.0, 1280, 720, "h264", "aac")

    def fake_compress(src, out, duration, target_bytes, timeout=300.0):
        Path(out).write_bytes(b"small")

    monkeypatch.setattr(video_source, "probe_video", fake_probe)
    monkeypatch.setattr(compress, "compress_video", fake_compress)

    service = CompressService(cache, str(tmp_path))
    result = await service.compress_original("v1", target_bytes=5 * 1024 * 1024)
    assert result is not None
    assert os.path.exists(result)
    assert cache.get_asset("v1", ASSET_ORIGINAL_COMPRESSED) == result


async def test_compress_service_returns_none_without_original(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    service = CompressService(cache, str(tmp_path))
    assert await service.compress_original("v1", target_bytes=1024) is None


async def test_compress_service_returns_none_when_over_target(tmp_path, monkeypatch):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    original = tmp_path / "orig.mp4"
    original.write_bytes(b"big")
    cache.replace("v1", {ASSET_ORIGINAL: str(original)})

    async def fake_probe(path):
        return video_source.VideoProbe(120.0, 1280, 720, "h264", "aac")

    def fake_compress(src, out, duration, target_bytes, timeout=300.0):
        Path(out).write_bytes(b"x" * (target_bytes + 1))  # 仍超限

    monkeypatch.setattr(video_source, "probe_video", fake_probe)
    monkeypatch.setattr(compress, "compress_video", fake_compress)

    service = CompressService(cache, str(tmp_path))
    assert await service.compress_original("v1", target_bytes=1024) is None
