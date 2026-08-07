"""视频压缩：用 FFmpeg 2-pass libx264 把视频压到目标大小内。纯子进程，不依赖 astrbot。"""
from __future__ import annotations

import os
import shutil
import subprocess


class CompressError(RuntimeError):
    """视频压缩失败。"""


def estimate_video_bitrate(target_bytes: int, duration: float, overhead_ratio: float = 0.82) -> int:
    """按目标大小与时长估算视频码率，留余量给音频与容器开销。

    @param target_bytes 目标文件字节数。
    @param duration 视频时长(秒)。
    @param overhead_ratio 码率折扣，给 aac 音频与 mp4 容器留余量。
    @return 视频码率(bps)，最低 200kbps 保证可编码。
    """
    if duration <= 0:
        raise ValueError("duration 必须大于 0")
    return max(200_000, int(target_bytes * overhead_ratio * 8 / duration))


def compress_video(
    src: str, out: str, duration: float, target_bytes: int, timeout: float = 300.0
) -> None:
    """2-pass libx264 + aac 编码到目标大小内。

    @param src 原视频路径。
    @param out 压缩输出路径。
    @param duration 原视频时长(秒)，用于估算码率。
    @param target_bytes 目标文件字节数。
    @param timeout 单次 ffmpeg 最长运行时间。
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CompressError("未安装 ffmpeg，无法压缩")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    bitrate = estimate_video_bitrate(target_bytes, duration)
    passlog = f"{out}.passlog"
    try:
        _run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
             "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(bitrate),
             "-pass", "1", "-passlogfile", passlog, "-an", "-f", "null", "-"],
            timeout,
        )
        _run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
             "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(bitrate),
             "-pass", "2", "-passlogfile", passlog,
             "-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart", out],
            timeout,
        )
    finally:
        for suffix in ("", "-0.log", "-0.log.mbtree"):
            try:
                os.remove(passlog + suffix)
            except OSError:
                pass


def _run(args: list[str], timeout: float) -> None:
    """运行 ffmpeg，失败或超时抛 CompressError。"""
    try:
        completed = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CompressError(f"ffmpeg 压缩超时（{timeout:g}s）") from exc
    if completed.returncode != 0:
        raise CompressError(
            f"ffmpeg 失败：{completed.stderr.decode(errors='replace')[:160]}"
        )
