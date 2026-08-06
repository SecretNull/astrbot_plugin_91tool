"""Cookie 持久化测试：落盘权限、跨实例恢复、损坏文件容错。

aiohttp 的 CookieJar 需要运行中的事件循环，因此用例都是 async。
"""
import os

from astrbot_plugin_91tool.core.cookie_store import COOKIE_URL, PersistentCookieJar


async def test_persist_and_restore(tmp_path):
    path = tmp_path / "cookies.json"
    jar = PersistentCookieJar(str(path))
    jar.update_cookies({"CLIPSHARE": "token123"}, COOKIE_URL)

    assert path.exists()
    assert os.stat(path).st_mode & 0o777 == 0o600

    restored = PersistentCookieJar(str(path))
    assert not restored.load_error
    cookies = restored.filter_cookies(COOKIE_URL)
    assert cookies["CLIPSHARE"].value == "token123"


async def test_missing_file_is_silent(tmp_path):
    jar = PersistentCookieJar(str(tmp_path / "missing.json"))
    assert not jar.load_error


async def test_corrupt_file_sets_load_error(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text("not-json{", encoding="utf-8")
    jar = PersistentCookieJar(str(path))
    assert jar.load_error
