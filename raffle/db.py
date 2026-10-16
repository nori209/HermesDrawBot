import fcntl
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .errors import AppError


SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'finished')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    drawn_at TEXT,
    winner_number INTEGER,
    drawn_by INTEGER,
    CHECK ((status = 'open' AND winner_number IS NULL AND drawn_at IS NULL)
        OR (status = 'finished' AND winner_number IS NOT NULL AND drawn_at IS NOT NULL)),
    FOREIGN KEY(id, winner_number) REFERENCES entries(round_id, number)
);
CREATE UNIQUE INDEX IF NOT EXISTS only_one_open_round ON rounds(status) WHERE status='open';
CREATE TABLE IF NOT EXISTS entries (
    round_id INTEGER NOT NULL REFERENCES rounds(id),
    number INTEGER NOT NULL CHECK(number > 0),
    telegram_id INTEGER NOT NULL,
    username TEXT,
    display_name TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY(round_id, number),
    UNIQUE(round_id, telegram_id)
);
CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def public_entry(row):
    return {key: row[key] for key in ("number", "username", "display_name")} if row else None


class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # Separate workers may start simultaneously; WAL initialization needs a
        # process-wide lock before the database's own write lock is available.
        fd = os.open(self.path + ".init.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            db_fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(db_fd)
            with self.connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(SCHEMA)
                conn.execute("INSERT INTO rounds (id) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM rounds)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def state(self, telegram_id):
        with self.connect() as conn:
            conn.execute("BEGIN")
            current = conn.execute("SELECT * FROM rounds ORDER BY id DESC LIMIT 1").fetchone()
            rid = current["id"]
            count = conn.execute("SELECT COUNT(*) FROM entries WHERE round_id=?", (rid,)).fetchone()[0]
            mine = conn.execute("SELECT * FROM entries WHERE round_id=? AND telegram_id=?", (rid, telegram_id)).fetchone()
            winner = conn.execute("SELECT * FROM entries WHERE round_id=? AND number=?", (rid, current["winner_number"])).fetchone()
            history = conn.execute("""SELECT r.id, r.drawn_at, e.number, e.username, e.display_name
                FROM rounds r JOIN entries e ON e.round_id=r.id AND e.number=r.winner_number
                ORDER BY r.id DESC LIMIT 10""").fetchall()
            return {"round": {"id": rid, "status": current["status"], "drawn_at": current["drawn_at"]},
                    "participant_count": count, "my_entry": public_entry(mine), "winner": public_entry(winner),
                    "history": [dict(row) for row in history]}

    @staticmethod
    def current(conn, round_id):
        current = conn.execute("SELECT * FROM rounds ORDER BY id DESC LIMIT 1").fetchone()
        if current["id"] != round_id:
            raise AppError(409, "Начался другой розыгрыш. Обновите приложение.")
        return current

    def join(self, round_id, user):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.current(conn, round_id)
            existing = conn.execute("SELECT * FROM entries WHERE round_id=? AND telegram_id=?", (round_id, user["id"])).fetchone()
            if existing:
                return public_entry(existing)
            if current["status"] != "open":
                raise AppError(409, "Регистрация завершена. Дождитесь следующего розыгрыша.")
            number = conn.execute("SELECT COALESCE(MAX(number),0)+1 FROM entries WHERE round_id=?", (round_id,)).fetchone()[0]
            name = " ".join(filter(None, (user.get("first_name"), user.get("last_name")))) or "Участник"
            conn.execute("INSERT INTO entries(round_id,number,telegram_id,username,display_name) VALUES(?,?,?,?,?)",
                         (round_id, number, user["id"], user.get("username") or None, name))
            return {"number": number, "username": user.get("username") or None, "display_name": name}

    def draw(self, round_id, owner_id):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.current(conn, round_id)
            if current["status"] == "finished":
                winner = conn.execute("SELECT * FROM entries WHERE round_id=? AND number=?", (round_id, current["winner_number"])).fetchone()
            else:
                count = conn.execute("SELECT COUNT(*) FROM entries WHERE round_id=?", (round_id,)).fetchone()[0]
                if not count:
                    raise AppError(409, "Пока нет участников. Сначала откройте регистрацию.")
                winner = conn.execute("SELECT * FROM entries WHERE round_id=? ORDER BY number LIMIT 1 OFFSET ?",
                                      (round_id, secrets.randbelow(count))).fetchone()
                conn.execute("""UPDATE rounds SET status='finished',winner_number=?,drawn_by=?,
                    drawn_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?""", (winner["number"], owner_id, round_id))
            return public_entry(winner)

    def new_round(self, previous_id):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM rounds ORDER BY id DESC LIMIT 1").fetchone()
            # A retried request must never create an extra round.
            if current["id"] == previous_id + 1 and current["status"] == "open":
                return current["id"]
            if current["id"] != previous_id or current["status"] != "finished":
                raise AppError(409, "Сначала завершите текущий розыгрыш и обновите приложение.")
            return conn.execute("INSERT INTO rounds DEFAULT VALUES").lastrowid

    def participants(self, round_id, page):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM entries WHERE round_id=? ORDER BY number LIMIT 50 OFFSET ?",
                                (round_id, (page - 1) * 50)).fetchall()
            count = conn.execute("SELECT COUNT(*) FROM entries WHERE round_id=?", (round_id,)).fetchone()[0]
            return {"items": [dict(row) for row in rows], "total": count, "page": page, "pages": (count + 49) // 50}

    def bot_offset(self):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM bot_state WHERE key='offset'").fetchone()
            return int(row[0]) if row else 0

    def set_bot_offset(self, offset):
        with self.connect() as conn:
            conn.execute("INSERT INTO bot_state(key,value) VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(offset),))

    def remove_entry(self, round_id, number):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.current(conn, round_id)
            if current["status"] != "open":
                raise AppError(409, "После запуска розыгрыша список изменить нельзя.")
            cursor = conn.execute("DELETE FROM entries WHERE round_id=? AND number=?", (round_id, number))
            if cursor.rowcount == 0:
                raise AppError(404, "Участник не найден.")
            return {"removed": number}