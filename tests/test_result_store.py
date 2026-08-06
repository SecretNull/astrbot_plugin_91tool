"""ResultStore 测试：存取、容量淘汰、TTL 过期。"""
import pytest

from astrbot_plugin_91tool.core.models import QueryResult
from astrbot_plugin_91tool.core.result_store import ResultStore


def _result(result_id: str, created_at: float) -> QueryResult:
    return QueryResult(
        result_id=result_id,
        category="rf",
        keyword="",
        page=1,
        page_size=0,
        items=(),
        raw_total=0,
        filtered_out=0,
        truncated=0,
        created_at=created_at,
    )


def test_put_and_get():
    store = ResultStore(max_results=10, ttl_seconds=100, now=lambda: 0)
    store.put(_result("a", 0))
    assert store.get("a") is not None
    assert store.get("missing") is None
    assert len(store) == 1


def test_capacity_evicts_oldest():
    store = ResultStore(max_results=2, ttl_seconds=1000, now=lambda: 0)
    store.put(_result("a", 1))
    store.put(_result("b", 2))
    store.put(_result("c", 3))
    assert store.get("a") is None
    assert store.get("b") is not None
    assert store.get("c") is not None
    assert len(store) == 2


def test_expired_get_returns_none_and_removes():
    current = [0]
    store = ResultStore(max_results=10, ttl_seconds=10, now=lambda: current[0])
    store.put(_result("a", 0))
    current[0] = 20
    assert store.get("a") is None
    assert len(store) == 0


def test_evict_expired_keeps_fresh():
    current = [0]
    store = ResultStore(max_results=10, ttl_seconds=10, now=lambda: current[0])
    store.put(_result("a", 0))
    store.put(_result("b", 5))
    current[0] = 15
    assert store.evict_expired() == 1
    assert store.get("a") is None
    assert store.get("b") is not None


def test_invalid_args():
    with pytest.raises(ValueError):
        ResultStore(max_results=0)
    with pytest.raises(ValueError):
        ResultStore(ttl_seconds=0)
