import json
import logging
import signal
import threading
import urllib.error
import urllib.request

from .config import Config
from .db import Database
from .errors import AppError


class TelegramError(Exception):
    def __init__(self, code, retry_after=5):
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"Telegram API error {code}")


class Bot:
    def __init__(self, config):
        self.config = config
        self.db = Database(config.database)
        self.stop = threading.Event()

    def api(self, method, payload=None):
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.config.token}/{method}",
            json.dumps(payload or {}).encode(),
            {"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read())
            except ValueError:
                raise TelegramError(exc.code) from None
            raise TelegramError(exc.code, result.get("parameters", {}).get("retry_after", 5)) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise TelegramError(0) from None
        if not result.get("ok"):
            raise TelegramError(result.get("error_code", 0))
        return result["result"]

    def setup(self):
        self.api("getMe")
        if self.api("getWebhookInfo").get("url"):
            raise RuntimeError("У этого токена уже установлен webhook. Используйте отдельного нового бота.")
        self.api("setChatMenuButton", {
            "menu_button": {"type": "web_app", "text": "Розыгрыш",
                            "web_app": {"url": self.config.app_url}}
        })
        self.api("setMyCommands", {"scope": {"type": "default"}, "commands": [
            {"command": "start", "description": "Открыть розыгрыш"},
            {"command": "help", "description": "Как участвовать"},
            {"command": "ticket", "description": "Мой билет"},
        ]})
        admin_commands = [
            {"command": "start", "description": "Открыть розыгрыш"},
            {"command": "ticket", "description": "Мой билет"},
            {"command": "admin", "description": "Команды организатора"},
            {"command": "list", "description": "Список участников"},
            {"command": "draw", "description": "Запустить розыгрыш"},
            {"command": "new", "description": "Новый розыгрыш"},
            {"command": "remove", "description": "Удалить участника по номеру"},
            {"command": "clear", "description": "Очистить список"},
            {"command": "admins", "description": "Список мастеров"},
        ]
        for owner_id in self.config.owner_ids:
            self.api("setMyCommands", {"scope": {"type": "chat", "chat_id": owner_id}, "commands": admin_commands})

    def current_round_id(self):
        with self.db.connect() as conn:
            row = conn.execute("SELECT id FROM rounds ORDER BY id DESC LIMIT 1").fetchone()
            return row["id"]

    def reply(self, chat_id, text, **extra):
        self.api("sendMessage", {"chat_id": chat_id, "text": text,
                                 "disable_web_page_preview": True, **extra})

    def handle(self, update):
        message = update.get("message", {})
        if message.get("chat", {}).get("type") != "private":
            return
        raw = (message.get("text") or "").strip()
        if not raw:
            return
        parts = raw.split()
        cmd = parts[0].split("@")[0].lower()
        args = parts[1:]
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        is_owner = user_id is not None and self.config.is_owner(user_id)

        if cmd in ("/start", "/help"):
            return self.cmd_welcome(chat_id, is_owner)
        if cmd == "/ticket":
            return self.cmd_ticket(chat_id, user_id)
        if cmd == "/admin":
            if not is_owner:
                return
            return self.reply(chat_id, (
                "Команды организатора:\n"
                "/list — список участников\n"
                "/draw — запустить розыгрыш (1 победитель)\n"
                "/new — новый розыгрыш\n"
                "/remove N — удалить участника с билетом N\n"
                "/clear — очистить список участников текущего розыгрыша\n"
                "/admins — список мастеров\n"
                "/ticket — мой билет"
            ))
        if not is_owner:
            return
        if cmd == "/list":
            return self.cmd_list(chat_id)
        if cmd == "/draw":
            return self.cmd_draw(chat_id, user_id)
        if cmd == "/new":
            return self.cmd_new(chat_id)
        if cmd == "/clear":
            return self.cmd_clear(chat_id)
        if cmd == "/remove":
            return self.cmd_remove(chat_id, args)
        if cmd == "/admins":
            return self.cmd_admins(chat_id)

    def cmd_welcome(self, chat_id, is_owner):
        welcome = ("🎯 Добро пожаловать в розыгрыш!\n\n"
                   "Откройте приложение и нажмите «Участвовать».")
        if is_owner:
            welcome += "\n\nВы — организатор. Команды: /admin"
        self.reply(chat_id, welcome, reply_markup={"inline_keyboard": [[
            {"text": "🎯 Открыть розыгрыш", "web_app": {"url": self.config.app_url}}
        ]]})

    def cmd_ticket(self, chat_id, user_id):
        rid = self.current_round_id()
        number = self.db.my_entry(rid, user_id)
        if number is None:
            return self.reply(chat_id, f"Вы ещё не участвуете в розыгрыше №{rid}. Откройте приложение и нажмите «Участвовать».")
        self.reply(chat_id, f"🎟 Ваш билет в розыгрыше №{rid}: №{number:03d}")

    def cmd_list(self, chat_id):
        rid = self.current_round_id()
        data = self.db.participants(rid, 1)
        total = data["total"]
        if not total:
            return self.reply(chat_id, f"Розыгрыш №{rid}: участников нет.")
        lines = [f"Розыгрыш №{rid} — участников: {total}", ""]
        for item in data["items"]:
            name = f"@{item['username']}" if item["username"] else item["display_name"]
            mark = f" [{item['place']}-е место]" if item.get("place") else ""
            lines.append(f"№{item['number']:03d} — {name} (ID {item['telegram_id']}){mark}")
        if total > len(data["items"]):
            lines.append("")
            lines.append("Показаны первые 50. Остальные — в Mini App.")
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3990] + "…"
        self.reply(chat_id, text)

    def cmd_draw(self, chat_id, actor_id):
        rid = self.current_round_id()
        was_open = self.db.round_status(rid) == "open"
        try:
            winners = self.db.draw(rid, actor_id, winner_count=1)
        except AppError as exc:
            return self.reply(chat_id, f"⚠️ {exc.message}")
        if not was_open:
            w = winners[0] if winners else None
            tail = f" Победитель: №{w['number']:03d}." if w else ""
            return self.reply(chat_id, f"ℹ️ Розыгрыш №{rid} уже завершён.{tail}")
        if not winners:
            return self.reply(chat_id, f"Розыгрыш №{rid} завершён без победителя.")
        lines = [f"🎯 Розыгрыш №{rid} завершён."]
        for w in winners:
            name = f"@{w['username']}" if w["username"] else w["display_name"]
            lines.append(f"Победитель: {name} · билет №{w['number']:03d}")
        self.reply(chat_id, "\n".join(lines))

    def cmd_new(self, chat_id):
        rid = self.current_round_id()
        try:
            new_id = self.db.new_round(rid)
        except AppError as exc:
            return self.reply(chat_id, f"⚠️ {exc.message}")
        self.reply(chat_id, f"✅ Открыт розыгрыш №{new_id}. Участники регистрируются заново.")

    def cmd_clear(self, chat_id):
        rid = self.current_round_id()
        try:
            removed = self.db.clear_entries(rid)
        except AppError as exc:
            return self.reply(chat_id, f"⚠️ {exc.message}")
        self.reply(chat_id, f"🧹 Удалено участников: {removed}.")

    def cmd_remove(self, chat_id, args):
        if not args:
            return self.reply(chat_id, "Использование: /remove НОМЕР_БИЛЕТА")
        try:
            number = int(args[0])
            if number < 1:
                raise ValueError
        except ValueError:
            return self.reply(chat_id, "Номер должен быть положительным целым.")
        rid = self.current_round_id()
        try:
            self.db.remove_entry(rid, number)
        except AppError as exc:
            return self.reply(chat_id, f"⚠️ {exc.message}")
        self.reply(chat_id, f"🗑 Билет №{number:03d} удалён.")

    def cmd_admins(self, chat_id):
        if not self.config.owner_ids:
            return self.reply(chat_id, "Список владельцев пуст.")
        lines = ["👑 Владельцы:"]
        for i, oid in enumerate(self.config.owner_ids, 1):
            lines.append(f"{i}. {oid}")
        self.reply(chat_id, "\n".join(lines))

    def run(self):
        while not self.stop.is_set():
            try:
                self.setup()
                break
            except TelegramError as exc:
                if exc.code in (401, 404, 409):
                    raise RuntimeError("Проверьте токен и отсутствие другого процесса для этого бота.") from None
                logging.warning("Telegram temporarily unavailable (%s)", exc.code)
                self.stop.wait(exc.retry_after)
        offset = self.db.bot_offset()
        while not self.stop.is_set():
            try:
                updates = self.api("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message"]})
                for update in updates:
                    try:
                        self.handle(update)
                    except TelegramError as exc:
                        if exc.code not in (400, 403):
                            raise
                    offset = update["update_id"] + 1
                    self.db.set_bot_offset(offset)
            except TelegramError as exc:
                if exc.code in (401, 404, 409):
                    raise RuntimeError("Telegram отклонил polling: проверьте токен и второй экземпляр бота.") from None
                logging.warning("Telegram polling retry (%s)", exc.code)
                self.stop.wait(exc.retry_after)


def send_message(token, chat_id, text):
    if not token or not chat_id:
        return False
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
            return bool(result.get("ok"))
    except Exception:
        logging.exception("Failed to send Telegram message to chat %s", chat_id)
        return False


def send_photo(token, chat_id, photo_bytes, caption=""):
    import io as _io
    import uuid as _uuid
    if not token or not chat_id or not photo_bytes:
        return False

    boundary = "----Hermes" + _uuid.uuid4().hex
    body = _io.BytesIO()

    def field(name, value):
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(str(value).encode("utf-8"))
        body.write(b"\r\n")

    field("chat_id", chat_id)
    if caption:
        field("caption", caption)

    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="photo"; filename="ticket.png"\r\n')
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(photo_bytes)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        body.getvalue(),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
            return bool(result.get("ok"))
    except Exception:
        logging.exception("Failed to send Telegram photo to chat %s", chat_id)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bot = Bot(Config.from_env())
    signal.signal(signal.SIGTERM, lambda *_: bot.stop.set())
    signal.signal(signal.SIGINT, lambda *_: bot.stop.set())
    bot.run()