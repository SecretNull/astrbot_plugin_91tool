"""91porn 会话 Cookie 的自动保存与恢复。"""

import json
import os
from pathlib import Path

from aiohttp import CookieJar
from yarl import URL


COOKIE_URL = URL("https://www.91porn.com/")


class PersistentCookieJar(CookieJar):
    """将 91porn Cookie 持久化到权限受限的 JSON 文件。"""

    def __init__(self, storage_path: str):
        self.storage_path = Path(storage_path)
        self.load_error = ""
        self.save_error = ""
        self._restoring = True
        super().__init__()
        self._load_from_disk()
        self._restoring = False

    def update_cookies(self, cookies, response_url=URL()):
        """更新 Cookie，并在收到新 Cookie 后立即保存。"""
        super().update_cookies(cookies, response_url)
        if not self._restoring and cookies:
            self._save_to_disk()

    def _load_from_disk(self) -> None:
        """从 JSON 文件恢复目标站点 Cookie。"""
        if not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            cookies = data.get("cookies", {}) if isinstance(data, dict) else {}
            if isinstance(cookies, dict):
                values = {
                    str(name): str(value)
                    for name, value in cookies.items()
                    if name and value is not None
                }
                if values:
                    super().update_cookies(values, COOKIE_URL)
        except (OSError, ValueError, TypeError) as error:
            self.load_error = str(error)

    def _save_to_disk(self) -> None:
        """原子保存目标站点 Cookie，不记录或输出 Cookie 值。"""
        temporary_path = self.storage_path.with_name(
            f".{self.storage_path.name}.{os.getpid()}.tmp"
        )
        try:
            cookies = {
                name: morsel.value
                for name, morsel in self.filter_cookies(COOKIE_URL).items()
            }
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps({"version": 1, "cookies": cookies}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.storage_path)
            self.save_error = ""
        except OSError as error:
            self.save_error = str(error)
            temporary_path.unlink(missing_ok=True)
