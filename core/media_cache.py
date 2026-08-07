"""按 video_id 管理原视频与衍生产物(预览/GIF)的共享缓存包。"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ASSET_ORIGINAL = "original"
ASSET_PREVIEW_CLEAN = "preview_clean"
ASSET_PREVIEW_MOSAIC = "preview_mosaic"
ASSET_GIF_CLEAN = "gif_clean"
ASSET_GIF_MOSAIC = "gif_mosaic"
ASSET_ORIGINAL_COMPRESSED = "original_compressed"


@dataclass
class MediaBundle:
    """单个视频的原片及全部衍生产物。"""

    video_id: str
    assets: dict[str, str] = field(default_factory=dict)


class MediaCache:
    """按 video_id 索引的媒体缓存，原片/预览/GIF 共享同一 bundle。

    与旧项目按 unified_msg_origin 隔离不同，这里直接用稳定 video_id 作 key，
    同一视频的原片与衍生产物自然落到同一个 bundle。
    """

    def __init__(
        self,
        video_dir: str,
        retention_hours: float = 24.0,
        now: Callable[[], float] | None = None,
    ):
        if retention_hours <= 0:
            raise ValueError("retention_hours 必须大于 0")
        self.video_dir = Path(video_dir)
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = retention_hours * 3600
        self._now = now or time.time
        self._bundles: dict[str, MediaBundle] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock_for(self, video_id: str) -> asyncio.Lock:
        """取得指定视频的媒体操作锁，防并发重复下载/生成。"""
        lock = self._locks.get(video_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[video_id] = lock
        return lock

    def get_asset(self, video_id: str, asset_name: str) -> str | None:
        """取得缓存产物并刷新 bundle 保留时间；文件丢失则清理条目。"""
        bundle = self._bundles.get(video_id)
        if bundle is None:
            return None
        path = bundle.assets.get(asset_name)
        if not path or not Path(path).is_file():
            bundle.assets.pop(asset_name, None)
            return None
        self._touch(bundle)
        return path

    def has(self, video_id: str, asset_name: str) -> bool:
        """是否存在指定产物。"""
        return self.get_asset(video_id, asset_name) is not None

    def replace(self, video_id: str, assets: dict[str, str]) -> None:
        """整包替换：登记新产物并删除该 video_id 的旧产物文件。"""
        new_bundle = MediaBundle(video_id, dict(assets))
        old = self._bundles.get(video_id)
        self._bundles[video_id] = new_bundle
        self._touch(new_bundle)
        if old:
            self._delete_paths(
                path for path in old.assets.values() if path not in new_bundle.assets.values()
            )

    def add_assets(self, video_id: str, assets: dict[str, str]) -> None:
        """向已有 bundle 追加衍生产物。"""
        bundle = self._bundles.get(video_id)
        if bundle is None:
            raise ValueError(f"video_id {video_id} 尚无缓存包，无法追加产物")
        replaced = {
            bundle.assets[name]
            for name in assets
            if name in bundle.assets and bundle.assets[name] != assets[name]
        }
        bundle.assets.update(assets)
        self._touch(bundle)
        self._delete_paths(path for path in replaced if path not in bundle.assets.values())

    def cleanup_expired(self) -> int:
        """按 bundle 内最新 mtime 清理过期产物与孤儿文件，返回删除文件数。"""
        cutoff = self._now() - self.retention_seconds
        removed: set[str] = set()
        retained: set[str] = set()
        expired: list[str] = []
        for video_id, bundle in self._bundles.items():
            paths = {Path(p) for p in bundle.assets.values() if Path(p).is_file()}
            if not paths:
                expired.append(video_id)
                continue
            latest_mtime = max(path.stat().st_mtime for path in paths)
            if latest_mtime < cutoff:
                removed.update(str(path) for path in paths)
                self._delete_paths(str(path) for path in paths)
                expired.append(video_id)
            else:
                retained.update(str(path) for path in paths)
        for video_id in expired:
            self._bundles.pop(video_id, None)

        for pattern in ("*.mp4", "*.gif", "*.jpg"):
            for path in self.video_dir.glob(pattern):
                path_value = str(path)
                if path_value in retained or path_value in removed:
                    continue
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                        removed.add(path_value)
                except OSError:
                    continue
        return len(removed)

    def status(self) -> dict:
        """返回缓存概况，供 cache_status tool 使用。"""
        total_size = 0
        for bundle in self._bundles.values():
            for path in bundle.assets.values():
                try:
                    total_size += Path(path).stat().st_size
                except OSError:
                    continue
        return {"bundles": len(self._bundles), "total_size_bytes": total_size}

    def clear(self) -> None:
        """清空内存索引（不删磁盘文件）。"""
        self._bundles.clear()
        self._locks.clear()

    def _touch(self, bundle: MediaBundle) -> None:
        """用注入时钟刷新 bundle 内全部现存文件的修改时间。"""
        timestamp = self._now()
        for path_value in set(bundle.assets.values()):
            try:
                os.utime(path_value, (timestamp, timestamp))
            except OSError:
                continue

    @staticmethod
    def _delete_paths(paths) -> None:
        """删除一组缓存文件。"""
        for path_value in set(paths):
            try:
                Path(path_value).unlink(missing_ok=True)
            except OSError:
                continue
