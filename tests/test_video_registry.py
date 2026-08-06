"""VideoRegistry 测试：存取、更新、容量淘汰、TTL 过期。"""
import pytest

from astrbot_plugin_91tool.core.models import VideoItem
from astrbot_plugin_91tool.core.video_registry import VideoRegistry


def _item(video_id: str, **overrides) -> VideoItem:
    fields = dict(
        video_id=video_id,
        index=1,
        title="t",
        duration_text="1:00",
        duration_sec=60.0,
        hd=False,
        page_url="https://www.91porn.com/view_video.php?viewkey=" + video_id,
        cover_url="c",
        source_id=video_id,
        viewkey=video_id,
        category="rf",
    )
    fields.update(overrides)
    return VideoItem(**fields)


def test_put_and_get(clock):
    registry = VideoRegistry(max_entries=10, ttl_seconds=100, now=clock)
    registry.put(_item("1"))
    assert registry.get("1") is not None
    assert registry.get("missing") is None
    assert len(registry) == 1


def test_put_updates_existing(clock):
    registry = VideoRegistry(max_entries=10, ttl_seconds=100, now=clock)
    registry.put(_item("1", title="old"))
    registry.put(_item("1", title="new"))
    assert len(registry) == 1
    assert registry.get("1").title == "new"


def test_capacity_evicts_oldest(clock):
    registry = VideoRegistry(max_entries=2, ttl_seconds=1000, now=clock)
    clock.advance(1)
    registry.put(_item("a"))
    clock.advance(1)
    registry.put(_item("b"))
    clock.advance(1)
    registry.put(_item("c"))
    assert registry.get("a") is None
    assert registry.get("b") is not None
    assert registry.get("c") is not None
    assert len(registry) == 2


def test_expired_get_returns_none(clock):
    registry = VideoRegistry(max_entries=10, ttl_seconds=10, now=clock)
    registry.put(_item("a"))
    clock.advance(20)
    assert registry.get("a") is None
    assert len(registry) == 0


def test_evict_expired(clock):
    registry = VideoRegistry(max_entries=10, ttl_seconds=10, now=clock)
    registry.put(_item("a"))
    clock.advance(5)
    registry.put(_item("b"))
    clock.advance(10)
    assert registry.evict_expired() == 1
    assert registry.get("a") is None
    assert registry.get("b") is not None


def test_invalid_args():
    with pytest.raises(ValueError):
        VideoRegistry(max_entries=0)
    with pytest.raises(ValueError):
        VideoRegistry(ttl_seconds=0)
