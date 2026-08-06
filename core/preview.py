"""从本地原视频生成静音 MP4 与 GIF 预览。纯 FFmpeg 子进程，不依赖 astrbot。"""
from __future__ import annotations

import asyncio
import math
import os
import shutil
import uuid
from pathlib import Path


class PreviewError(RuntimeError):
    """预览参数或 FFmpeg 处理失败。"""


CLIP_DURATION = 1.5
PLAYBACK_SPEED = 1.5
MIN_PREVIEW_DURATION = 10.0
MAX_PREVIEW_DURATION = 20.0
SHORT_VIDEO_LIMIT = 15.0
LINEAR_START_DURATION = 300.0
LINEAR_END_DURATION = 2400.0


def target_preview_duration(video_duration: float) -> float:
    """计算 10～20 秒范围内的目标预览时长。

    @param video_duration 原视频实测时长，单位秒。
    @return 目标预览时长，单位秒。
    """
    if video_duration <= 0:
        raise ValueError("video_duration 必须大于 0")
    if video_duration <= LINEAR_START_DURATION:
        return MIN_PREVIEW_DURATION
    if video_duration >= LINEAR_END_DURATION:
        return MAX_PREVIEW_DURATION
    ratio = (
        (video_duration - LINEAR_START_DURATION)
        / (LINEAR_END_DURATION - LINEAR_START_DURATION)
    )
    return MIN_PREVIEW_DURATION + ratio * (
        MAX_PREVIEW_DURATION - MIN_PREVIEW_DURATION
    )


def preview_segment_starts(video_duration: float) -> list[float]:
    """计算预览片段起点，首尾贴边且中间均匀分布。

    @param video_duration 原视频实测时长，单位秒。
    @return 每个 1.5 秒片段的起点秒数；短视频只返回 0。
    """
    if video_duration <= 0:
        raise ValueError("video_duration 必须大于 0")
    if video_duration < SHORT_VIDEO_LIMIT:
        return [0.0]
    segment_count = max(
        2,
        math.floor(target_preview_duration(video_duration) + 0.5),
    )
    last_start = max(0.0, video_duration - CLIP_DURATION)
    return [
        last_start * index / (segment_count - 1)
        for index in range(segment_count)
    ]


async def generate_preview_video(
    source_path: str,
    output_path: str,
    video_duration: float,
    timeout: float = 5.0,
) -> None:
    """均匀截取原视频并生成 1.5 倍速静音 MP4 预览。

    @param source_path 本地原视频路径。
    @param output_path 预览 MP4 输出路径。
    @param video_duration 原视频实测时长，单位秒。
    @param timeout FFmpeg 最长运行时间，单位秒。
    """
    source = Path(source_path)
    if not source.is_file():
        raise PreviewError("原视频缓存不存在")
    starts = preview_segment_starts(video_duration)
    arguments = ["-hide_banner", "-loglevel", "error", "-y"]
    if video_duration < SHORT_VIDEO_LIMIT:
        arguments.extend(["-i", str(source)])
        filter_graph = (
            f"[0:v:0]setpts=(PTS-STARTPTS)/{PLAYBACK_SPEED},"
            "fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            "setsar=1,format=yuv420p[outv]"
        )
    else:
        for start in starts:
            arguments.extend([
                "-ss", f"{start:.6f}",
                "-t", f"{CLIP_DURATION:.6f}",
                "-i", str(source),
            ])
        filters = [
            f"[{index}:v:0]setpts=(PTS-STARTPTS)/{PLAYBACK_SPEED}[v{index}]"
            for index in range(len(starts))
        ]
        inputs = "".join(f"[v{index}]" for index in range(len(starts)))
        filters.append(
            f"{inputs}concat=n={len(starts)}:v=1:a=0,"
            "fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            "setsar=1,format=yuv420p[outv]"
        )
        filter_graph = ";".join(filters)
    arguments.extend([
        "-filter_complex", filter_graph,
        "-map", "[outv]",
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "24",
        "-movflags", "+faststart",
    ])
    await _run_ffmpeg(arguments, output_path, timeout)


async def generate_mosaic_video(
    source_path: str,
    output_path: str,
    mosaic_block: int,
    timeout: float = 5.0,
) -> None:
    """对无和谐 MP4 预览逐帧应用马赛克。

    @param source_path 无和谐 MP4 预览路径。
    @param output_path 打码 MP4 预览输出路径。
    @param mosaic_block 马赛克缩放比。
    @param timeout FFmpeg 最长运行时间，单位秒。
    """
    block = max(1, int(mosaic_block))
    if block <= 1:
        raise ValueError("mosaic_block 必须大于 1")
    filter_graph = (
        f"scale=iw/{block}:ih/{block}:flags=area,"
        f"scale=iw*{block}:ih*{block}:flags=neighbor,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,format=yuv420p"
    )
    arguments = [
        "-hide_banner", "-loglevel", "error", "-y",
        "-i", source_path,
        "-vf", filter_graph,
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "24",
        "-movflags", "+faststart",
    ]
    await _run_ffmpeg(arguments, output_path, timeout)


async def generate_preview_gif(
    source_path: str,
    output_path: str,
    width: int = 480,
    fps: int = 10,
    timeout: float = 5.0,
) -> None:
    """使用调色板从 MP4 预览生成循环 GIF。

    @param source_path MP4 预览路径。
    @param output_path GIF 输出路径。
    @param width GIF 最大宽度。
    @param fps GIF 帧率。
    @param timeout FFmpeg 最长运行时间，单位秒。
    """
    width = max(64, int(width))
    fps = max(1, int(fps))
    filter_graph = (
        f"fps={fps},scale='min({width},iw)':-2:flags=lanczos,"
        "split[gif_source][palette_source];"
        "[palette_source]palettegen=stats_mode=diff[palette];"
        "[gif_source][palette]paletteuse=dither=sierra2_4a:diff_mode=rectangle"
    )
    arguments = [
        "-hide_banner", "-loglevel", "error", "-y",
        "-i", source_path,
        "-filter_complex", filter_graph,
        "-an",
        "-loop", "0",
    ]
    await _run_ffmpeg(arguments, output_path, timeout)


async def _run_ffmpeg(arguments: list[str], output_path: str, timeout: float) -> None:
    """运行 FFmpeg 并以临时文件原子写入输出。

    @param arguments 不含可执行文件及输出路径的参数。
    @param output_path 最终输出路径。
    @param timeout 最长运行时间，单位秒。
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise PreviewError("未安装 ffmpeg，无法生成预览")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(
        f".{destination.stem}_{uuid.uuid4().hex}{destination.suffix}"
    )
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg_path,
            *arguments,
            str(temporary_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(1.0, timeout),
            )
        except asyncio.TimeoutError as error:
            process.kill()
            await process.communicate()
            raise PreviewError(f"FFmpeg 生成预览超时（{timeout:g} 秒）") from error
        if process.returncode:
            message = stderr.decode(errors="replace").strip()
            raise PreviewError(f"FFmpeg 生成预览失败：{message or '未知错误'}")
        if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
            raise PreviewError("FFmpeg 未生成有效预览文件")
        os.replace(temporary_path, destination)
    except OSError as error:
        raise PreviewError(f"FFmpeg 启动或写入失败：{error}") from error
    finally:
        temporary_path.unlink(missing_ok=True)
