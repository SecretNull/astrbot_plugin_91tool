"""probe 探测模块测试：三通道文件生成、逐档发送记录、失败捕获、报告格式。"""
import os
import shutil

import pytest

from astrbot_plugin_91tool.core import probe


def test_generate_dummy_file_size(tmp_path):
    path = tmp_path / "d.bin"
    probe.generate_dummy_file(1024 + 512, str(path))
    assert path.stat().st_size == 1024 + 512


def test_generate_dummy_jpeg_creates_valid_image(tmp_path):
    from PIL import Image

    path = tmp_path / "t.jpg"
    probe.generate_dummy_jpeg(500 * 1024, str(path))
    assert path.stat().st_size > 0
    with Image.open(path) as img:
        img.verify()


def test_generate_dummy_video_requires_ffmpeg(tmp_path):
    if not shutil.which("ffmpeg"):
        with pytest.raises(probe.ProbeError):
            probe.generate_dummy_video(1024, str(tmp_path / "v.mp4"))
    else:
        path = tmp_path / "v.mp4"
        probe.generate_dummy_video(200 * 1024, str(path), timeout=30)
        assert path.stat().st_size > 0


async def test_probe_channel_file_records_ok(tmp_path):
    async def send(path, size_mb):
        assert os.path.exists(path)

    report = await probe.probe_channel("file", send, str(tmp_path), [1, 2])
    assert report.kind == "file"
    assert len(report.results) == 2
    assert all(r.ok for r in report.results)
    assert report.max_ok_bytes == 2 * 1024 * 1024


async def test_probe_channel_records_failure(tmp_path):
    async def send(path, size_mb):
        if size_mb > 1:
            raise RuntimeError("too big")

    report = await probe.probe_channel("file", send, str(tmp_path), [1, 2])
    assert report.results[0].ok is True
    assert report.results[1].ok is False
    assert "too big" in report.results[1].error
    assert report.max_ok_bytes == 1 * 1024 * 1024


async def test_probe_channel_image(tmp_path):
    async def send(path, size_mb):
        pass

    report = await probe.probe_channel("image", send, str(tmp_path), [1])
    assert report.kind == "image"
    assert len(report.results) == 1
    assert report.results[0].size_bytes > 0


async def test_probe_channel_unknown_kind(tmp_path):
    async def send(path, size_mb):
        pass

    with pytest.raises(ValueError):
        await probe.probe_channel("weird", send, str(tmp_path), [1])


async def test_probe_channel_cleans_files(tmp_path):
    async def send(path, size_mb):
        pass

    await probe.probe_channel("file", send, str(tmp_path), [1, 2])
    remaining = [p for p in tmp_path.iterdir() if p.name.startswith("probe_")]
    assert remaining == []


def test_format_report_single_channel():
    report = probe.ProbeReport(
        kind="image",
        results=[
            probe.ProbeResult(1 * 1024 * 1024, ok=True),
            probe.ProbeResult(2 * 1024 * 1024, ok=False, error="too big"),
        ],
    )
    text = probe.format_report(report)
    assert "[image]" in text
    assert "1MB" in text
    assert "最大成功" in text


def test_format_reports_multi_channel():
    reports = [
        probe.ProbeReport(kind="image", results=[probe.ProbeResult(1024, ok=True)]),
        probe.ProbeReport(kind="video", results=[probe.ProbeResult(2048, ok=False, error="err")]),
    ]
    text = probe.format_reports(reports)
    assert "[image]" in text
    assert "[video]" in text
    assert "全部失败" in text


def test_probe_config_from_mapping():
    config = probe.ProbeConfig.from_mapping({"probe_sizes_mb": "5, 25, 100"})
    assert config.sizes_mb == (5, 25, 100)


def test_probe_config_invalid_falls_back():
    config = probe.ProbeConfig.from_mapping({"probe_sizes_mb": "abc"})
    assert config.sizes_mb == probe.DEFAULT_PROBE_SIZES_MB
