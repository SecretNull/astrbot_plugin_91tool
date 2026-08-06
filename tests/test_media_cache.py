"""MediaCache 测试：bundle 存取、整包替换删旧、追加衍生、过期清理、状态。"""
import pytest

from astrbot_plugin_91tool.core.media_cache import (
    ASSET_GIF_CLEAN,
    ASSET_ORIGINAL,
    MediaCache,
)


def test_replace_and_get_asset(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    cache.replace("v1", {ASSET_ORIGINAL: str(p)})
    assert cache.get_asset("v1", ASSET_ORIGINAL) == str(p)
    assert cache.has("v1", ASSET_ORIGINAL)
    assert not cache.has("v1", ASSET_GIF_CLEAN)


def test_replace_deletes_old_assets(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    old = tmp_path / "a.mp4"
    old.write_bytes(b"old")
    new = tmp_path / "b.mp4"
    new.write_bytes(b"new")
    cache.replace("v1", {ASSET_ORIGINAL: str(old)})
    cache.replace("v1", {ASSET_ORIGINAL: str(new)})
    assert not old.exists()
    assert new.exists()
    assert cache.get_asset("v1", ASSET_ORIGINAL) == str(new)


def test_add_assets_keeps_original(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes(b"orig")
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"gif")
    cache.replace("v1", {ASSET_ORIGINAL: str(mp4)})
    cache.add_assets("v1", {ASSET_GIF_CLEAN: str(gif)})
    assert cache.has("v1", ASSET_ORIGINAL)
    assert cache.has("v1", ASSET_GIF_CLEAN)


def test_add_assets_requires_existing_bundle(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    with pytest.raises(ValueError):
        cache.add_assets("v1", {ASSET_GIF_CLEAN: str(tmp_path / "x.gif")})


def test_get_asset_drops_missing_file(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    cache.replace("v1", {ASSET_ORIGINAL: str(p)})
    p.unlink()
    assert cache.get_asset("v1", ASSET_ORIGINAL) is None


def test_cleanup_expired_removes_old_bundle(tmp_path):
    now = [900.0]
    cache = MediaCache(str(tmp_path), retention_hours=1 / 3600, now=lambda: now[0])
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    cache.replace("v1", {ASSET_ORIGINAL: str(p)})
    now[0] = 1000.0
    removed = cache.cleanup_expired()
    assert removed == 1
    assert not p.exists()


def test_cleanup_keeps_fresh(tmp_path):
    now = [1000.0]
    cache = MediaCache(str(tmp_path), retention_hours=1 / 3600, now=lambda: now[0])
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    cache.replace("v1", {ASSET_ORIGINAL: str(p)})
    now[0] = 1000.5
    assert cache.cleanup_expired() == 0
    assert p.exists()


def test_status_reports_size(tmp_path):
    cache = MediaCache(str(tmp_path), retention_hours=24)
    p = tmp_path / "a.mp4"
    p.write_bytes(b"hello")
    cache.replace("v1", {ASSET_ORIGINAL: str(p)})
    status = cache.status()
    assert status["bundles"] == 1
    assert status["total_size_bytes"] == 5


def test_invalid_retention(tmp_path):
    with pytest.raises(ValueError):
        MediaCache(str(tmp_path), retention_hours=0)
