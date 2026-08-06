"""测试共享夹具：可推进的时钟、假抓取器、VideoRecord 工厂。"""
from __future__ import annotations

import pytest

from astrbot_plugin_91tool.core.crawler import VideoRecord


class FakeClock:
    """可手动推进的时钟，用作 ResultStore/QueryService 的 now 注入。"""

    def __init__(self, start: float = 1000.0):
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeFetcher:
    """假列表抓取器：按构造时的固定记录或按调用次序的序列返回。"""

    def __init__(self, records=None, sequence=None):
        self.records = list(records or [])
        self.sequence = list(sequence or [])
        self.calls: list[dict] = []

    async def fetch(self, category, keyword, page, *, first=False):
        self.calls.append(
            {"category": category, "keyword": keyword, "page": page, "first": first}
        )
        if self.sequence:
            index = min(len(self.calls) - 1, len(self.sequence) - 1)
            return list(self.sequence[index])
        return list(self.records)


def make_record(**overrides) -> VideoRecord:
    """构造一个带默认值的 VideoRecord，测试中按需覆盖字段。"""
    fields = dict(
        title="示例视频",
        link="https://www.91porn.com/view_video.php?viewkey=abc",
        image_url="https://www.91porn.com/thumb/1024.jpg",
        duration="12:30",
        hd=False,
        source_id="1024",
    )
    fields.update(overrides)
    return VideoRecord(**fields)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_rec():
    return make_record


@pytest.fixture
def fetcher_factory():
    """返回一个工厂，按需构造 FakeFetcher。"""
    def _factory(records=None, sequence=None) -> FakeFetcher:
        return FakeFetcher(records=records, sequence=sequence)
    return _factory
