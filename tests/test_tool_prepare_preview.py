"""PreviewService / 91tool_prepare_preview 测试。

用 monkeypatch 替换 ensure_original_path / probe_video / generate_*，
聚焦依赖链、缓存命中、打码复用、格式与 source_id 校验。
"""
from pathlib import Path

from astrbot_plugin_91tool.core import preview, video_source
from astrbot_plugin_91tool.core.config import PreviewConfig, QueryConfig, VideoConfig
from astrbot_plugin_91tool.core.media_cache import (
    ASSET_GIF_CLEAN,
    ASSET_ORIGINAL,
    ASSET_PREVIEW_CLEAN,
    ASSET_PREVIEW_MOSAIC,
    MediaCache,
)
from astrbot_plugin_91tool.core.preview_service import PreviewService
from astrbot_plugin_91tool.core.query_service import QueryService
from astrbot_plugin_91tool.core.result_store import ResultStore
from astrbot_plugin_91tool.core.video_registry import VideoRegistry
from astrbot_plugin_91tool.core.video_service import VideoService
from astrbot_plugin_91tool.tools import prepare_preview as pp_tool


def _setup(clock, make_rec, fetcher_factory, tmp_path):
    fetcher = fetcher_factory(records=[make_rec(source_id="1001")])
    store = ResultStore(max_results=10, ttl_seconds=3600, now=clock)
    registry = VideoRegistry(max_entries=10, ttl_seconds=3600, now=clock)
    qs = QueryService(fetcher, QueryConfig(), store, registry, now=clock)
    cache = MediaCache(str(tmp_path), retention_hours=24, now=clock)
    return qs, cache


def _patch(monkeypatch, tmp_path):
    original = tmp_path / "original.mp4"
    original.write_bytes(b"orig")

    async def fake_ensure(self, item):
        self.cache.replace(item.video_id, {ASSET_ORIGINAL: str(original)})
        return str(original)

    async def fake_probe(path):
        return video_source.VideoProbe(600.0, 1280, 720, "h264", "aac")

    async def fake_gen_video(src, out, dur, timeout=5):
        Path(out).write_bytes(b"preview")

    async def fake_gen_mosaic(src, out, block, timeout=5):
        Path(out).write_bytes(b"mosaic")

    async def fake_gen_gif(src, out, width=480, fps=10, timeout=5):
        Path(out).write_bytes(b"gif")

    monkeypatch.setattr(VideoService, "ensure_original_path", fake_ensure)
    monkeypatch.setattr(video_source, "probe_video", fake_probe)
    monkeypatch.setattr(preview, "generate_preview_video", fake_gen_video)
    monkeypatch.setattr(preview, "generate_mosaic_video", fake_gen_mosaic)
    monkeypatch.setattr(preview, "generate_preview_gif", fake_gen_gif)
    return original


def _service(qs, cache, tmp_path, preview_config=None):
    video_service = VideoService(None, cache, qs, VideoConfig(), str(tmp_path))
    return PreviewService(
        qs, video_service, cache, preview_config or PreviewConfig(), str(tmp_path)
    )


async def test_prepare_preview_clean(clock, make_rec, fetcher_factory, tmp_path, monkeypatch):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    _patch(monkeypatch, tmp_path)

    out = await _service(qs, cache, tmp_path).prepare_preview(
        video_id="1001", format="mp4", mosaic=False
    )
    assert out["ready"] is True
    assert out["format"] == "mp4"
    assert out["mosaic"] is False
    assert cache.has("1001", ASSET_PREVIEW_CLEAN)


async def test_prepare_preview_mosaic_makes_clean_and_mosaic(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    _patch(monkeypatch, tmp_path)

    out = await _service(qs, cache, tmp_path).prepare_preview(
        video_id="1001", format="mp4", mosaic=True
    )
    assert out["ready"] is True
    assert out["mosaic"] is True
    assert cache.has("1001", ASSET_PREVIEW_MOSAIC)
    assert cache.has("1001", ASSET_PREVIEW_CLEAN)


async def test_prepare_preview_mosaic_block_le_1_reuses_clean(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    _patch(monkeypatch, tmp_path)

    await _service(qs, cache, tmp_path, PreviewConfig(mosaic_block=1)).prepare_preview(
        video_id="1001", format="mp4", mosaic=True
    )
    mosaic_path = cache.get_asset("1001", ASSET_PREVIEW_MOSAIC)
    clean_path = cache.get_asset("1001", ASSET_PREVIEW_CLEAN)
    assert mosaic_path == clean_path


async def test_prepare_preview_gif_clean(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    _patch(monkeypatch, tmp_path)

    out = await _service(qs, cache, tmp_path).prepare_preview(
        video_id="1001", format="gif", mosaic=False
    )
    assert out["ready"] is True
    assert out["format"] == "gif"
    assert cache.has("1001", ASSET_GIF_CLEAN)


async def test_prepare_preview_cache_hit(
    clock, make_rec, fetcher_factory, tmp_path
):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    cached_path = tmp_path / "pre.mp4"
    cached_path.write_bytes(b"x")
    cache.replace("1001", {ASSET_PREVIEW_CLEAN: str(cached_path)})

    out = await _service(qs, cache, tmp_path).prepare_preview(
        video_id="1001", format="mp4", mosaic=False
    )
    assert out["ready"] is True
    assert out["cached"] is True
    assert out["path"] == str(cached_path)


async def test_prepare_preview_invalid_format(
    clock, make_rec, fetcher_factory, tmp_path
):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()

    out = await _service(qs, cache, tmp_path).prepare_preview(
        video_id="1001", format="webm"
    )
    assert out["ready"] is False
    assert "格式" in out["error"]


async def test_prepare_preview_missing_source_id(
    clock, make_rec, fetcher_factory, tmp_path
):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="", link="https://www.91porn.com/view_video.php?viewkey=vk")
    ])
    qs = QueryService(
        fetcher, QueryConfig(), ResultStore(now=clock),
        VideoRegistry(now=clock), now=clock,
    )
    cache = MediaCache(str(tmp_path), now=clock)
    await qs.query()

    out = await _service(qs, cache, tmp_path).prepare_preview(video_id="v_vk")
    assert out["ready"] is False
    assert "source_id" in out["error"]


async def test_prepare_preview_ensure_fail(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()

    async def fake_ensure(self, item):
        return None

    monkeypatch.setattr(VideoService, "ensure_original_path", fake_ensure)
    out = await _service(qs, cache, tmp_path).prepare_preview(video_id="1001")
    assert out["ready"] is False
    assert "原视频" in out["error"]


async def test_run_prepare_preview_tool(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    _patch(monkeypatch, tmp_path)

    service = _service(qs, cache, tmp_path)
    out = await pp_tool.run_prepare_preview(
        service, {"video_id": "1001", "format": "gif", "mosaic": "true"}
    )
    assert out["ready"] is True
    assert out["format"] == "gif"
    assert out["mosaic"] is True
