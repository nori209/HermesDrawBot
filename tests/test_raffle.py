import hashlib
import hmac
import io
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

from raffle.auth import authenticate
from raffle.config import Config
from raffle.db import Database
from raffle.errors import AppError
from raffle.web import Application

TOKEN = "123456789:test-secret-for-tests-only"
OWNER = 777


def signed(user_id=123, now=None, **extra):
    fields = {"auth_date": str(int(time.time()) if now is None else now),
              "query_id": "test-query", "user": json.dumps({"id": user_id, "first_name": "Тест", **extra}, ensure_ascii=False)}
    secret = hmac.digest(b"WebAppData", TOKEN.encode(), "sha256")
    fields["hash"] = hmac.new(secret, "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class AuthTests(unittest.TestCase):
    def test_valid_signature_and_unicode(self):
        self.assertEqual(authenticate(signed(username="tester"), TOKEN)["username"], "tester")

    def test_tamper_wrong_token_expired_future_missing_duplicates(self):
        invalid = [signed().replace("test-query", "tampered"), signed(now=int(time.time()) - 86401),
                   signed(now=int(time.time()) + 90), "", signed() + "&auth_date=1", signed(user_id=True),
                   signed(user_id=-1), signed(username={"unsafe": True})]
        for raw in invalid:
            with self.subTest(raw=raw[:25]), self.assertRaises(AppError) as caught:
                authenticate(raw, TOKEN)
            self.assertEqual(caught.exception.status, 401)
        with self.assertRaises(AppError):
            authenticate(signed(), "wrong-token")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.directory.name) / "private.sqlite3")

    def tearDown(self):
        self.directory.cleanup()

    def join(self, uid):
        return self.db.join(1, {"id": uid, "first_name": "User", "username": f"user{uid}"})

    def test_concurrent_registrations_unique_sequential_idempotent(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            entries = list(pool.map(self.join, list(range(1, 61)) * 2))
        self.assertEqual({e["number"] for e in entries}, set(range(1, 61)))
        self.assertEqual(self.db.state(1)["participant_count"], 60)
        self.assertEqual(self.join(1), self.join(1))

    def test_concurrent_draws_choose_one_registered_winner_and_persist(self):
        for uid in range(1, 11):
            self.join(uid)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.db.draw(1, OWNER), range(16)))
        self.assertEqual(len({result["number"] for result in results}), 1)
        self.assertIn(results[0]["number"], range(1, 11))
        persisted = Database(self.db.path).state(1)
        self.assertEqual(persisted["winner"], results[0])
        self.assertEqual(persisted["round"]["status"], "finished")
        with self.assertRaises(AppError):
            self.join(999)
        self.assertIsNotNone(self.join(1))

    def test_draw_and_join_race_has_consistent_snapshot(self):
        self.join(1)
        def attempt(uid):
            try:
                return self.join(uid)
            except AppError:
                return None
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(attempt, uid) for uid in range(2, 41)]
            winner_future = pool.submit(self.db.draw, 1, OWNER)
            futures += [pool.submit(attempt, uid) for uid in range(41, 81)]
            accepted = [f.result() for f in futures if f.result() is not None]
            winner = winner_future.result()
        state = self.db.state(1)
        self.assertEqual(state["participant_count"], 1 + len(accepted))
        self.assertIn(winner["number"], [1] + [e["number"] for e in accepted])
        self.assertEqual(self.db.draw(1, OWNER), winner)

    def test_empty_draw_new_round_stale_requests_and_history(self):
        with self.assertRaises(AppError):
            self.db.draw(1, OWNER)
        with self.assertRaises(AppError):
            self.db.new_round(1)
        self.join(123)
        self.db.draw(1, OWNER)
        self.assertEqual(self.db.new_round(1), 2)
        self.assertEqual(self.db.new_round(1), 2)
        self.assertIsNone(self.db.state(123)["my_entry"])
        self.assertEqual(len(self.db.state(123)["history"]), 1)
        with self.assertRaises(AppError):
            self.db.draw(1, OWNER)
        with self.assertRaises(AppError):
            self.db.join(1, {"id": 333})
        self.assertEqual(self.db.join(2, {"id": 123})["number"], 1)

    def test_independent_databases(self):
        other = Database(Path(self.directory.name) / "other.sqlite3")
        self.join(1)
        self.assertEqual(other.state(1)["participant_count"], 0)

    def test_concurrent_cold_start(self):
        path = Path(self.directory.name) / "cold.sqlite3"
        with ThreadPoolExecutor(max_workers=8) as pool:
            states = list(pool.map(lambda _: Database(path).state(1), range(8)))
        self.assertTrue(all(state["round"]["id"] == 1 for state in states))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_pagination_and_private_fields(self):
        for uid in range(1, 56):
            self.join(uid)
        self.assertEqual(len(self.db.participants(1, 1)["items"]), 50)
        self.assertEqual(len(self.db.participants(1, 2)["items"]), 5)
        self.assertNotIn("telegram_id", self.db.state(1)["my_entry"])


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = Application(Config(TOKEN, OWNER, "https://raffle.example.com", str(Path(self.directory.name) / "db.sqlite3")))

    def tearDown(self):
        self.directory.cleanup()

    def request(self, path, method="GET", body=None, user=123, auth=None, content_type="application/json"):
        path, _, query = path.partition("?")
        data = json.dumps(body).encode() if body is not None else b""
        env = {"PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": method,
               "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(len(data)), "wsgi.input": io.BytesIO(data),
               "HTTP_AUTHORIZATION": "tma " + (signed(user) if auth is None else auth)}
        response = {}
        def start(status, headers):
            response.update(status=int(status.split()[0]), headers=dict(headers))
        raw = b"".join(self.app(env, start))
        response["body"] = json.loads(raw) if response["headers"]["Content-Type"].startswith("application/json") else raw
        return response

    def test_owner_authorization_on_every_admin_route(self):
        for route, method in [("/api/admin/draw", "POST"), ("/api/admin/new-round", "POST"), ("/api/admin/participants?round_id=1", "GET")]:
            self.assertEqual(self.request(route, method, {"round_id": 1})["status"], 403)
            self.assertEqual(self.request(route, method, {"round_id": 1}, auth="forged")["status"], 401)

    def test_full_workflow_and_no_client_identity_override(self):
        entry = self.request("/api/join", "POST", {"round_id": 1, "id": OWNER, "username": "forged"})
        self.assertEqual(entry["body"]["entry"]["number"], 1)
        self.assertIsNone(entry["body"]["entry"]["username"])
        private = self.request("/api/admin/participants?round_id=1", user=OWNER)
        self.assertEqual(private["body"]["items"][0]["telegram_id"], 123)
        result = self.request("/api/admin/draw", "POST", {"round_id": 1}, user=OWNER)
        self.assertEqual(result["body"]["winner"]["number"], 1)
        again = self.request("/api/admin/draw", "POST", {"round_id": 1}, user=OWNER)
        self.assertEqual(result["body"], again["body"])
        self.assertEqual(self.request("/api/join", "POST", {"round_id": 1}, user=444)["status"], 409)
        state = self.request("/api/state")["body"]
        self.assertFalse(state["is_owner"])
        self.assertNotIn("telegram_id", state["winner"])
        self.assertEqual(self.request("/api/admin/new-round", "POST", {"round_id": 1}, user=OWNER)["status"], 200)
        self.assertEqual(self.request("/api/admin/draw", "POST", {"round_id": 1}, user=OWNER)["status"], 409)

    def test_validation_static_secrets_and_headers(self):
        self.assertEqual(self.request("/api/join", "POST", {"round_id": True})["status"], 400)
        self.assertEqual(self.request("/api/join", "POST", {"round_id": 1}, content_type="text/plain")["status"], 415)
        self.assertEqual(self.request("/api/admin/participants?round_id=x", user=OWNER)["status"], 400)
        self.assertEqual(self.request("/api/state", "POST")["status"], 405)
        self.assertEqual(self.request("/.env")["status"], 404)
        self.assertEqual(self.request("/../config.py")["status"], 404)
        self.assertEqual(self.request("/data/raffle.sqlite3")["status"], 404)
        home = self.request("/")
        self.assertEqual(home["status"], 200)
        self.assertIn("Content-Security-Policy", home["headers"])
        self.assertNotIn(TOKEN.encode(), home["body"])
        self.assertEqual(self.request("/healthz")["status"], 200)


if __name__ == "__main__":
    unittest.main()
