"""用 aiohttp 会话抓取列表/搜索页的适配器，供 QueryService 注入。"""
from __future__ import annotations

import asyncio
import random

from . import crawler
from .config import QueryConfig
from .crawler import VideoRecord


class HttpListFetcher:
    """调用 crawler 抓页，首次抓取前按配置加入随机延迟。"""

    def __init__(self, session, config: QueryConfig):
        self.session = session
        self.config = config

    async def fetch(
        self, category: str, keyword: str, page: int, *, first: bool = False
    ) -> list[VideoRecord]:
        """抓取一页；keyword 非空走搜索，否则走分类。first 时先随机等待。"""
        if first:
            delay_min = max(0.0, float(self.config.request_delay_min))
            delay_max = max(delay_min, float(self.config.request_delay_max))
            if delay_max > 0:
                await asyncio.sleep(random.uniform(delay_min, delay_max))
        timeout = float(self.config.timeout)
        proxy = self.config.proxy or None
        if keyword:
            return await crawler.fetch_search_page(
                self.session,
                keyword,
                page,
                timeout,
                proxy,
                self.config.cookie_bootstrap_max_refreshes,
                self.config.cookie_bootstrap_delay,
            )
        return await crawler.fetch_page(
            self.session,
            category,
            page,
            timeout,
            proxy,
            self.config.cookie_bootstrap_max_refreshes,
            self.config.cookie_bootstrap_delay,
        )
