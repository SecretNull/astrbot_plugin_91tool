"""91tool_video_info 适配层测试：按 video_id 与 (result_id,index) 定位、未命中、纯本地。"""
from astrbot_plugin_91tool.core.config import QueryConfig
from astrbot_plugin_91tool.core.query_service import QueryService
from astrbot_plugin_91tool.core.result_store import ResultStore
from astrbot_plugin_91tool.core.video_registry import VideoRegistry
from astrbot_plugin_91tool.tools import video_info as vi_tool


def _service(clock, make_rec, fetcher_factory) -> QueryService:
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1"),
        make_rec(source_id="2", hd=True),
    ])
    store = ResultStore(max_results=10, ttl_seconds=3600, now=clock)
    registry = VideoRegistry(max_entries=10, ttl_seconds=3600, now=clock)
    return QueryService(fetcher, QueryConfig(), store, registry, now=clock)


async def test_video_info_by_video_id(clock, make_rec, fetcher_factory):
    service = _service(clock, make_rec, fetcher_factory)
    await service.query()

    output = await vi_tool.run_video_info(service, {"video_id": "1"})
    assert output["found"] is True
    assert output["video_id"] == "1"
    assert output["cover_url"]
    assert output["source_id"] == "1"
    assert output["page_url"].startswith("https://www.91porn.com/view_video.php")


async def test_video_info_by_result_id_and_index(clock, make_rec, fetcher_factory):
    service = _service(clock, make_rec, fetcher_factory)
    result = await service.query()

    output = await vi_tool.run_video_info(
        service, {"result_id": result.result_id, "index": 2}
    )
    assert output["found"] is True
    assert output["video_id"] == "2"
    assert output["hd"] is True


async def test_video_info_not_found(clock, make_rec, fetcher_factory):
    service = _service(clock, make_rec, fetcher_factory)
    await service.query()

    output = await vi_tool.run_video_info(service, {"video_id": "999"})
    assert output["found"] is False


async def test_video_info_no_params(clock, make_rec, fetcher_factory):
    service = _service(clock, make_rec, fetcher_factory)
    output = await vi_tool.run_video_info(service, {})
    assert output["found"] is False


async def test_video_info_is_local_no_fetch(clock, make_rec, fetcher_factory):
    """video_info 不应触发任何抓取（不进详情页、不进列表页）。"""
    service = _service(clock, make_rec, fetcher_factory)
    await service.query()
    fetch_calls_before = len(service.fetcher.calls)

    await vi_tool.run_video_info(service, {"video_id": "1"})
    assert len(service.fetcher.calls) == fetch_calls_before
