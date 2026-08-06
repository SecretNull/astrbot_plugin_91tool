"""详情页视频源解析、可信校验、下载与时长校验。

本模块是整个项目里唯一访问详情页的地方，由 VideoService 在准备原视频时调用。
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import random
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from aiohttp import ClientSession


class VideoSourceError(RuntimeError):
    """视频源解析、下载或校验失败。"""


@dataclass(frozen=True)
class VideoSource:
    """详情页声明的媒体源。"""

    media_url: str
    source_id: str
    expected_duration: float | None
    refreshes: int = 0


@dataclass(frozen=True)
class VideoProbe:
    """本地视频的媒体探测结果。"""

    duration: float
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None


def parse_video_source(page_html: str) -> VideoSource:
    """从详情页的播放器配置解析 MP4 地址和声明时长。

    @param page_html 详情页 HTML。
    @return 解析到的媒体源。
    @raise VideoSourceError 页面未提供可用 MP4 源时抛出。
    """
    expected_duration = _parse_expected_duration(page_html)
    encoded_sources = re.findall(
        r"strencode2\(\s*['\"]([^'\"]+)['\"]\s*\)", page_html, re.IGNORECASE)
    for encoded_source in encoded_sources:
        source_html = html.unescape(unquote(encoded_source))
        match = re.search(
            r"<source\s+[^>]*\bsrc=['\"]([^'\"]+)['\"]",
            source_html,
            re.IGNORECASE,
        )
        if match and match.group(1).lower().split("?", 1)[0].endswith(".mp4"):
            media_url = html.unescape(match.group(1))
            return VideoSource(media_url, extract_source_id(media_url), expected_duration)
    raise VideoSourceError("详情页未找到动态 MP4 播放源")


def extract_source_id(media_url: str) -> str:
    """从 MP4 地址的纯数字文件名提取视频源 ID。"""
    name = os.path.basename(urlparse(media_url or "").path)
    stem, extension = os.path.splitext(name)
    if extension.lower() != ".mp4" or not stem.isdigit():
        return ""
    return stem


def _parse_expected_duration(page_html: str) -> float | None:
    """提取页面 JavaScript 中的视频时长声明。

    @param page_html 详情页 HTML。
    @return 秒数；页面没有时长时返回 None。
    """
    match = re.search(r"\bvideoDuration\s*=\s*([0-9]+(?:\.[0-9]+)?)", page_html)
    if match:
        return float(match.group(1))
    match = re.search(r"Runtime:\s*</span>\s*([0-9]{2}):([0-9]{2}):([0-9]{2})", page_html)
    if not match:
        return None
    hour, minute, second = (int(value) for value in match.groups())
    return hour * 3600 + minute * 60 + second


async def fetch_video_source(session: ClientSession, page_url: str,
                             timeout: float = 30.0, proxy: str = None) -> VideoSource:
    """请求详情页并解析当前候选视频源。

    @param session aiohttp 会话。
    @param page_url 视频详情页地址。
    @param timeout 请求超时秒数。
    @param proxy 可选 HTTP/HTTPS 代理。
    @return 当前详情页返回的媒体源。
    """
    headers = {"Referer": "https://www.91porn.com/"}
    async with session.get(page_url, timeout=timeout, proxy=proxy, headers=headers) as response:
        if response.status != 200:
            raise VideoSourceError(f"详情页请求失败：HTTP {response.status}")
        return parse_video_source(await response.text())


async def fetch_matching_video_source(
    session: ClientSession,
    page_url: str,
    expected_source_id: str,
    max_refreshes: int = 3,
    timeout: float = 30.0,
    proxy: str = None,
    retry_delay_min: float = 2.0,
    retry_delay_max: float = 5.0,
) -> VideoSource:
    """获取与列表封面 ID 匹配的视频源。

    @param session aiohttp 会话。
    @param page_url 视频详情页地址。
    @param expected_source_id 列表封面声明的数字视频源 ID。
    @param max_refreshes 首次请求失败后最多刷新的次数。
    @param timeout 单次详情页请求超时秒数。
    @param proxy 可选 HTTP/HTTPS 代理。
    @param retry_delay_min 刷新前最小等待秒数。
    @param retry_delay_max 刷新前最大等待秒数。
    @return ID 匹配的视频源及实际刷新次数。
    @raise VideoSourceError 达到刷新上限后仍不匹配时抛出。
    """
    if max_refreshes < 0:
        raise ValueError("max_refreshes 不能小于 0")
    if not expected_source_id or not str(expected_source_id).isdigit():
        raise ValueError("expected_source_id 必须是数字视频源 ID")
    if retry_delay_min < 0 or retry_delay_max < retry_delay_min:
        raise ValueError("刷新等待时间范围无效")

    expected_source_id = str(expected_source_id)
    last_source_id = "无法识别"
    for refreshes in range(max_refreshes + 1):
        source = await fetch_video_source(session, page_url, timeout, proxy)
        if source.source_id == expected_source_id:
            return VideoSource(
                source.media_url,
                source.source_id,
                source.expected_duration,
                refreshes,
            )
        last_source_id = source.source_id or "无法识别"
        if refreshes < max_refreshes:
            await asyncio.sleep(random.uniform(retry_delay_min, retry_delay_max))

    raise VideoSourceError(
        f"刷新详情页 {max_refreshes} 次后视频源 ID 仍不匹配："
        f"期望 {expected_source_id}，最后实际 {last_source_id}"
    )


async def download_verified_video(session: ClientSession, page_url: str,
                                  expected_source_id: str, output_path: str,
                                  max_refreshes: int = 3, timeout: float = 1800.0,
                                  proxy: str = None, retry_delay_min: float = 2.0,
                                  retry_delay_max: float = 5.0) -> VideoProbe:
    """下载与详情页声明时长匹配的视频。

    @param session aiohttp 会话。
    @param page_url 视频详情页地址。
    @param expected_source_id 列表封面声明的数字视频源 ID。
    @param output_path 校验成功后的 MP4 输出路径。
    @param max_refreshes 视频源 ID 不匹配时最多刷新的次数，不含首次请求。
    @param timeout 单次下载超时秒数。
    @param proxy 可选 HTTP/HTTPS 代理。
    @param retry_delay_min 失败后重试的最小等待秒数。
    @param retry_delay_max 失败后重试的最大等待秒数。
    @return 已保存视频的媒体信息。
    @raise VideoSourceError 达到刷新上限仍不匹配或下载失败时抛出。
    """
    source = await fetch_matching_video_source(
        session,
        page_url,
        expected_source_id,
        max_refreshes,
        timeout,
        proxy,
        retry_delay_min,
        retry_delay_max,
    )
    return await download_video_source(
        session,
        source,
        page_url,
        output_path,
        timeout,
        proxy,
    )


async def download_video_source(
    session: ClientSession,
    source: VideoSource,
    page_url: str,
    output_path: str,
    timeout: float = 60.0,
    proxy: str = None,
) -> VideoProbe:
    """下载并校验一个已经通过 ID 匹配的视频源。

    @param session aiohttp 会话。
    @param source 已匹配的视频源。
    @param page_url 视频详情页地址。
    @param output_path 校验成功后的 MP4 输出路径。
    @param timeout 下载超时秒数。
    @param proxy 可选 HTTP/HTTPS 代理。
    @return 已保存视频的媒体信息。
    @raise VideoSourceError 远程或本地视频时长校验失败时抛出。
    """
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f".{destination.stem}_{uuid.uuid4().hex}.mp4")
    try:
        remote_probe = await probe_media_url(source.media_url, page_url)
        if not duration_matches(source.expected_duration, remote_probe.duration):
            raise VideoSourceError(
                f"页面声明 {source.expected_duration:.3f} 秒，"
                f"候选媒体实际 {remote_probe.duration:.3f} 秒"
            )
        await _download_video(session, source.media_url, page_url, temporary_path, timeout, proxy)
        probe = await probe_video(temporary_path)
        if not duration_matches(source.expected_duration, probe.duration):
            raise VideoSourceError("下载完成后的媒体时长与页面声明不一致")
        os.replace(temporary_path, destination)
        return probe
    finally:
        temporary_path.unlink(missing_ok=True)


async def _download_video(session: ClientSession, media_url: str, page_url: str,
                          output_path: Path, timeout: float, proxy: str | None) -> None:
    """下载一个候选 MP4 文件。

    @param session aiohttp 会话。
    @param media_url 候选 MP4 地址。
    @param page_url 对应详情页地址。
    @param output_path 临时输出文件。
    @param timeout 请求超时秒数。
    @param proxy 可选 HTTP/HTTPS 代理。
    """
    headers = {"Referer": page_url}
    async with session.get(media_url, timeout=timeout, proxy=proxy, headers=headers) as response:
        if response.status != 200:
            raise VideoSourceError(f"媒体下载失败：HTTP {response.status}")
        with output_path.open("wb") as output_file:
            while chunk := await response.content.read(256 * 1024):
                output_file.write(chunk)


async def probe_video(video_path: Path) -> VideoProbe:
    """调用 ffprobe 获取本地视频媒体信息。

    @param video_path 本地 MP4 路径。
    @return 时长、分辨率与编码信息。
    @raise VideoSourceError 本机没有 ffprobe 或探测失败时抛出。
    """
    return await _probe_input(str(video_path))


async def probe_media_url(media_url: str, page_url: str) -> VideoProbe:
    """通过 Range 请求探测远程 MP4，避免下载短替代源。

    @param media_url 候选 MP4 地址。
    @param page_url 对应详情页地址。
    @return 时长、分辨率与编码信息。
    @raise VideoSourceError 远程媒体探测失败时抛出。
    """
    return await _probe_input(
        media_url,
        "-headers",
        f"Referer: {page_url}\r\n",
    )


async def _probe_input(input_value: str, *input_options: str) -> VideoProbe:
    """调用 ffprobe 探测本地文件或远程媒体。

    @param input_value 本地路径或远程 URL。
    @param input_options 输入参数，例如 HTTP 请求头。
    @return 时长、分辨率与编码信息。
    @raise VideoSourceError 本机没有 ffprobe 或探测失败时抛出。
    """
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        raise VideoSourceError("未安装 ffprobe，无法校验视频时长")
    process = await asyncio.create_subprocess_exec(
        ffprobe_path,
        "-v", "error",
        *input_options,
        "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
        "-of", "json",
        input_value,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise VideoSourceError(f"ffprobe 失败：{stderr.decode(errors='replace').strip()}")
    try:
        data = json.loads(stdout)
        duration = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise VideoSourceError("ffprobe 未返回有效时长") from error
    streams = data.get("streams", [])
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), {})
    return VideoProbe(
        duration=duration,
        width=video_stream.get("width"),
        height=video_stream.get("height"),
        video_codec=video_stream.get("codec_name"),
        audio_codec=audio_stream.get("codec_name"),
    )


def duration_matches(expected_duration: float | None, actual_duration: float,
                     ratio_tolerance: float = 0.01, minimum_tolerance: float = 2.0) -> bool:
    """判断候选视频的实际时长是否与页面声明一致。

    @param expected_duration 页面声明时长，单位秒。
    @param actual_duration ffprobe 实测时长，单位秒。
    @param ratio_tolerance 相对时长误差上限。
    @param minimum_tolerance 最小允许误差，单位秒。
    @return 未声明时长或误差在允许范围内返回 True。
    """
    if expected_duration is None:
        return True
    return abs(expected_duration - actual_duration) <= max(
        minimum_tolerance,
        expected_duration * ratio_tolerance,
    )
