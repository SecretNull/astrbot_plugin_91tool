"""RenderService / 91tool_render_list 测试。

用 monkeypatch 替换 build_longimage_from_items，聚焦条目子集解析、
打码控制、video_ids/result_id+indices 定位。
"""
from pathlib import Path

from astrbot_plugin_91tool.core import longimage
from astrbot_plugin_91tool.core.config import QueryConfig, RenderConfig
from astrbot_plugin_91tool.core.query_service import QueryService
from astrbot_plugin_91tool.core.render_service import RenderService
from astrbot_plugin_91tool.core.result_store import ResultStore
from astrbot_plugin_91tool.core.video_registry import VideoRegistry
from astrbot_plugin_91tool.tools import render_list as rl_tool


def _setup(clock, make_rec, fetcher_factory):
    fetcher = fetcher_factory(records=[
        make_rec(source_id="1"), make_rec(source_id="2"), make_rec(source_id="3"),
    ])
    qs = QueryService(
        fetcher, QueryConfig(), ResultStore(now=clock),
        VideoRegistry(now=clock), now=clock,
    )
    return qs


def _patch_build(monkeypatch):
    captured = {}

    async def fake_build(items, http_client, config, out_path, block, proxy=None):
        Path(out_path).write_bytes(b"jpg")
        captured["items"] = items
        captured["block"] = block
        return out_path

    monkeypatch.setattr(longimage, "build_longimage_from_items", fake_build)
    return captured


async def test_render_full(clock, make_rec, fetcher_factory, tmp_path, monkeypatch):
    qs = _setup(clock, make_rec, fetcher_factory)
    result = await qs.query()
    captured = _patch_build(monkeypatch)

    out = await RenderService(qs, None, RenderConfig(), str(tmp_path)).render(
        result_id=result.result_id
    )
    assert out["ready"] is True
    assert out["item_count"] == 3
    assert len(captured["items"]) == 3
    assert out["mosaic_applied"] is True


async def test_render_subset_by_indices(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs = _setup(clock, make_rec, fetcher_factory)
    result = await qs.query()
    captured = _patch_build(monkeypatch)

    out = await RenderService(qs, None, RenderConfig(), str(tmp_path)).render(
        result_id=result.result_id, indices=[2]
    )
    assert out["item_count"] == 1
    assert captured["items"][0].video_id == "2"
    assert out["indices"] == [2]


async def test_render_no_mosaic(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs = _setup(clock, make_rec, fetcher_factory)
    result = await qs.query()
    captured = _patch_build(monkeypatch)

    out = await RenderService(qs, None, RenderConfig(), str(tmp_path)).render(
        result_id=result.result_id, mosaic=False
    )
    assert out["mosaic_applied"] is False
    assert captured["block"] == 1


async def test_render_by_video_ids(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs = _setup(clock, make_rec, fetcher_factory)
    await qs.query()
    captured = _patch_build(monkeypatch)

    out = await RenderService(qs, None, RenderConfig(), str(tmp_path)).render(
        video_ids=["1", "3"]
    )
    assert out["item_count"] == 2
    assert [it.video_id for it in captured["items"]] == ["1", "3"]


async def test_render_result_not_found(clock, make_rec, fetcher_factory, tmp_path):
    qs = _setup(clock, make_rec, fetcher_factory)
    out = await RenderService(qs, None, RenderConfig(), str(tmp_path)).render(
        result_id="missing"
    )
    assert out["ready"] is False


async def test_render_empty_selection(clock, make_rec, fetcher_factory, tmp_path):
    qs = _setup(clock, make_rec, fetcher_factory)
    result = await qs.query()
    out = await RenderService(qs, None, RenderConfig(), str(tmp_path)).render(
        result_id=result.result_id, indices=[99]
    )
    assert out["ready"] is False


async def test_run_render_list_tool(
    clock, make_rec, fetcher_factory, tmp_path, monkeypatch
):
    qs = _setup(clock, make_rec, fetcher_factory)
    result = await qs.query()
    _patch_build(monkeypatch)

    out = await rl_tool.run_render_list(
        RenderService(qs, None, RenderConfig(), str(tmp_path)),
        {"result_id": result.result_id, "indices": "1,3"},
    )
    assert out["ready"] is True
    assert out["item_count"] == 2
    assert out["indices"] == [1, 3]
