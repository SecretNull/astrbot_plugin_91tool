"""crawler 纯解析函数测试：source_id、URL 归一、卡片解析、分类识别。"""
from astrbot_plugin_91tool.core import crawler


def test_extract_source_id():
    assert crawler.extract_source_id("https://www.91porn.com/thumb/123456.jpg") == "123456"
    assert crawler.extract_source_id("https://www.91porn.com/other.png") == ""
    assert crawler.extract_source_id("") == ""


def test_abs_detail_url_normalizes_to_www():
    url = crawler._abs_detail_url("//91porn.com/view_video.php?viewkey=abc")
    assert url.startswith("https://www.91porn.com/")
    assert "viewkey=abc" in url


def test_parse_cards_extracts_fields():
    html = """
    <div class="well-sm">
      <a href="view_video.php?viewkey=abc&c=ch"><span class="video-title">标题A</span></a>
      <img class="img-responsive" src="//www.91porn.com/thumb/1024.jpg">
      <div class="duration">12:30</div>
      <span class="hd-text-icon">HD</span>
      <div id="playvthumb_1024"></div>
    </div>
    """
    records = crawler.parse_cards(html)
    assert len(records) == 1
    rec = records[0]
    assert rec.title == "标题A"
    assert rec.duration == "12:30"
    assert rec.hd is True
    assert rec.source_id == "1024"
    assert "viewkey=abc" in rec.link


def test_parse_cards_drops_mismatched_overlay():
    html = """
    <div class="well-sm">
      <a href="view_video.php?viewkey=abc"><span class="video-title">A</span></a>
      <img class="img-responsive" src="//www.91porn.com/thumb/1024.jpg">
      <div class="duration">1:00</div>
      <div id="playvthumb_9999"></div>
    </div>
    """
    assert crawler.parse_cards(html) == []


def test_extract_reported_category():
    html = """
    <div class="well-sm"><a href="v.php?category=rf&page=1">x</a></div>
    <div class="well-sm"><a href="v.php?category=rf&page=2">y</a></div>
    """
    assert crawler.extract_reported_category(html) == "rf"
