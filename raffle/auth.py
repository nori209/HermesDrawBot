import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from .errors import AppError


def authenticate(raw, token, ttl=86400, now=None):
    """Validate Telegram initData; identity never comes from request JSON."""
    if not token:
        raise AppError(503, "Бот пока не подключён. Обратитесь к организатору.")
    try:
        if not raw or len(raw) > 16384:
            raise ValueError
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=30)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError
        supplied = fields.pop("hash")
        check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise ValueError
        age = (time.time() if now is None else now) - int(fields["auth_date"])
        if age < -30 or age > ttl:
            raise ValueError
        user = json.loads(fields["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or not 0 < user["id"] < 2**52:
            raise ValueError
        for key in ("first_name", "last_name", "username"):
            if key in user and (not isinstance(user[key], str) or len(user[key]) > 256):
                raise ValueError
        return user
    except (ValueError, KeyError, TypeError, OverflowError):
        raise AppError(401, "Откройте приложение заново через Telegram.") from None
