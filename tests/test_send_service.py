"""SendService 测试：原片超限压缩补救、其他产物超限拒绝、小文件直发。"""
from astrbot_plugin_91tool.core.media_cache import (
    ASSET_ORIGINAL,
    ASSET_PREVIEW_MOSAIC,
    MediaCache,
)
from astrbot_plugin_91tool.core.media_sender import ACTION_REJECT, ACTION_SEND, SendConfig
from astrbot_plugin_91tool.core.send_service import SendService


class FakeCompress:
    def __init__(self, return_value=None):
        self.return_value = return_value
        self.calls = []

    async def compress_original(self, video_id, target_bytes):
        self.calls.append((video_id, target_bytes))
        return self.return_value, "fake reason"


def _put_original(tmp_path, cache, size):
    path = tmp_path / "orig.mp4"
    path.write_bytes(b"x" * size)
    cache.replace("1001", {ASSET_ORIGINAL: str(path)})


async def test_original_over_limit_compressed(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    _put_original(tmp_path, cache, 20 * 1024 * 1024)
    comp_path = tmp_path / "comp.mp4"
    comp_path.write_bytes(b"x" * (5 * 1024 * 1024))
    compress = FakeCompress(return_value=str(comp_path))

    decision = await SendService(cache, SendConfig(), compress).resolve_send(
        video_id="1001", asset="original", uncensored=True
    )
    assert decision.action == ACTION_SEND
    assert decision.compressed is True
    assert decision.path == str(comp_path)
    assert compress.calls and compress.calls[0][0] == "1001"


async def test_original_over_limit_no_compress_service(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    _put_original(tmp_path, cache, 20 * 1024 * 1024)
    decision = await SendService(cache, SendConfig()).resolve_send(
        video_id="1001", asset="original", uncensored=True
    )
    assert decision.action == ACTION_REJECT
    assert "超过上限" in decision.reason


async def test_preview_over_limit_not_compressed(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"x" * (20 * 1024 * 1024))
    cache.replace("1001", {ASSET_PREVIEW_MOSAIC: str(preview)})
    compress = FakeCompress(return_value="/nonexistent")

    decision = await SendService(cache, SendConfig(), compress).resolve_send(
        video_id="1001", asset="preview_mosaic"
    )
    assert decision.action == ACTION_REJECT
    assert compress.calls == []


async def test_original_under_limit_sent_directly(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    _put_original(tmp_path, cache, 3 * 1024 * 1024)
    compress = FakeCompress()

    decision = await SendService(cache, SendConfig(), compress).resolve_send(
        video_id="1001", asset="original", uncensored=True
    )
    assert decision.action == ACTION_SEND
    assert decision.compressed is False
    assert compress.calls == []


async def test_compress_returns_none_falls_back_reject(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    _put_original(tmp_path, cache, 20 * 1024 * 1024)
    compress = FakeCompress(return_value=None)

    decision = await SendService(cache, SendConfig(), compress).resolve_send(
        video_id="1001", asset="original", uncensored=True
    )
    assert decision.action == ACTION_REJECT


async def test_resolve_send_path_mp4_treated_as_video(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    mp4 = tmp_path / "123_preview_clean_abc.mp4"
    mp4.write_bytes(b"x" * 100)

    decision = await SendService(cache, SendConfig()).resolve_send(
        path=str(mp4), uncensored=True
    )
    assert decision.action == ACTION_SEND
    assert decision.kind == "video"
    assert decision.asset == "preview_clean"


async def test_resolve_send_path_jpg_treated_as_image(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    jpg = tmp_path / "render_xyz.jpg"
    jpg.write_bytes(b"x" * 100)

    decision = await SendService(cache, SendConfig()).resolve_send(path=str(jpg))
    assert decision.action == ACTION_SEND
    assert decision.kind == "image"
    assert decision.asset == "render_image"
