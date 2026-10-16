import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def load_env(path=".env"):
    if not Path(path).is_file():
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.replace("_", "").isalnum():
            raise ValueError("Некорректный формат .env")
        os.environ.setdefault(key, value.strip().strip("\"'"))


@dataclass(frozen=True)
class Config:
    token: str
    owner_id: int
    app_url: str
    database: str
    auth_ttl: int = 86400

    @classmethod
    def from_env(cls):
        load_env(os.environ.get("ENV_FILE", ".env"))
        development = os.environ.get("DEVELOPMENT") == "1"
        token = os.environ.get("BOT_TOKEN", "").strip()
        owner = int(os.environ.get("OWNER_ID") or "0")
        url = os.environ.get("APP_URL", "").rstrip("/")
        parsed = urlparse(url)
        if not development and (not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{30,}", token) or owner <= 0
                                or parsed.scheme != "https" or not parsed.hostname or parsed.username
                                or parsed.password or parsed.query or parsed.fragment or parsed.path):
            raise ValueError("Укажите BOT_TOKEN, OWNER_ID и HTTPS APP_URL в .env")
        ttl = int(os.environ.get("INIT_DATA_TTL", "86400"))
        if ttl < 60 or ttl > 86400:
            raise ValueError("INIT_DATA_TTL должен быть от 60 до 86400 секунд")
        return cls(token, owner, url, os.environ.get("DATABASE_PATH", "data/raffle.sqlite3"), ttl)
