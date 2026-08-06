"""preview 采样纯函数测试：目标时长、分段起点、边界。"""
import pytest

from astrbot_plugin_91tool.core import preview


def test_target_preview_duration_short():
    assert preview.target_preview_duration(100) == 10.0
    assert preview.target_preview_duration(300) == 10.0


def test_target_preview_duration_long():
    assert preview.target_preview_duration(2400) == 20.0
    assert preview.target_preview_duration(3000) == 20.0


def test_target_preview_duration_linear_mid():
    assert preview.target_preview_duration(1350) == 15.0


def test_target_preview_duration_invalid():
    with pytest.raises(ValueError):
        preview.target_preview_duration(0)
    with pytest.raises(ValueError):
        preview.target_preview_duration(-1)


def test_preview_segment_starts_short():
    assert preview.preview_segment_starts(10) == [0.0]


def test_preview_segment_starts_long_edges():
    starts = preview.preview_segment_starts(600)
    assert starts[0] == 0.0
    assert starts[-1] == pytest.approx(598.5)
    assert len(starts) >= 2


def test_preview_segment_starts_invalid():
    with pytest.raises(ValueError):
        preview.preview_segment_starts(0)
