"""AstrBot 插件入口：注册 LLM Tool 与管理命令，装配 core 服务。

阶段 1-3：91tool_query、91tool_video_info（纯本地）、91tool_prepare_video（进详情页）。
"""
from __future__ import annotations

import json
import os
from typing import Optional

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .core.config import QueryConfig, VideoConfig
from .core.cookie_store import PersistentCookieJar
from .core.list_fetcher import HttpListFetcher
from .core.media_cache import MediaCache
from .core.query_service import QueryService
from .core.result_store import ResultStore
from .core.video_registry import VideoRegistry
from .core.video_service import VideoService
from .tools import prepare_video as prepare_video_tool
from .tools import query as query_tool
from .tools import video_info as video_info_tool


class PluginStar(Star):
    """astrbot_plugin_91tool 的 Star 入口。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        data_dir = StarTools.get_data_dir("astrbot_plugin_91tool")
        self.cookie_path = os.path.join(str(data_dir), "cookies.json")
        self.video_dir = os.path.join(str(data_dir), "videos")
        os.makedirs(self.video_dir, exist_ok=True)
        self.query_config = QueryConfig.from_mapping(config)
        self.video_config = VideoConfig.from_mapping(config)
        ttl_seconds = self.query_config.result_ttl_hours * 3600
        self.store = ResultStore(
            max_results=self.query_config.result_store_max,
            ttl_seconds=ttl_seconds,
        )
        self.registry = VideoRegistry(max_entries=500, ttl_seconds=ttl_seconds)
        self.media_cache = MediaCache(
            self.video_dir, self.video_config.video_cache_retention_hours
        )
        self.http_client: Optional[aiohttp.ClientSession] = None
        self.query_service: Optional[QueryService] = None
        self.video_service: Optional[VideoService] = None

    async def initialize(self) -> None:
        """初始化 HTTP 客户端与各服务。"""
        timeout = aiohttp.ClientTimeout(total=self.query_config.timeout)
        headers = {
            "User-Agent": self.query_config.user_agent,
            "Accept": "text/html,application/xhtml+xml,image/*;q=0.8,*/*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://91porn.com/",
        }
        cookie_jar = PersistentCookieJar(self.cookie_path)
        if cookie_jar.load_error:
            logger.warning("91porn Cookie 恢复失败，将创建新会话")
        self.http_client = aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
            cookie_jar=cookie_jar,
        )
        fetcher = HttpListFetcher(self.http_client, self.query_config)
        self.query_service = QueryService(
            fetcher, self.query_config, self.store, self.registry
        )
        self.video_service = VideoService(
            self.http_client,
            self.media_cache,
            self.query_service,
            self.video_config,
            self.video_dir,
        )
        logger.info("astrbot_plugin_91tool 初始化完成")

    async def terminate(self) -> None:
        """关闭 HTTP 客户端。"""
        if self.http_client:
            await self.http_client.close()
        logger.info("astrbot_plugin_91tool 已关闭")

    @filter.llm_tool(name="91tool_query")
    async def query_videos(
        self,
        event: AstrMessageEvent,
        category: str = "",
        keyword: str = "",
        page: int = 1,
        page_size: int = 0,
        min_duration: float = 0,
        max_duration: float = 0,
        hd: str = "",
        result_id: str = "",
    ):
        """按分类或关键词查询 91 视频，返回带 result_id 的结构化列表。

        Args:
            category(string): 分类代码 rf/hot/top/ori/tf/mf/md/hd/long/longer，留空用默认分类
            keyword(string): 搜索关键词，非空时按搜索结果返回
            page(number): 页码，从 1 开始
            page_size(number): 最多返回条目数，0 表示不限
            min_duration(number): 最小时长(秒)，0 表示不限
            max_duration(number): 最大时长(秒)，0 表示不限
            hd(string): HD 过滤，留空不限，"true" 仅 HD，"false" 仅非 HD
            result_id(string): 复用已有结果时传入其 result_id
        """
        raw = {
            "category": category, "keyword": keyword, "page": page,
            "page_size": page_size, "min_duration": min_duration,
            "max_duration": max_duration, "hd": hd, "result_id": result_id,
        }
        try:
            output = await query_tool.run_query(self.query_service, raw)
        except (ValueError, RuntimeError) as exc:
            return f"查询失败：{exc}"
        return json.dumps(output, ensure_ascii=False)

    @filter.llm_tool(name="91tool_video_info")
    async def video_info(
        self,
        event: AstrMessageEvent,
        video_id: str = "",
        result_id: str = "",
        index: int = 0,
    ):
        """查看单个视频的文字详情（不下载、不进详情页）。

        Args:
            video_id(string): 视频 ID，优先使用
            result_id(string): 配合 index 使用，来自 91tool_query 返回
            index(number): 在 result_id 结果中的 1-based 序号
        """
        raw = {"video_id": video_id, "result_id": result_id, "index": index}
        try:
            output = await video_info_tool.run_video_info(self.query_service, raw)
        except ValueError as exc:
            return f"参数错误：{exc}"
        return json.dumps(output, ensure_ascii=False)

    @filter.llm_tool(name="91tool_prepare_video")
    async def prepare_video(
        self,
        event: AstrMessageEvent,
        video_id: str = "",
        result_id: str = "",
        index: int = 0,
    ):
        """可信校验下载原视频到本地缓存，返回路径与校验信息（不发送）。

        Args:
            video_id(string): 视频 ID，优先使用
            result_id(string): 配合 index 使用
            index(number): 在 result_id 结果中的 1-based 序号
        """
        raw = {"video_id": video_id, "result_id": result_id, "index": index}
        try:
            output = await prepare_video_tool.run_prepare_video(self.video_service, raw)
        except (ValueError, RuntimeError) as exc:
            return f"准备失败：{exc}"
        return json.dumps(output, ensure_ascii=False)
