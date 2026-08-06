"""领域模型纯函数测试：时长解析、viewkey 提取、筛选匹配。"""
from astrbot_plugin_91tool.core.models import (
    QueryFilter,
    VideoItem,
    extract_viewkey,
    matches_filter,
    parse_duration_text,
)


def _item(**overrides) -> VideoItem:
    fields = dict(
        video_id="1",
        index=1,
        title="t",
        duration_text="10:00",
        duration_sec=600.0,
        hd=False,
        page_url="https://www.91porn.com/view_video.php?viewkey=k",
        cover_url="c",
        source_id="1",
        viewkey="k",
        category="rf",
    )
    fields.update(overrides)
    return VideoItem(**fields)


def test_parse_duration_text():
    assert parse_duration_text("12:34") == 754.0
    assert parse_duration_text("1:02:03") == 3723.0
    assert parse_duration_text("45") == 45.0
    assert parse_duration_text("") is None
    assert parse_duration_text("abc") is None
    assert parse_duration_text("1:2:3:4") is None


def test_extract_viewkey():
    url = "https://www.91porn.com/view_video.php?viewkey=abc123&c=ch"
    assert extract_viewkey(url) == "abc123"
    assert extract_viewkey("") == ""
    assert extract_viewkey("https://www.91porn.com/") == ""


def test_matches_filter_duration_bounds():
    item = _item(duration_sec=600.0)
    assert matches_filter(item, QueryFilter(min_duration=300, max_duration=900))
    assert not matches_filter(item, QueryFilter(min_duration=700))
    assert not matches_filter(item, QueryFilter(max_duration=500))


def test_matches_filter_unknown_duration_excluded_when_bound():
    item = _item(duration_sec=None)
    assert matches_filter(item, QueryFilter())
    assert not matches_filter(item, QueryFilter(min_duration=60))
    assert not matches_filter(item, QueryFilter(max_duration=60))


def test_matches_filter_hd():
    assert matches_filter(_item(hd=True), QueryFilter(hd=True))
    assert not matches_filter(_item(hd=False), QueryFilter(hd=True))
    assert matches_filter(_item(hd=False), QueryFilter(hd=False))
    assert not matches_filter(_item(hd=True), QueryFilter(hd=False))
    assert matches_filter(_item(hd=True), QueryFilter(hd=None))
