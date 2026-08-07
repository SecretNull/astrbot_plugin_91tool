"""probe 探测模块测试：dummy 文件生成、逐档发送记录、失败捕获、报告格式。"""
import os

from astrbot_plugin_91tool.core import probe


def test_generate_dummy_file_size(tmp_path):
    path = tmp_path / "d.bin"
    probe.generate_dummy_file(1024 + 512, str(path))
    assert path.stat().st_size == 1024 + 512


def test_generate_dummy_file_zero(tmp_path):
    path = tmp_path / "empty.bin"
    probe.generate_dummy_file(0, str(path))
    assert path.stat().st_size == 0


async def test_probe_sizes_records_ok(tmp_path):
    async def send_file(path, size_mb):
        assert os.path.exists(path)

    report = await probe.probe_sizes(send_file, str(tmp_path), [1, 2])
    assert len(report.results) == 2
    assert all(r.ok for r in report.results)
    assert report.max_ok_bytes == 2 * 1024 * 1024


async def test_probe_sizes_records_failure(tmp_path):
    async def send_file(path, size_mb):
        if size_mb > 1:
            raise RuntimeError("too big")

    report = await probe.probe_sizes(send_file, str(tmp_path), [1, 2])
    assert report.results[0].ok is True
    assert report.results[1].ok is False
    assert "too big" in report.results[1].error
    assert report.max_ok_bytes == 1 * 1024 * 1024


async def test_probe_sizes_cleans_files(tmp_path):
    async def send_file(path, size_mb):
        pass

    await probe.probe_sizes(send_file, str(tmp_path), [1, 2])
    remaining = [p for p in tmp_path.iterdir() if p.name.startswith("probe_")]
    assert remaining == []


def test_format_report_contains_max():
    report = probe.ProbeReport(
        kind="file",
        results=[
            probe.ProbeResult(1 * 1024 * 1024, ok=True),
            probe.ProbeResult(2 * 1024 * 1024, ok=False, error="too big"),
        ],
    )
    text = probe.format_report(report)
    assert "1MB" in text
    assert "2MB" in text
    assert "最大成功" in text


def test_format_report_all_failed():
    report = probe.ProbeReport(
        kind="file",
        results=[probe.ProbeResult(1 * 1024 * 1024, ok=False, error="rejected")],
    )
    assert "均失败" in probe.format_report(report)


def test_probe_config_from_mapping():
    config = probe.ProbeConfig.from_mapping({"probe_sizes_mb": "5, 25, 100"})
    assert config.sizes_mb == (5, 25, 100)


def test_probe_config_invalid_falls_back():
    config = probe.ProbeConfig.from_mapping({"probe_sizes_mb": "abc"})
    assert config.sizes_mb == probe.DEFAULT_PROBE_SIZES_MB
