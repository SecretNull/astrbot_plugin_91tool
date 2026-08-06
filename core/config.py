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
            default_category=pick("91porn_category", str, cls.default_category),
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
