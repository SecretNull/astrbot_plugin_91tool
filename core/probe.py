"""探测各平台媒体发送通道与大小上限。

支持三种通道：image(Comp.Image)、video(Comp.Video)、file(Comp.File)。
每种生成递增测试文件逐档发送，记录成败。发送动作抽象成可注入的 send 协程，
便于单测；生产环境由 main 的探测命令用 context.send_message 包装注入。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from PIL import Image

DEFAULT_PROBE_SIZES_MB: tuple[int, ...] = (1, 5, 10, 20, 50, 100)

# JPEG 边长上限：4096 足以测出图片通道上限（再大平台也不收）
_JPEG_MAX_SIDE = 4096


class ProbeError(RuntimeError):
    """探测文件生成失败。"""


@dataclass
class ProbeConfig:
    """探测档位（MB），三种通道共用。"""

    sizes_mb: tuple[int, ...] = DEFAULT_PROBE_SIZES_MB

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "ProbeConfig":
        source = mapping or {}
        raw = source.get("probe_sizes_mb", "")
        if not raw:
            return cls()
        try:
            sizes = tuple(int(part.strip()) for part in str(raw).split(",") if part.strip())
        except ValueError:
            return cls()
        return cls(sizes_mb=sizes or DEFAULT_PROBE_SIZES_MB)


@dataclass
class ProbeResult:
    """单个档位的探测结果。"""

    size_bytes: int
    ok: bool
    error: str = ""


@dataclass
class ProbeReport:
    """单个通道的探测汇总。"""

    kind: str = "file"
    results: list[ProbeResult] = field(default_factory=list)

    @property
    def max_ok_bytes(self) -> int:
        """最大成功档位的字节数；全失败返回 0。"""
        return max((r.size_bytes for r in self.results if r.ok), default=0)


def generate_dummy_file(size_bytes: int, path: str) -> None:
    """生成指定大小的占位文件（分块写零字节）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    chunk = b"\0" * (1024 * 1024)
    remaining = int(size_bytes)
    with open(path, "wb") as handle:
        while remaining > 0:
            write = min(remaining, len(chunk))
            handle.write(chunk[:write])
            remaining -= write


def generate_dummy_jpeg(target_bytes: int, path: str) -> None:
    """生成接近 target_bytes 的真实 JPEG（随机噪点，避免被压缩到过小）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pixels = max(64 * 64, int(target_bytes / 1.5))
    side = min(_JPEG_MAX_SIDE, int(pixels ** 0.5))
    data = os.urandom(side * side * 3)
    image = Image.frombytes("RGB", (side, side), data)
    image.save(path, "JPEG", quality=85)


def generate_dummy_video(target_bytes: int, path: str, timeout: float = 30.0) -> None:
    """用 ffmpeg 生成接近 target_bytes 的真实 MP4（testsrc + 目标码率）。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ProbeError("未安装 ffmpeg，无法生成测试视频")
    duration = 8
    bitrate = max(500_000, int(target_bytes * 8 / duration))
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30,noise=alls=100:allf=t",
        "-t", str(duration), "-b:v", str(bitrate), "-pix_fmt", "yuv420p", "-an", path,
    ]
    try:
        completed = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffmpeg 生成超时（{timeout:g}s）") from exc
    if completed.returncode != 0:
        raise ProbeError(
            f"ffmpeg 失败：{completed.stderr.decode(errors='replace')[:120]}"
        )


KIND_GENERATORS = {
    "file": (generate_dummy_file, ".bin"),
    "image": (generate_dummy_jpeg, ".jpg"),
    "video": (generate_dummy_video, ".mp4"),
}


async def probe_channel(
    kind: str,
    send: Callable[[str, int], Awaitable[None]],
    video_dir: str,
    sizes_mb: Sequence[int],
) -> ProbeReport:
    """对指定通道逐档生成测试文件并发送，返回 ProbeReport。

    生成在 to_thread 里执行，避免 ffmpeg/jpeg 编码阻塞事件循环。
    send(path, size_mb) 失败时抛异常，记为该档失败；文件用完即删。
    """
    if kind not in KIND_GENERATORS:
        raise ValueError(f"未知通道 {kind}，可选 {list(KIND_GENERATORS)}")
    generate, ext = KIND_GENERATORS[kind]
    report = ProbeReport(kind=kind)
    for size_mb in sizes_mb:
        target = int(size_mb) * 1024 * 1024
        path = os.path.join(video_dir, f"probe_{kind}_{size_mb}mb_{uuid.uuid4().hex[:6]}{ext}")
        try:
            await asyncio.to_thread(generate, target, path)
            actual = os.path.getsize(path)
        except Exception as exc:  # noqa: BLE001 生成失败要继续下一档
            report.results.append(ProbeResult(0, ok=False, error=f"生成失败：{exc}"))
            continue
        try:
            await send(path, int(size_mb))
            report.results.append(ProbeResult(actual, ok=True))
        except Exception as exc:  # noqa: BLE001 探测要捕获所有发送失败
            report.results.append(ProbeResult(actual, ok=False, error=str(exc)[:200]))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    return report


def format_report(report: ProbeReport) -> str:
    """单通道报告文字。"""
    lines = [f"[{report.kind}] 通道，共 {len(report.results)} 档："]
    for result in report.results:
        size_mb = result.size_bytes / (1024 * 1024)
        mark = "成功" if result.ok else "失败"
        extra = f"（{result.error}）" if result.error else ""
        lines.append(f"  {mark}  {size_mb:g}MB{extra}")
    if report.max_ok_bytes:
        lines.append(f"  → 最大成功：{report.max_ok_bytes / (1024 * 1024):g}MB")
    else:
        lines.append(f"  → 全部失败，[{report.kind}] 通道可能不支持")
    return "\n".join(lines)


def format_reports(reports: list[ProbeReport]) -> str:
    """多通道汇总文字。"""
    return "\n\n".join(format_report(report) for report in reports)
