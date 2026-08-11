"""归档服务：把原片/无码预览/封面持久化到 archive_dir(NAS)，按 日期/标题_video_id/ 组织。

archive_dir 不被 cleanup 扫描，归档内容永久保留。
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import VideoItem

# 文件名非法字符(Windows/Linux 通用)
_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


class ArchiveService:
    """按 video_id 归档原片/封面/无码预览到 archive_dir。"""

    def __init__(
        self,
        http_client,
        archive_dir: str,
        enabled: bool,
        now: Callable[[], float] | None = None,
    ):
        self.http_client = http_client
        self.archive_dir = archive_dir
        self.enabled = enabled
        self._now = now or time.time

    @staticmethod
    def _sanitize_title(title: str) -> str:
        """清洗标题为合法文件/文件夹名：非法字符→_，截断 80，空→untitled。"""
        cleaned = _ILLEGAL.sub("_", title or "").strip().strip(".")
        if len(cleaned) > 80:
            cleaned = cleaned[:80].strip().strip(".")
        return cleaned or "untitled"

    def _archive_folder(self, item: VideoItem) -> Path:
        """定位/创建归档目录：优先复用同 video_id 已有目录，否则建当天。"""
        root = Path(self.archive_dir)
        if root.exists():
            for path in root.rglob(f"*_{item.video_id}"):
                if path.is_dir():
                    return path
        date = datetime.fromtimestamp(self._now()).strftime("%Y-%m-%d")
        folder = root / date / f"{self._sanitize_title(item.title)}_{item.video_id}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    async def archive_original(self, item: VideoItem, src_path: str) -> str | None:
        """归档原片 + 封面 + meta；未启用返回 None。"""
        if not self.enabled:
            return None
        folder = self._archive_folder(item)
        dest = folder / f"{self._sanitize_title(item.title)}.mp4"
        await asyncio.to_thread(shutil.copyfile, src_path, str(dest))
        await self._download_cover(item.cover_url, folder / "cover.jpg")
        self._write_meta(item, folder)
        return str(folder)

    async def archive_preview(
        self, item: VideoItem, src_path: str, asset_name: str
    ) -> str | None:
        """归档无码预览(preview_clean/gif_clean)；打码与未启用返回 None。"""
        if not self.enabled or asset_name not in ("preview_clean", "gif_clean"):
            return None
        folder = self._archive_folder(item)
        title = self._sanitize_title(item.title)
        if asset_name == "preview_clean":
            dest = folder / f"{title}_preview.mp4"
        else:
            dest = folder / f"{title}.gif"
        await asyncio.to_thread(shutil.copyfile, src_path, str(dest))
        self._write_meta(item, folder)
        return str(folder)

    async def _download_cover(self, url: str, dest: Path) -> None:
        """下载封面到 dest；失败静默(归档不因封面失败而中断)。"""
        if not url:
            return
        try:
            async with self.http_client.get(
                url, headers={"Referer": "https://91porn.com/"}
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.read()
        except Exception:
            return
        await asyncio.to_thread(self._write_bytes, str(dest), data)

    @staticmethod
    def _write_bytes(path: str, data: bytes) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def _write_meta(self, item: VideoItem, folder: Path) -> None:
        """写 meta.json，记录能记的所有字段。"""
        meta = {
            "video_id": item.video_id,
            "title": item.title,
            "duration_text": item.duration_text,
            "duration_sec": item.duration_sec,
            "hd": item.hd,
            "category": item.category,
            "page_url": item.page_url,
            "viewkey": item.viewkey,
            "source_id": item.source_id,
            "cover_url": item.cover_url,
            "archive_date": datetime.fromtimestamp(self._now()).strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(folder / "meta.json", "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, indent=2)
