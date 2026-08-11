"""查询相关配置，从 AstrBot 配置映射读取，带类型容错。"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class QueryConfig:
    """查询服务运行所需的全部配置。"""

    default_category: str = "rf"
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 30.0
    proxy: str | None = None
    cookie_bootstrap_max_refreshes: int = 3
    cookie_bootstrap_delay: float = 3.0
    request_delay_min: float = 1.0
    request_delay_max: float = 1.5
    result_store_max: int = 100
    result_ttl_hours: float = 24.0

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "QueryConfig":
        """从 AstrBot 配置映射构造，非法值回退默认值。"""
        source = mapping or {}

        def pick(key: str, cast, default):
            value = source.get(key, default)
            if value in (None, ""):
                return default
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        proxy_value = pick("proxy", str, "")
        return cls(
            user_agent=pick("91porn_user_agent", str, cls.user_agent),
            timeout=pick("timeout", float, cls.timeout),
            proxy=proxy_value or None,
            cookie_bootstrap_max_refreshes=pick(
                "cookie_bootstrap_max_refreshes", int, cls.cookie_bootstrap_max_refreshes
            ),
            cookie_bootstrap_delay=pick(
                "cookie_bootstrap_delay", float, cls.cookie_bootstrap_delay
            ),
            request_delay_min=pick("request_delay_min", float, cls.request_delay_min),
            request_delay_max=pick("request_delay_max", float, cls.request_delay_max),
            result_store_max=pick("result_store_max", int, cls.result_store_max),
            result_ttl_hours=pick("result_ttl_hours", float, cls.result_ttl_hours),
        )


@dataclass
class VideoConfig:
    """视频下载与媒体缓存的配置。"""

    video_source_max_refreshes: int = 3
    video_source_refresh_delay: float = 3.0
    video_download_timeout: float = 1800.0
    video_cache_retention_hours: float = 24.0
    proxy: str | None = None

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "VideoConfig":
        """从 AstrBot 配置映射构造，非法值回退默认值。"""
        source = mapping or {}

        def pick(key: str, cast, default):
            value = source.get(key, default)
            if value in (None, ""):
                return default
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        return cls(
            video_source_max_refreshes=pick(
                "video_source_max_refreshes", int, cls.video_source_max_refreshes
            ),
            video_source_refresh_delay=pick(
                "video_source_refresh_delay", float, cls.video_source_refresh_delay
            ),
            video_download_timeout=pick(
                "video_download_timeout", float, cls.video_download_timeout
            ),
            video_cache_retention_hours=pick(
                "video_cache_retention_hours", float, cls.video_cache_retention_hours
            ),
            proxy=pick("proxy", str, "") or None,
        )


@dataclass
class PreviewConfig:
    """预览采样的配置。"""

    mosaic_block: int = 15
    preview_generation_timeout: float = 300.0
    preview_gif_width: int = 320
    preview_gif_fps: int = 6

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "PreviewConfig":
        """从 AstrBot 配置映射构造，非法值回退默认值。"""
        source = mapping or {}

        def pick(key: str, cast, default):
            value = source.get(key, default)
            if value in (None, ""):
                return default
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        return cls(
            mosaic_block=pick("mosaic_block", int, cls.mosaic_block),
            preview_generation_timeout=pick(
                "preview_generation_timeout", float, cls.preview_generation_timeout
            ),
            preview_gif_width=pick("preview_gif_width", int, cls.preview_gif_width),
            preview_gif_fps=pick("preview_gif_fps", int, cls.preview_gif_fps),
        )


@dataclass
class RenderConfig:
    """长图渲染的配置。"""

    longimage_width: int = 720
    cover_max_height: int = 380
    mosaic_block: int = 15
    font_regular: str = ""
    proxy: str | None = None

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "RenderConfig":
        """从 AstrBot 配置映射构造，非法值回退默认值。"""
        source = mapping or {}

        def pick(key: str, cast, default):
            value = source.get(key, default)
            if value in (None, ""):
                return default
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        return cls(
            longimage_width=pick("longimage_width", int, cls.longimage_width),
            cover_max_height=pick("cover_max_height", int, cls.cover_max_height),
            mosaic_block=pick("mosaic_block", int, cls.mosaic_block),
            font_regular=pick("font_regular", str, ""),
            proxy=pick("proxy", str, "") or None,
        )


@dataclass
class CompressConfig:
    """原片压缩的配置。"""

    compress_timeout: float = 300.0

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "CompressConfig":
        source = mapping or {}

        def pick(key: str, cast, default):
            value = source.get(key, default)
            if value in (None, ""):
                return default
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        return cls(
            compress_timeout=pick("compress_timeout", float, cls.compress_timeout),
        )


@dataclass
class ArchiveConfig:
    """持久归档(NAS)的配置。"""

    archive_enabled: bool = False
    archive_dir: str = "/archive/91"

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "ArchiveConfig":
        source = mapping or {}

        def pick(key: str, cast, default):
            value = source.get(key, default)
            if value in (None, ""):
                return default
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        def parse_bool(value):
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "1", "yes")

        return cls(
            archive_enabled=pick("archive_enabled", parse_bool, cls.archive_enabled),
            archive_dir=pick("archive_dir", str, cls.archive_dir),
        )
