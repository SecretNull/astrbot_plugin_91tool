"""91tool_query 适配层测试：参数规整、结构化输出、端到端 run_query。"""
import pytest

from astrbot_plugin_91tool.core.config import QueryConfig
from astrbot_plugin_91tool.core.query_service import QueryService
from astrbot_plugin_91tool.core.result_store import ResultStore
from astrbot_plugin_91tool.tools import query as query_tool


def test_parse_params_defaults():
    params = query_tool.parse_params({})
    assert params["page"] == 1
    assert params["page_size"] is None
    assert params["min_duration"] is None
    assert params["max_duration"] is None
    assert params["hd"] is None
    assert params["category"] is None
    assert params["keyword"] == ""


def test_parse_params_zero_means_unbounded():
    params = query_tool.parse_params(
        {"page_size": 0, "min_duration": 0, "max_duration": 0}
    )
    assert params["page_size"] is None
    assert params["min_duration"] is None
    assert params["max_duration"] is None


def test_parse_params_hd_strings():
    assert query_tool.parse_params({"hd": "true"})["hd"] is True
    assert query_tool.parse_params({"hd": "false"})["hd"] is False
    assert query_tool.parse_params({"hd": ""})["hd"] is None
    assert query_tool.parse_params({"hd": "hd"})["hd"] is True


def test_parse_params_invalid_int():
    with pytest.raises(ValueError):
        query_tool.parse_params({"page": "abc"})


async def test_run_query_end_to_end(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1", duration="05:00", hd=True),
    ])
    store = ResultStore(max_results=10, ttl_seconds=3600, now=clock)
    service = QueryService(fetcher, QueryConfig(), store, now=clock)

    output = await query_tool.run_query(service, {"category": "rf", "page": "1"})

    assert output["result_id"]
    assert output["query"] == {"category": "rf", "keyword": "", "page": 1}
    assert output["stats"] == {"returned": 1, "raw_total": 1, "filtered_out": 0, "truncated": 0}
    assert output["items"][0]["video_id"] == "1"
    assert output["items"][0]["hd"] is True
    assert output["items"][0]["duration_sec"] == 300.0
    assert output["items"][0]["index"] == 1


async def test_run_query_applies_filter(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1", duration="05:00", hd=False),
        make_rec(source_id="2", duration="20:00", hd=True),
    ])
    store = ResultStore(max_results=10, ttl_seconds=3600, now=clock)
    service = QueryService(fetcher, QueryConfig(), store, now=clock)

    output = await query_tool.run_query(
        service, {"min_duration": "600", "hd": "true"}
    )
    assert [item["video_id"] for item in output["items"]] == ["2"]
    assert output["stats"]["filtered_out"] == 1
