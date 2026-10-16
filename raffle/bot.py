import json
import logging
import signal
import threading
import urllib.error
import urllib.request

from .config import Config
from .db import Database


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
        request = urllib.request.Request(f"https://api.telegram.org/bot{self.config.token}/{method}",
                                         json.dumps(payload or {}).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            # Never log HTTPError's URL: it includes the bot token.
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
        # Refuse to take over a token already serving another webhook-based bot.
        if self.api("getWebhookInfo").get("url"):
            raise RuntimeError("У этого токена уже установлен webhook. Используйте отдельного нового бота.")
        self.api("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Розыгрыш", "web_app": {"url": self.config.app_url}}})
        self.api("setMyCommands", {"commands": [{"command": "start", "description": "Открыть розыгрыш"},
                                                {"command": "help", "description": "Как участвовать"}]})

    def handle(self, update):
        message = update.get("message", {})
        if message.get("chat", {}).get("type") != "private":
            return
        text = message.get("text", "").split(" ")[0].split("@")[0]
        if text not in ("/start", "/help", "/admin"):
            return
        owner = message.get("from", {}).get("id") == self.config.owner_id
        welcome = "🎯 Добро пожаловать в розыгрыш!\n\nОткройте приложение и нажмите «Участвовать». Вы получите личный номер. Результат появится здесь же, в приложении."
        if owner:
            welcome += "\n\nВы — организатор. В приложении доступна кнопка «Запустить розыгрыш» и список участников."
        self.api("sendMessage", {"chat_id": message["chat"]["id"], "text": welcome,
                                "reply_markup": {"inline_keyboard": [[{"text": "🎯 Открыть розыгрыш", "web_app": {"url": self.config.app_url}}]]}})

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bot = Bot(Config.from_env())
    signal.signal(signal.SIGTERM, lambda *_: bot.stop.set())
    signal.signal(signal.SIGINT, lambda *_: bot.stop.set())
    bot.run()

def send_message(token, chat_id, text):
    """Send a Telegram message. Used by the web app for draw notifications."""
    import json as _json
    if not token or not chat_id:
        return False
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        _json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = _json.load(response)
            return bool(result.get("ok"))
    except Exception:
        logging.exception("Failed to send Telegram message to chat %s", chat_id)
        return False

