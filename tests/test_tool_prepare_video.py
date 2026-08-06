"""VideoService / 91tool_prepare_video 测试。

用 monkeypatch 替换 video_source 的详情页校验与下载，避开真实网络和 ffprobe，
聚焦缓存命中、校验下载写缓存、source_id 缺失拒绝等业务逻辑。
"""
from pathlib import Path

from astrbot_plugin_91tool.core import video_source
from astrbot_plugin_91tool.core.config import QueryConfig, VideoConfig
from astrbot_plugin_91tool.core.media_cache import ASSET_ORIGINAL, MediaCache
from astrbot_plugin_91tool.core.query_service import QueryService
from astrbot_plugin_91tool.core.result_store import ResultStore
from astrbot_plugin_91tool.core.video_registry import VideoRegistry
from astrbot_plugin_91tool.core.video_service import VideoService
from astrbot_plugin_91tool.tools import prepare_video as prep_tool


def _setup(clock, make_rec, fetcher_factory, tmp_path):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1001"),
        make_rec(source_id="", link="https://www.91porn.com/view_video.php?viewkey=onlyvk"),
    ])
    store = ResultStore(max_results=10, ttl_seconds=3600, now=clock)
    registry = VideoRegistry(max_entries=10, ttl_seconds=3600, now=clock)
    qs = QueryService(fetcher, QueryConfig(), store, registry, now=clock)
    cache = MediaCache(str(tmp_path), retention_hours=24, now=clock)
    return qs, cache


def _patch_video_source(monkeypatch):
    async def fake_match(session, page_url, expected, **kw):
        return video_source.VideoSource("https://x/1001.mp4", "1001", None, refreshes=1)

    async def fake_download(session, source, page_url, output_path, **kw):
        Path(output_path).write_bytes(b"video-bytes")
        return video_source.VideoProbe(10.0, 1280, 720, "h264", "aac")

    monkeypatch.setattr(video_source, "fetch_matching_video_source", fake_match)
    monkeypatch.setattr(video_source, "download_video_source", fake_download)


async def test_prepare_cache_hit(clock, make_rec, fetcher_factory, tmp_path):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    cached_path = tmp_path / "v.mp4"
    cached_path.write_bytes(b"orig")
    cache.replace("1001", {ASSET_ORIGINAL: str(cached_path)})

    service = VideoService(None, cache, qs, VideoConfig(), str(tmp_path))
    out = await service.prepare(video_id="1001")
    assert out["ready"] is True
    assert out["cached"] is True
    assert out["path"] == str(cached_path)


async def test_prepare_downloads_and_caches(clock, make_rec, fetcher_factory, tmp_path, monkeypatch):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    _patch_video_source(monkeypatch)

    service = VideoService(object(), cache, qs, VideoConfig(), str(tmp_path))
    out = await service.prepare(video_id="1001")
    assert out["ready"] is True
    assert out["cached"] is False
    assert out["verified"] is True
    assert out["refreshes"] == 1
    assert out["duration_sec"] == 10.0
    assert out["size_bytes"] == len(b"video-bytes")
    assert cache.has("1001", ASSET_ORIGINAL)


async def test_prepare_rejects_missing_source_id(clock, make_rec, fetcher_factory, tmp_path):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    service = VideoService(None, cache, qs, VideoConfig(), str(tmp_path))

    out = await service.prepare(video_id="v_onlyvk")
    assert out["ready"] is False
    assert "source_id" in out["error"]


async def test_prepare_not_found(clock, make_rec, fetcher_factory, tmp_path):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    service = VideoService(None, cache, qs, VideoConfig(), str(tmp_path))

    out = await service.prepare(video_id="missing")
    assert out["ready"] is False
    assert "error" in out


async def test_prepare_by_result_id_and_index(clock, make_rec, fetcher_factory, tmp_path, monkeypatch):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    result = await qs.query()
    _patch_video_source(monkeypatch)

    service = VideoService(object(), cache, qs, VideoConfig(), str(tmp_path))
    out = await prep_tool.run_prepare_video(
        service, {"result_id": result.result_id, "index": 1}
    )
    assert out["ready"] is True
    assert out["video_id"] == "1001"


async def test_run_prepare_video_tool(clock, make_rec, fetcher_factory, tmp_path, monkeypatch):
    qs, cache = _setup(clock, make_rec, fetcher_factory, tmp_path)
    await qs.query()
    _patch_video_source(monkeypatch)

    service = VideoService(object(), cache, qs, VideoConfig(), str(tmp_path))
    out = await prep_tool.run_prepare_video(service, {"video_id": "1001"})
    assert out["ready"] is True
