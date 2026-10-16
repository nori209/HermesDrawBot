import tempfile
import unittest
from pathlib import Path

from raffle.bot import Bot, TelegramError
from raffle.config import Config


class FakeBot(Bot):
    def __init__(self, config, webhook=""):
        super().__init__(config)
        self.calls = []
        self.webhook = webhook

    def api(self, method, payload=None):
        self.calls.append((method, payload))
        if method == "getWebhookInfo":
            return {"url": self.webhook}
        return True


class BotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = Config("123:test", 777, "https://raffle.example.com", str(Path(self.directory.name) / "db.sqlite3"))

    def tearDown(self):
        self.directory.cleanup()

    def test_refuses_token_with_existing_webhook(self):
        bot = FakeBot(self.config, "https://existing.example.com/webhook")
        with self.assertRaises(RuntimeError):
            bot.setup()
        self.assertEqual([method for method, _ in bot.calls], ["getMe", "getWebhookInfo"])

    def test_new_bot_has_menu_button_and_private_start(self):
        bot = FakeBot(self.config)
        bot.setup()
        menu = next(payload for method, payload in bot.calls if method == "setChatMenuButton")
        self.assertEqual(menu["menu_button"]["web_app"]["url"], self.config.app_url)
        bot.handle({"message": {"chat": {"id": 777, "type": "private"}, "from": {"id": 777}, "text": "/start"}})
        self.assertIn("организатор", bot.calls[-1][1]["text"])
        count = len(bot.calls)
        bot.handle({"message": {"chat": {"id": -123, "type": "group"}, "text": "/start"}})
        self.assertEqual(len(bot.calls), count)

    def test_telegram_error_never_contains_token(self):
        error = TelegramError(401)
        self.assertNotIn(self.config.token, str(error))

    def test_polling_offset_is_persistent(self):
        bot = FakeBot(self.config)
        bot.db.set_bot_offset(54321)
        self.assertEqual(FakeBot(self.config).db.bot_offset(), 54321)


if __name__ == "__main__":
    unittest.main()
