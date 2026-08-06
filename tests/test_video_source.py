"""video_source 测试：详情页解析、ID 匹配刷新、时长校验、参数校验。

用 FakeSession 避开真实网络；下载/ffprobe 路径在 VideoService 测试里用 monkeypatch 覆盖。
"""
import urllib.parse

import pytest

from astrbot_plugin_91tool.core import video_source


class FakeResponse:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """按调用次序返回预设 (status, html)，超出则重复最后一个。"""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = 0

    def get(self, url, **kwargs):
        idx = min(self.calls, len(self.pages) - 1)
        self.calls += 1
        status, text = self.pages[idx]
        return FakeResponse(status, text)


def _page_with_source(source_id, duration=None):
    inner = f'<source src="https://cdn.example.com/{source_id}.mp4?t=1" type="video/mp4">'
    encoded = urllib.parse.quote(inner)
    page = f"<html><script>strencode2('{encoded}')</script></html>"
    if duration is not None:
        page += f"<script>videoDuration={duration};</script>"
    return page


def test_parse_video_source_extracts_mp4():
    source = video_source.parse_video_source(_page_with_source("12345", duration=600))
    assert source.media_url == "https://cdn.example.com/12345.mp4?t=1"
    assert source.source_id == "12345"
    assert source.expected_duration == 600.0


def test_parse_video_source_raises_without_mp4():
    with pytest.raises(video_source.VideoSourceError):
        video_source.parse_video_source("<html>no source</html>")


def test_extract_source_id():
    assert video_source.extract_source_id("https://cdn.x/12345.mp4?t=1") == "12345"
    assert video_source.extract_source_id("https://cdn.x/abc.mp4") == ""
    assert video_source.extract_source_id("https://cdn.x/12345.webm") == ""
    assert video_source.extract_source_id("") == ""


def test_duration_matches_none_expected():
    assert video_source.duration_matches(None, 10.0)


def test_duration_matches_accepts_close():
    assert video_source.duration_matches(600.0, 602.0)
    assert video_source.duration_matches(600.0, 598.0)


def test_duration_matches_rejects_short_decoy():
    assert not video_source.duration_matches(600.0, 10.0)


async def test_fetch_matching_refreshes_until_match():
    pages = [
        (200, _page_with_source("999")),
        (200, _page_with_source("999")),
        (200, _page_with_source("1024")),
    ]
    session = FakeSession(pages)
    source = await video_source.fetch_matching_video_source(
        session, "https://detail", "1024",
        max_refreshes=3, retry_delay_min=0, retry_delay_max=0,
    )
    assert source.source_id == "1024"
    assert source.refreshes == 2
    assert session.calls == 3


async def test_fetch_matching_max_refreshes_zero_single_request():
    session = FakeSession([(200, _page_with_source("999"))])
    with pytest.raises(video_source.VideoSourceError):
        await video_source.fetch_matching_video_source(
            session, "https://detail", "1024",
            max_refreshes=0, retry_delay_min=0, retry_delay_max=0,
        )
    assert session.calls == 1


async def test_fetch_matching_raises_when_never_matches():
    session = FakeSession([(200, _page_with_source("999"))])
    with pytest.raises(video_source.VideoSourceError):
        await video_source.fetch_matching_video_source(
            session, "https://detail", "1024",
            max_refreshes=2, retry_delay_min=0, retry_delay_max=0,
        )
    assert session.calls == 3


async def test_fetch_matching_rejects_empty_id():
    session = FakeSession([])
    with pytest.raises(ValueError):
        await video_source.fetch_matching_video_source(
            session, "https://detail", "", max_refreshes=0,
        )


async def test_download_verified_rejects_empty_id():
    session = FakeSession([])
    with pytest.raises(ValueError):
        await video_source.download_verified_video(
            session, "https://detail", "", "out.mp4", max_refreshes=0,
        )
