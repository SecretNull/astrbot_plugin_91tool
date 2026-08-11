"""ArchiveService 测试：标题清洗、目录组织、原片/封面/meta、无码预览、打码跳过。"""
import json

import pytest

from astrbot_plugin_91tool.core.archive_service import ArchiveService
from astrbot_plugin_91tool.core.models import VideoItem


def _item(**overrides) -> VideoItem:
    fields = dict(
        video_id="1230307",
        index=1,
        title="示例标题",
        duration_text="13:57",
        duration_sec=837.0,
        hd=False,
        page_url="https://www.91porn.com/view_video.php?viewkey=abc",
        cover_url="https://cdn.example.com/thumb/1230307.jpg",
        source_id="1230307",
        viewkey="abc",
        category="hot",
    )
    fields.update(overrides)
    return VideoItem(**fields)


class _FakeResponse:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def read(self):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, cover_data=b"jpeg"):
        self.cover_data = cover_data

    def get(self, url, headers=None):
        return _FakeResponse(200, self.cover_data)


def test_sanitize_title():
    assert ArchiveService._sanitize_title("正常标题") == "正常标题"
    assert ArchiveService._sanitize_title("a/b:c?d|e") == "a_b_c_d_e"
    assert ArchiveService._sanitize_title("") == "untitled"
    long = "字" * 100
    assert len(ArchiveService._sanitize_title(long)) == 80


def test_disabled_returns_none(tmp_path):
    service = ArchiveService(_FakeClient(), str(tmp_path), enabled=False)
    import asyncio
    result = asyncio.run(service.archive_original(_item(), str(tmp_path / "x.mp4")))
    assert result is None


def test_archive_original_copies_and_writes_meta(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"mp4data")
    service = ArchiveService(_FakeClient(b"cover"), str(tmp_path / "archive"), enabled=True)

    import asyncio
    folder = asyncio.run(service.archive_original(_item(), str(src)))

    folder_path = __import__("pathlib").Path(folder)
    assert (folder_path / "示例标题.mp4").read_bytes() == b"mp4data"
    assert (folder_path / "cover.jpg").read_bytes() == b"cover"
    meta = json.loads((folder_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["video_id"] == "1230307"
    assert meta["viewkey"] == "abc"
    assert "page_url" in meta and "cover_url" in meta


def test_archive_preview_skips_mosaic(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"preview")
    service = ArchiveService(_FakeClient(), str(tmp_path / "archive"), enabled=True)

    import asyncio
    # 打码预览不归档
    assert asyncio.run(service.archive_preview(_item(), str(src), "preview_mosaic")) is None
    # 无码 mp4 预览归档
    folder = asyncio.run(service.archive_preview(_item(), str(src), "preview_clean"))
    assert folder is not None
    folder_path = __import__("pathlib").Path(folder)
    assert (folder_path / "示例标题_preview.mp4").exists()


def test_archive_preview_gif_naming(tmp_path):
    src = tmp_path / "src.gif"
    src.write_bytes(b"gif")
    service = ArchiveService(_FakeClient(), str(tmp_path / "archive"), enabled=True)

    import asyncio
    folder = asyncio.run(service.archive_preview(_item(), str(src), "gif_clean"))
    folder_path = __import__("pathlib").Path(folder)
    assert (folder_path / "示例标题.gif").exists()


def test_archive_folder_reuses_same_video_id(tmp_path):
    src1 = tmp_path / "src1.mp4"
    src1.write_bytes(b"original")
    src2 = tmp_path / "src2.mp4"
    src2.write_bytes(b"preview")
    service = ArchiveService(_FakeClient(), str(tmp_path / "archive"), enabled=True)

    import asyncio
    folder1 = asyncio.run(service.archive_original(_item(), str(src1)))
    folder2 = asyncio.run(service.archive_preview(_item(), str(src2), "preview_clean"))
    assert folder1 == folder2  # 同 video_id 复用同一目录
