"""Small SQLite data layer. All timestamps are Unix UTC seconds."""
import sqlite3
from pathlib import Path
from typing import Any

from config import DATABASE_PATH


def connect() -> sqlite3.Connection:
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at INTEGER NOT NULL,
                folder_created INTEGER NOT NULL,
                record_expire INTEGER,
                banned INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER NOT NULL DEFAULT 0,
                download_url TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'link',
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_files_user_created
                ON files(user_id, created_at DESC);
            """
        )
        # Migrate older databases created by earlier versions of the project.
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "folder_created" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN folder_created INTEGER")
            db.execute("UPDATE users SET folder_created=joined_at WHERE folder_created IS NULL")
        if "record_expire" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN record_expire INTEGER")
        file_columns = {row[1] for row in db.execute("PRAGMA table_info(files)").fetchall()}
        if "source" not in file_columns:
            db.execute("ALTER TABLE files ADD COLUMN source TEXT NOT NULL DEFAULT 'link'")


def touch_user(user_id: int, username: str | None, first_name: str | None, now: int) -> None:
    with connect() as db:
        db.execute(
            """INSERT INTO users(user_id, username, first_name, joined_at, folder_created)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, first_name=excluded.first_name""",
            (user_id, username, first_name, now, now),
        )


def get_user(user_id: int) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def is_banned(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row.get("banned"))


def set_banned(user_id: int, value: bool) -> None:
    with connect() as db:
        db.execute("UPDATE users SET banned=? WHERE user_id=?", (int(value), user_id))


def set_record_expiry(user_id: int, expiry: int | None) -> None:
    with connect() as db:
        db.execute("UPDATE users SET record_expire=? WHERE user_id=?", (expiry, user_id))


def add_file(user_id: int, name: str, size: int, url: str, created_at: int, source: str = "link") -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO files(user_id,file_name,file_size,download_url,created_at,source) VALUES(?,?,?,?,?,?)",
            (user_id, name, max(0, int(size)), url, created_at, source),
        )


def recent_files(user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM files WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def stats() -> dict[str, int]:
    with connect() as db:
        return {
            "users": int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
            "banned": int(db.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]),
            "files": int(db.execute("SELECT COUNT(*) FROM files").fetchone()[0]),
            "bytes": int(db.execute("SELECT COALESCE(SUM(file_size),0) FROM files").fetchone()[0]),
        }


def list_users(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT user_id, username, first_name, joined_at, banned FROM users ORDER BY joined_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def all_user_ids() -> list[int]:
    with connect() as db:
        return [int(row[0]) for row in db.execute("SELECT user_id FROM users WHERE banned=0").fetchall()]
