import json
import logging
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

from .auth import authenticate
from .bot import send_message
from .config import Config
from .db import Database
from .errors import AppError

STATIC = Path(__file__).parent / "static"
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Content-Security-Policy", "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org"),
]


class Application:
    def __init__(self, config):
        self.config = config
        self.db = Database(config.database)

    def __call__(self, environ, start_response):
        content_type = "application/json; charset=utf-8"
        try:
            status, body, content_type = self.dispatch(environ)
        except AppError as exc:
            status, body = exc.status, {"error": exc.message}
        except Exception:
            logging.exception("Request failed")
            status, body = 500, {"error": "Временная ошибка. Повторите попытку."}
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        headers = SECURITY_HEADERS + [("Content-Type", content_type), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")]
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]

    def dispatch(self, env):
        path, method = env.get("PATH_INFO", "/"), env.get("REQUEST_METHOD", "GET")
        json_type = "application/json; charset=utf-8"
        if path == "/healthz" and method == "GET":
            with self.db.connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return 200, {"status": "ok", "configured": bool(self.config.token and self.config.owner_id)}, json_type
        assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
        if path in assets and method == "GET":
            name, content_type = assets[path]
            return 200, (STATIC / name).read_bytes(), content_type
        routes = {"/api/state": "GET", "/api/join": "POST", "/api/admin/draw": "POST",
                  "/api/admin/new-round": "POST", "/api/admin/participants": "GET",
                  "/api/admin/remove-participant": "POST"}
        if path not in routes:
            raise AppError(404, "Страница не найдена.")
        if method != routes[path]:
            raise AppError(405, "Метод не поддерживается.")
        auth = env.get("HTTP_AUTHORIZATION", "")
        user = authenticate(auth[4:] if auth.startswith("tma ") else "", self.config.token, self.config.auth_ttl)
        is_owner = user["id"] == self.config.owner_id
        if path.startswith("/api/admin/") and not is_owner:
            raise AppError(403, "Эта функция доступна только организатору.")
        if path == "/api/state":
            return 200, {**self.db.state(user["id"]), "is_owner": is_owner,
                         "user": {"first_name": user.get("first_name", "Участник"), "username": user.get("username")}}, json_type
        if path == "/api/admin/participants":
            query = parse_qs(env.get("QUERY_STRING", ""))
            try:
                rid, page = int(query["round_id"][0]), int(query.get("page", ["1"])[0])
                if rid < 1 or page < 1 or page > 1000000:
                    raise ValueError
            except (ValueError, KeyError):
                raise AppError(400, "Некорректная страница.") from None
            return 200, self.db.participants(rid, page), json_type
        body = self.read_json(env)
        rid = body.get("round_id")
        if type(rid) is not int or rid < 1:
            raise AppError(400, "Укажите номер розыгрыша.")
        if path == "/api/join":
            result = {"entry": self.db.join(rid, user)}
        elif path == "/api/admin/draw":
            was_open = self.db.round_status(rid) == "open"
            winner = self.db.draw(rid, user["id"])
            if was_open:
                self._notify_draw(rid)
            result = {"winner": winner}
        elif path == "/api/admin/remove-participant":
            number = body.get("number")
            if type(number) is not int or number < 1:
                raise AppError(400, "Укажите номер участника.")
            result = self.db.remove_entry(rid, number)
        else:
            result = {"round_id": self.db.new_round(rid)}
        return 200, result, json_type

    def _notify_draw(self, round_id):
        details = self.db.winner_details(round_id)
        if not details:
            return
        name = f"@{details['username']}" if details["username"] else details["display_name"]
        winner_text = (
            f"🎉 Поздравляем! Вы победили в розыгрыше №{round_id}.\n"
            f"Ваш билет: №{details['number']}.\n\n"
            f"Свяжитесь с организатором для получения приза."
        )
        send_message(self.config.token, details["telegram_id"], winner_text)
        owner_text = (
            f"🎯 Розыгрыш №{round_id} завершён.\n\n"
            f"Победитель: {name}\n"
            f"Telegram ID: {details['telegram_id']}\n"
            f"Билет: №{details['number']}"
        )
        send_message(self.config.token, self.config.owner_id, owner_text)

    @staticmethod
    def read_json(env):
        if env.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
            raise AppError(415, "Ожидается JSON.")
        try:
            length = int(env.get("CONTENT_LENGTH", "0"))
            if length < 0 or length > 16384:
                raise AppError(413, "Слишком большой запрос.")
            body = json.loads(env["wsgi.input"].read(length))
            if not isinstance(body, dict):
                raise ValueError
            return body
        except (ValueError, UnicodeError):
            raise AppError(400, "Некорректный запрос.") from None


def create_app():
    return Application(Config.from_env())


if __name__ == "__main__":
    from wsgiref.simple_server import make_server
    app = create_app()
    print("Локальный просмотр: http://127.0.0.1:8088")
    with make_server("127.0.0.1", 8088, app) as server:
        server.serve_forever()
