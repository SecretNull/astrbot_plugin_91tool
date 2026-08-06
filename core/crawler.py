"""91porn 列表页抓取与解析。纯模块，不依赖 astrbot，便于独立测试。"""
import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

from aiohttp import ClientSession
from bs4 import BeautifulSoup
from yarl import URL

BASE_URL = "https://www.91porn.com"
CARD_SEL = ".well-sm"
TITLE_SEL = ".video-title"
IMG_SEL = ".img-responsive"
DURATION_SEL = ".duration"
HD_SEL = ".hd-text-icon"


class CategoryMismatchError(RuntimeError):
    """列表页响应分类与请求分类不一致。"""


class CookieBootstrapError(RuntimeError):
    """首次请求后仍未取得站点访问 Cookie。"""


@dataclass
class VideoRecord:
    """单个视频卡片解析结果。"""
    title: str
    link: str
    image_url: str
    duration: str
    hd: bool
    source_id: str = ""


def build_page_url(category: str, page: int) -> str:
    """构造列表页 URL。viewtype 固定 basic（detailed 未登录为空，已验证）。"""
    return f"{BASE_URL}/v.php?category={category}&viewtype=basic&page={page}"


def _abs_image_url(src: str) -> str:
    """把封面图相对地址补全为绝对 URL。"""
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return BASE_URL + src
    return src


def _abs_detail_url(href: str) -> str:
    """补全详情页地址，并统一到可持久复用 Cookie 的 www 域名。"""
    link = urljoin(BASE_URL + "/", href)
    parsed = urlparse(link)
    if parsed.hostname == "91porn.com":
        parsed = parsed._replace(netloc="www.91porn.com")
    return parsed.geturl()


def extract_source_id(image_url: str) -> str:
    """从列表封面地址提取数字视频源 ID。"""
    path = urlparse(image_url or "").path
    match = re.search(r"/thumb/(\d+)\.[A-Za-z0-9]+$", path)
    return match.group(1) if match else ""


def extract_reported_category(html: str) -> str:
    """从列表卡片或视图链接识别服务端实际返回的分类。"""
    soup = BeautifulSoup(html, "html.parser")
    categories = []
    for link in soup.select(f"{CARD_SEL} a[href*='category=']"):
        category = parse_qs(urlparse(link.get("href", "")).query).get("category", [""])[0]
        if category:
            categories.append(category)
    if categories:
        return Counter(categories).most_common(1)[0][0]
    for link in soup.select(".basicdetailed a[href*='category=']"):
        category = parse_qs(urlparse(link.get("href", "")).query).get("category", [""])[0]
        if category:
            return category
    return ""


def has_access_cookie(session: ClientSession) -> bool:
    """判断会话是否已有控制正确列表响应的 CLIPSHARE Cookie。"""
    cookie_jar = getattr(session, "cookie_jar", None)
    if cookie_jar is None:
        return False
    return "CLIPSHARE" in cookie_jar.filter_cookies(URL(BASE_URL + "/"))


def parse_cards(html: str) -> list[VideoRecord]:
    """从列表页 HTML 解析全部视频卡片。"""
    soup = BeautifulSoup(html, "html.parser")
    records: list[VideoRecord] = []
    for card in soup.select(CARD_SEL):
        title_el = card.select_one(TITLE_SEL)
        title = title_el.get_text(strip=True) if title_el else "无标题"

        link_el = card.find("a")
        link = ""
        if link_el and link_el.get("href"):
            link = _abs_detail_url(link_el["href"])

        img_el = card.select_one(IMG_SEL)
        image_url = _abs_image_url(img_el["src"]) if img_el and img_el.get("src") else ""
        overlay = card.select_one("[id^='playvthumb_']")
        overlay_source_id = ""
        if overlay:
            match = re.fullmatch(r"playvthumb_(\d+)", overlay.get("id", ""))
            if match:
                overlay_source_id = match.group(1)
        image_source_id = extract_source_id(image_url)
        if (
            overlay_source_id
            and image_source_id
            and overlay_source_id != image_source_id
        ):
            continue
        source_id = overlay_source_id or image_source_id

        dur_el = card.select_one(DURATION_SEL)
        duration = dur_el.get_text(strip=True) if dur_el else ""

        hd = bool(card.select_one(HD_SEL))

        if image_url:
            records.append(VideoRecord(title, link, image_url, duration, hd, source_id))

    channel_tokens = [
        parse_qs(urlparse(record.link).query).get("c", [""])[0]
        for record in records
    ]
    token_counts = Counter(token for token in channel_tokens if token)
    if len(token_counts) > 1:
        ranked_tokens = token_counts.most_common()
        if ranked_tokens[0][1] > ranked_tokens[1][1]:
            dominant_token = ranked_tokens[0][0]
            records = [
                record
                for record, token in zip(records, channel_tokens)
                if not token or token == dominant_token
            ]
    return records


async def fetch_page(session: ClientSession, category: str, page: int,
                     timeout: float = 20.0, proxy: str = None,
                     max_category_refreshes: int = 3,
                     category_refresh_delay: float = 3.0) -> list[VideoRecord]:
    """抓取分类页，并拒绝站点首次匿名会话返回的错误分类。"""
    if max_category_refreshes < 0:
        raise ValueError("max_category_refreshes 不能小于 0")
    if category_refresh_delay < 0:
        raise ValueError("category_refresh_delay 不能小于 0")
    url = build_page_url(category, page)
    last_reported_category = "无法识别"
    for refreshes in range(max_category_refreshes + 1):
        request_has_cookie = has_access_cookie(session)
        async with session.get(url, timeout=timeout, proxy=proxy) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()
        reported_category = extract_reported_category(html)
        if reported_category == category and request_has_cookie:
            return parse_cards(html)
        last_reported_category = reported_category or "无法识别"
        if refreshes < max_category_refreshes:
            await asyncio.sleep(category_refresh_delay)
    if last_reported_category == category:
        raise CookieBootstrapError(
            f"刷新分类页 {max_category_refreshes} 次后仍未使用 CLIPSHARE Cookie"
        )
    raise CategoryMismatchError(
        f"刷新分类页 {max_category_refreshes} 次后响应分类仍不匹配："
        f"期望 {category}，最后实际 {last_reported_category}"
    )


async def fetch_search_page(session: ClientSession, keyword: str, page: int,
                            timeout: float = 20.0, proxy: str = None,
                            max_cookie_refreshes: int = 3,
                            cookie_refresh_delay: float = 3.0) -> list[VideoRecord]:
    """抓取搜索结果；首次无 Cookie 响应仅用于建立会话。"""
    if max_cookie_refreshes < 0:
        raise ValueError("max_cookie_refreshes 不能小于 0")
    if cookie_refresh_delay < 0:
        raise ValueError("cookie_refresh_delay 不能小于 0")
    params = {"search_id": keyword, "page": str(page)}
    for refreshes in range(max_cookie_refreshes + 1):
        request_has_cookie = has_access_cookie(session)
        async with session.get(f"{BASE_URL}/search_result.php", params=params,
                               timeout=timeout, proxy=proxy) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()
        if request_has_cookie:
            return parse_cards(html)
        if refreshes < max_cookie_refreshes:
            await asyncio.sleep(cookie_refresh_delay)
    raise CookieBootstrapError(
        f"刷新搜索页 {max_cookie_refreshes} 次后仍未使用 CLIPSHARE Cookie"
    )


async def download_image(session: ClientSession, url: str, save_path: str,
                         timeout: float = 20.0, proxy: str = None) -> bool:
    """下载图片到 save_path（原尺寸，不缩放不打码）。成功返回 True。"""
    headers = {"Referer": BASE_URL + "/"}
    async with session.get(url, timeout=timeout, proxy=proxy, headers=headers) as resp:
        if resp.status != 200:
            return False
        data = await resp.read()
    with open(save_path, "wb") as f:
        f.write(data)
    return True
