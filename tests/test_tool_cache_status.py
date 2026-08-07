"""91tool_cache_status 测试：汇总各缓存层条目数与占用。"""
from astrbot_plugin_91tool.core.config import QueryConfig
from astrbot_plugin_91tool.core.crawler import VideoRecord
from astrbot_plugin_91tool.core.media_cache import ASSET_ORIGINAL, MediaCache
from astrbot_plugin_91tool.core.query_service import QueryService
from astrbot_plugin_91tool.core.result_store import ResultStore
from astrbot_plugin_91tool.core.video_registry import VideoRegistry
from astrbot_plugin_91tool.tools import cache_status as cs_tool


class _FakeFetcher:
    def __init__(self, records):
        self.records = records

    async def fetch(self, category, keyword, page, *, first=False):
        return list(self.records)


async def test_cache_status_reports_counts(tmp_path):
    store = ResultStore(max_results=10, ttl_seconds=3600)
    registry = VideoRegistry(max_entries=10, ttl_seconds=3600)
    media = MediaCache(str(tmp_path), retention_hours=24)
    service = QueryService(
        _FakeFetcher([VideoRecord("t", "https://x/v?viewkey=a", "https://x/i.jpg", "1:00", False, "1")]),
        QueryConfig(), store, registry,
    )
    await service.query()

    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes(b"hello")
    media.replace("1", {ASSET_ORIGINAL: str(mp4)})

    status = cs_tool.run_cache_status(store, registry, media)
    assert status["results"] == 1
    assert status["video_ids"] == 1
    assert status["media_bundles"] == 1
    assert status["total_size_bytes"] == 5


def test_cache_status_empty(tmp_path):
    store = ResultStore(max_results=10, ttl_seconds=3600)
    registry = VideoRegistry(max_entries=10, ttl_seconds=3600)
    media = MediaCache(str(tmp_path), retention_hours=24)
    status = cs_tool.run_cache_status(store, registry, media)
    assert status["results"] == 0
    assert status["total_size_bytes"] == 0
