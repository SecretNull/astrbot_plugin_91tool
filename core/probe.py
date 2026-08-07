"""探测各平台文件发送大小上限：生成递增 dummy 文件，逐个发送，记录成功/失败。

发送动作抽象成可注入的 send_file(path, size_mb) 协程，便于单测；生产环境由
main 的探测命令用 context.send_message + Comp.File 包装注入。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

DEFAULT_PROBE_SIZES_MB: tuple[int, ...] = (1, 5, 10, 20, 50, 100)


@dataclass
class ProbeConfig:
    """探测档位（MB）。"""

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
    """一次探测的汇总。"""

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


async def probe_sizes(
    send_file: Callable[[str, int], Awaitable[None]],
    video_dir: str,
    sizes_mb: Sequence[int],
) -> ProbeReport:
    """逐个档位生成 dummy 文件并发送，返回 ProbeReport。

    send_file(path, size_mb) 失败时抛异常，记为该档位失败。文件用完即删。
    """
    report = ProbeReport(kind="file")
    for size_mb in sizes_mb:
        size_bytes = int(size_mb) * 1024 * 1024
        path = os.path.join(video_dir, f"probe_{size_mb}mb_{uuid.uuid4().hex[:6]}.bin")
        generate_dummy_file(size_bytes, path)
        try:
            await send_file(path, int(size_mb))
            report.results.append(ProbeResult(size_bytes, ok=True))
        except Exception as exc:  # noqa: BLE001 探测要捕获所有发送失败
            report.results.append(ProbeResult(size_bytes, ok=False, error=str(exc)[:200]))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    return report


def format_report(report: ProbeReport) -> str:
    """把 ProbeReport 格式化成面向用户的文字。"""
    lines = [f"文件通道探测结果（共 {len(report.results)} 档）："]
    for result in report.results:
        size_mb = result.size_bytes / (1024 * 1024)
        mark = "成功" if result.ok else "失败"
        extra = f"（{result.error}）" if result.error else ""
        lines.append(f"  {mark}  {size_mb:g}MB{extra}")
    if report.max_ok_bytes:
        lines.append(f"最大成功大小：{report.max_ok_bytes / (1024 * 1024):g}MB")
    else:
        lines.append("所有档位均失败，该通道可能不支持发文件")
    return "\n".join(lines)
