"""AstrBot 插件入口：注册 LLM Tool 与管理命令，装配 core 服务。

阶段 1-7 完整：
  query / video_info / prepare_video / prepare_preview / render_list /
  send_media(唯一发包，经 on_agent_done) / cache_status
管理命令：/91probe 探测、/91tool_status 状态、/91tool_clear 清理、/91tool_help 帮助。
后台清理循环定期回收过期 result / video_id / 媒体。
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from typing import Optional

import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools

from .core.config import CompressConfig, PreviewConfig, QueryConfig, RenderConfig, VideoConfig
from .core.compress_service import CompressService
from .core.cookie_store import PersistentCookieJar
from .core.list_fetcher import HttpListFetcher
from .core.media_cache import MediaCache
from .core.media_sender import SendConfig
from .core.preview_service import PreviewService
from .core.probe import ProbeConfig, format_reports, probe_channel
from .core.query_service import QueryService
from .core.render_service import RenderService
from .core.result_store import ResultStore
from .core.send_service import SendService
from .core.video_registry import VideoRegistry
from .core.video_service import VideoService
from .tools import cache_status as cache_status_tool
from .tools import prepare_preview as prepare_preview_tool
from .tools import prepare_video as prepare_video_tool
from .tools import query as query_tool
from .tools import render_list as render_list_tool
from .tools import send_media as send_media_tool
from .tools import video_info as video_info_tool

LLM_TOOL_MEDIA_EXTRA = "astrbot_plugin_91tool.llm_tool_media"


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
        self.preview_config = PreviewConfig.from_mapping(config)
        self.render_config = RenderConfig.from_mapping(config)
        self.send_config = SendConfig.from_mapping(config)
        self.probe_config = ProbeConfig.from_mapping(config)
        self.compress_config = CompressConfig.from_mapping(config)
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
        self.preview_service: Optional[PreviewService] = None
        self.render_service: Optional[RenderService] = None
        self.send_service: Optional[SendService] = None
        self.compress_service: Optional[CompressService] = None
        self.cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """初始化 HTTP 客户端、各服务与后台清理循环。"""
        timeout = aiohttp.ClientTimeout(total=self.query_config.timeout)
        headers = {
            "User-Agent": self.query_config.user_agent,
            "Accept": "text/html,application/xhtml+xml,image/*;q=0.8,*/*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://91porn.com/",
        }
        cookie_jar = PersistentCookieJar(self.cookie_path)
        if cookie_jar.load_error:
            logger.warning("Cookie 恢复失败，将创建新会话")
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
            self.http_client, self.media_cache, self.query_service,
            self.video_config, self.video_dir,
        )
        self.preview_service = PreviewService(
            self.query_service, self.video_service, self.media_cache,
            self.preview_config, self.video_dir,
        )
        self.render_service = RenderService(
            self.query_service, self.http_client, self.render_config, self.video_dir
        )
        self.compress_service = CompressService(
            self.media_cache, self.video_dir, self.compress_config.compress_timeout
        )
        self.send_service = SendService(
            self.media_cache, self.send_config, self.compress_service
        )
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("astrbot_plugin_91tool 初始化完成")

    async def terminate(self) -> None:
        """停止清理循环并关闭 HTTP 客户端。"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.cleanup_task
            self.cleanup_task = None
        if self.http_client:
            await self.http_client.close()
        logger.info("astrbot_plugin_91tool 已关闭")

    async def _cleanup_loop(self) -> None:
        """每小时清理过期的查询结果、视频索引与媒体缓存。"""
        while True:
            await asyncio.sleep(3600)
            try:
                self.store.evict_expired()
                self.registry.evict_expired()
                removed = self.media_cache.cleanup_expired()
                if removed:
                    logger.info("已清理 %d 个过期媒体文件", removed)
            except Exception as exc:  # noqa: BLE001 后台任务不能因单次失败退出
                logger.warning("清理循环出错：%s", exc)

    def _build_media_components(self, plan: dict) -> list:
        """按决策把待发文件构造成 astrbot 消息组件。"""
        path = plan["path"]
        if plan["kind"] == "image":
            return [Comp.Image.fromFileSystem(path)]
        if plan["as_file"]:
            return [Comp.File(file=path, name=os.path.basename(path))]
        return [Comp.Video.fromFileSystem(path=path)]

    @filter.on_agent_done()
    async def emit_pending_media(self, event: AstrMessageEvent, *args, **kwargs):
        """agent 结束时把 llm_tool 暂存的媒体作为最终回复发出。

        astrbot 不同版本给 on_agent_done 传参个数不同，这里按 result_chain
        属性定位 response，兼容多参数。
        """
        pending = event.get_extra(LLM_TOOL_MEDIA_EXTRA) or []
        if not pending:
            return
        event.set_extra(LLM_TOOL_MEDIA_EXTRA, [])
        response = next((arg for arg in args if hasattr(arg, "result_chain")), None)
        if response is None:
            return
        response.result_chain = MessageChain(chain=pending, type="llm_result")

    # ---- LLM Tools ----

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
        """按分类或关键词查询视频，返回带 result_id 的结构化列表。

        用户说"数字站"或"91"都指本数据源（如"数字站热门"/"91热门"均查 hot 分类）。
        回复用户时一律用"数字站"指代，不要出现数字 91、完整站点地址或工具内部名。

        列表展示首选：拿到结果后用 list_image 一步发长图，或 render_list + send_media。
        不要逐条文字罗列给用户。只有用户明确要"具体链接/某条详情"时才用文字或 video_info。

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
        self, event: AstrMessageEvent,
        video_id: str = "", result_id: str = "", index: int = 0,
    ):
        """查看单个视频的文字详情（不下载、不进详情页）。

        Args:
            video_id(string): 视频 ID，优先使用
            result_id(string): 配合 index 使用，来自 query 返回
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
        self, event: AstrMessageEvent,
        video_id: str = "", result_id: str = "", index: int = 0,
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

    @filter.llm_tool(name="91tool_prepare_preview")
    async def prepare_preview(
        self, event: AstrMessageEvent,
        video_id: str = "", result_id: str = "", index: int = 0,
        format: str = "mp4", mosaic: str = "",
    ):
        """基于原视频生成 MP4 或 GIF 预览并缓存，返回路径（不发送）。

        Args:
            video_id(string): 视频 ID，优先使用
            result_id(string): 配合 index 使用
            index(number): 在 result_id 结果中的 1-based 序号
            format(string): mp4 或 gif，默认 mp4
            mosaic(string): 是否打码，"true" 打码，留空不打码
        """
        raw = {
            "video_id": video_id, "result_id": result_id, "index": index,
            "format": format, "mosaic": mosaic,
        }
        try:
            output = await prepare_preview_tool.run_prepare_preview(
                self.preview_service, raw
            )
        except (ValueError, RuntimeError) as exc:
            return f"预览失败：{exc}"
        return json.dumps(output, ensure_ascii=False)

    @filter.llm_tool(name="91tool_render_list")
    async def render_list(
        self, event: AstrMessageEvent,
        result_id: str = "", indices: str = "", video_ids: str = "", mosaic: str = "",
    ):
        """把查询结果或选定条目渲染成单列长图——列表发给用户的主要形式。

        渲染后用 send_media(path=image_path) 发出。列表浏览也可直接用 list_image 一步完成。

        Args:
            result_id(string): 来自 query 的结果 ID
            indices(string): 要渲染的 1-based 序号，逗号分隔如 "1,3,5"；留空渲染全部
            video_ids(string): 直接按 video_id 渲染，逗号分隔
            mosaic(string): "true" 打码，"false" 无和谐，留空用默认(打码)
        """
        raw = {
            "result_id": result_id, "indices": indices,
            "video_ids": video_ids, "mosaic": mosaic,
        }
        try:
            output = await render_list_tool.run_render_list(self.render_service, raw)
        except (ValueError, RuntimeError) as exc:
            return f"渲染失败：{exc}"
        return json.dumps(output, ensure_ascii=False)

    @filter.llm_tool(name="91tool_list_image")
    async def list_image(
        self,
        event: AstrMessageEvent,
        category: str = "",
        keyword: str = "",
        page: int = 1,
        min_duration: float = 0,
        max_duration: float = 0,
        hd: str = "",
        mosaic: str = "",
    ):
        """浏览分类/搜索，一步查询+渲染长图+发送(列表展示的首选方式)。

        用户说"数字站"或"91"都指本数据源（如"看数字站热门"/"91热门"均调用本工具查 hot）。
        回复用户时一律用"数字站"指代，不要出现数字 91、完整站点地址或工具内部名。

        渲染整页全部条目(通常 20~30 条，长图一般 <2MB)。除非用户明确要"具体链接/某条详情"，
        列表浏览都用本工具发长图，不要文字罗列。返回 result_id 供后续 video_info/prepare。

        Args:
            category(string): 分类代码 rf/hot/top/ori/tf/mf/md/hd/long/longer
            keyword(string): 搜索关键词，非空时按搜索结果
            page(number): 页码，从 1 开始
            min_duration(number): 最小时长(秒)，0 不限
            max_duration(number): 最大时长(秒)，0 不限
            hd(string): HD 过滤，留空不限，"true" 仅 HD，"false" 仅非 HD
            mosaic(string): 长图打码，"true"(默认)打码，"false" 无和谐
        """
        query_raw = {
            "category": category, "keyword": keyword, "page": page,
            "min_duration": min_duration,
            "max_duration": max_duration, "hd": hd,
        }
        try:
            query_out = await query_tool.run_query(self.query_service, query_raw)
        except (ValueError, RuntimeError) as exc:
            return f"查询失败：{exc}"
        if not query_out["items"]:
            return "没有匹配的结果"

        render_out = await render_list_tool.run_render_list(
            self.render_service,
            {"result_id": query_out["result_id"], "mosaic": mosaic or "true"},
        )
        if not render_out.get("ready"):
            return f"长图渲染失败：{render_out.get('error')}"

        image_size = os.path.getsize(render_out["image_path"])
        if image_size > self.send_config.image_max_bytes:
            return (
                f"长图 {image_size} 字节超过发送上限 {self.send_config.image_max_bytes}，"
                "请减少 page_size 后重试"
            )

        components = [Comp.Image.fromFileSystem(render_out["image_path"])]
        pending = event.get_extra(LLM_TOOL_MEDIA_EXTRA) or []
        pending.extend(components)
        event.set_extra(LLM_TOOL_MEDIA_EXTRA, pending)
        size_mb = image_size / (1024 * 1024)
        return (
            f"已加入待发长图({render_out['item_count']} 条，{size_mb:g}MB，agent 结束后发出)。"
            f"result_id={query_out['result_id']}；用户要某条详情/链接时用 video_info。"
        )

    @filter.llm_tool(name="91tool_send_media")
    async def send_media(
        self, event: AstrMessageEvent,
        video_id: str = "", asset: str = "", path: str = "",
        uncensored: str = "", as_file: str = "",
    ):
        """发送已准备的媒体到当前会话。

        默认只发打码版；用户明确要无和谐时传 uncensored=true。视频默认视频消息，
        as_file=true 时以文件形式发（文件通道，部分平台不支持）。

        Args:
            video_id(string): 视频 ID，配合 asset 定位产物
            asset(string): 产物名 original/preview_clean/preview_mosaic/gif_clean/gif_mosaic
            path(string): 直接指定文件路径，如 render_list 返回的 image_path
            uncensored(string): "true" 发无码（用户明确要求时），留空走默认打码
            as_file(string): "true" 视频以文件形式发，留空用视频消息
        """
        raw = {
            "video_id": video_id, "asset": asset, "path": path,
            "uncensored": uncensored, "as_file": as_file,
        }
        plan = await send_media_tool.run_send_media(self.send_service, raw)
        if plan["action"] == "reject":
            return f"未发送：{plan['reason']}"
        components = self._build_media_components(plan)
        pending = event.get_extra(LLM_TOOL_MEDIA_EXTRA) or []
        pending.extend(components)
        event.set_extra(LLM_TOOL_MEDIA_EXTRA, pending)
        size_mb = plan["size_bytes"] / (1024 * 1024)
        return f"已加入待发：{plan['asset']}（{plan['kind']}，{size_mb:g}MB，agent 结束后发出）"

    @filter.llm_tool(name="91tool_cache_status")
    async def cache_status(self, event: AstrMessageEvent):
        """查看查询结果、视频索引、媒体缓存的概况。"""
        output = cache_status_tool.run_cache_status(
            self.store, self.registry, self.media_cache
        )
        return json.dumps(output, ensure_ascii=False)

    # ---- 管理命令 ----

    def _probe_sender(self, event: AstrMessageEvent, kind: str):
        """构造指定通道的发送协程（image=Comp.Image / video=Comp.Video / file=Comp.File）。"""
        umo = event.unified_msg_origin

        if kind == "image":
            async def send(path: str, size_mb: int):
                chain = MessageChain(chain=[Comp.Image.fromFileSystem(path)])
                await self.context.send_message(umo, chain)
        elif kind == "video":
            async def send(path: str, size_mb: int):
                chain = MessageChain(chain=[Comp.Video.fromFileSystem(path=path)])
                await self.context.send_message(umo, chain)
        else:
            async def send(path: str, size_mb: int):
                chain = MessageChain(
                    chain=[Comp.File(file=path, name=os.path.basename(path))]
                )
                await self.context.send_message(umo, chain)
        return send

    @filter.command("91probe", alias={"探测"})
    async def probe_command(self, event: AstrMessageEvent):
        """探测当前会话的媒体发送通道与大小上限。

        用法：/91probe [image|video|file|all]，默认 all。
        会向当前会话发出若干测试文件，最后汇总各通道上限。
        """
        text = event.get_message_str() if hasattr(event, "get_message_str") else ""
        tokens = (text or "").lower().split()
        kind = next((t for t in tokens if t in ("image", "video", "file", "all")), "all")
        kinds = [kind] if kind != "all" else ["image", "video", "file"]

        reports = []
        for channel_kind in kinds:
            send = self._probe_sender(event, channel_kind)
            report = await probe_channel(
                channel_kind, send, self.video_dir, self.probe_config.sizes_mb
            )
            reports.append(report)
        yield event.plain_result(format_reports(reports))

    @filter.command("91tool_status", alias={"91状态"})
    async def status_command(self, event: AstrMessageEvent):
        """查看缓存概况。"""
        status = cache_status_tool.run_cache_status(
            self.store, self.registry, self.media_cache
        )
        size_mb = status["total_size_bytes"] / (1024 * 1024)
        text = (
            f"查询结果：{status['results']} 条\n"
            f"视频索引：{status['video_ids']} 个\n"
            f"媒体缓存包：{status['media_bundles']} 个\n"
            f"媒体总占用：{size_mb:g}MB"
        )
        yield event.plain_result(text)

    @filter.command("91tool_clear", alias={"91清理"})
    async def clear_command(self, event: AstrMessageEvent):
        """清理过期的查询结果、视频索引与媒体缓存。"""
        self.store.evict_expired()
        self.registry.evict_expired()
        removed = self.media_cache.cleanup_expired()
        yield event.plain_result(f"已清理过期缓存，媒体文件 {removed} 个")

    @filter.command("91tool_help", alias={"91帮助"})
    async def help_command(self, event: AstrMessageEvent):
        """查看可用命令与 AI 工具。"""
        text = (
            "本插件管理命令：\n"
            "  /91probe [image|video|file]  探测发送通道与上限\n"
            "  /91tool_status               查看缓存概况\n"
            "  /91tool_clear                清理过期缓存\n"
            "  /91tool_help                 显示本帮助\n\n"
            "AI 工具：query / video_info / prepare_video / "
            "prepare_preview / render_list / send_media / cache_status"
        )
        yield event.plain_result(text)
