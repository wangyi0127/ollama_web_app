import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from .config import DATABASE_FILE


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_database():
    connection = sqlite3.connect(DATABASE_FILE, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with closing(open_database()) as database:
        database.execute("PRAGMA journal_mode = WAL")
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                model_context TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id_id
                ON messages(chat_id, id);
            """
        )
        database.commit()

        chat_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(chats)")
        }
        message_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(messages)")
        }
        if "user_id" not in chat_columns:
            database.execute(
                "ALTER TABLE chats ADD COLUMN user_id TEXT "
                "REFERENCES users(id) ON DELETE CASCADE"
            )
        if "model_context" not in message_columns:
            database.execute(
                "ALTER TABLE messages ADD COLUMN model_context TEXT NOT NULL DEFAULT ''"
            )
        database.execute(
            "CREATE INDEX IF NOT EXISTS idx_chats_user_updated "
            "ON chats(user_id, updated_at DESC)"
        )
        database.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"
        )
