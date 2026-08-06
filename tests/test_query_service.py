"""查询服务测试：结构化结果、组合筛选、page_size 截断、result_id 命中、定位。"""
import pytest

from astrbot_plugin_91tool.core.config import QueryConfig
from astrbot_plugin_91tool.core.query_service import QueryService, stable_video_id
from astrbot_plugin_91tool.core.result_store import ResultStore


def _build(fetcher, clock):
    store = ResultStore(max_results=10, ttl_seconds=3600, now=clock)
    service = QueryService(fetcher, QueryConfig(), store, now=clock)
    return service, store


def test_stable_video_id_prefers_source_id():
    assert stable_video_id("1024", "abc", "u") == "1024"


def test_stable_video_id_falls_back_to_viewkey():
    assert stable_video_id("", "abc", "u") == "v_abc"


def test_stable_video_id_falls_back_to_hash():
    vid = stable_video_id("", "", "https://www.91porn.com/view_video.php?viewkey=k")
    assert vid.startswith("h_") and len(vid) == 14


async def test_query_returns_structured_result(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1", duration="05:00"),
        make_rec(source_id="2", duration="20:00", hd=True),
    ])
    service, store = _build(fetcher, clock)
    result = await service.query(category="rf", page=1)

    assert result.category == "rf"
    assert result.page == 1
    assert result.raw_total == 2
    assert [item.video_id for item in result.items] == ["1", "2"]
    assert [item.index for item in result.items] == [1, 2]
    assert result.result_id
    assert store.get(result.result_id) is result
    assert fetcher.calls and fetcher.calls[0]["first"] is True


async def test_query_filter_min_duration(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1", duration="05:00"),
        make_rec(source_id="2", duration="20:00"),
    ])
    service, _ = _build(fetcher, clock)
    result = await service.query(min_duration=600)
    assert [item.video_id for item in result.items] == ["2"]
    assert result.filtered_out == 1


async def test_query_filter_hd_only(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1", hd=False),
        make_rec(source_id="2", hd=True),
    ])
    service, _ = _build(fetcher, clock)
    result = await service.query(hd=True)
    assert [item.video_id for item in result.items] == ["2"]
    assert result.filtered_out == 1


async def test_query_combined_filter(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1", duration="05:00", hd=False),
        make_rec(source_id="2", duration="20:00", hd=True),
        make_rec(source_id="3", duration="30:00", hd=True),
    ])
    service, _ = _build(fetcher, clock)
    result = await service.query(min_duration=600, max_duration=1500, hd=True)
    assert [item.video_id for item in result.items] == ["2"]
    assert result.filtered_out == 2


async def test_query_page_size_truncates(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id=str(i), duration="05:00") for i in range(5)
    ])
    service, _ = _build(fetcher, clock)
    result = await service.query(page_size=2)
    assert len(result.items) == 2
    assert result.truncated == 3
    assert [item.index for item in result.items] == [1, 2]


async def test_query_result_id_hit_returns_same(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[make_rec(source_id="1")])
    service, _ = _build(fetcher, clock)
    first = await service.query()
    second = await service.query(result_id=first.result_id)
    assert second is first
    assert len(fetcher.calls) == 1


async def test_find_item_by_result_id_and_index(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1"),
        make_rec(source_id="2"),
    ])
    service, _ = _build(fetcher, clock)
    result = await service.query()
    assert service.find_item(result.result_id, 2).video_id == "2"
    assert service.find_item(result.result_id, 99) is None
    assert service.find_item("missing", 1) is None


async def test_find_video_id(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[make_rec(source_id="7")])
    service, _ = _build(fetcher, clock)
    result = await service.query()
    assert service.find_video_id(result.result_id, 1) == "7"


async def test_query_rejects_invalid_page(clock, fetcher_factory):
    service, _ = _build(fetcher_factory(), clock)
    with pytest.raises(ValueError):
        await service.query(page=0)


async def test_query_rejects_negative_page_size(clock, fetcher_factory):
    service, _ = _build(fetcher_factory(), clock)
    with pytest.raises(ValueError):
        await service.query(page_size=-1)
