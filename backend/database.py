from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.config import BASE_DIR

DB_PATH = BASE_DIR / "data" / "documind.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS guest_usage (
            guest_id TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            operation_count INTEGER DEFAULT 0,
            PRIMARY KEY (guest_id, usage_date)
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            doc_id TEXT,
            title TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_history_owner_created
            ON history(owner_key, created_at DESC);

        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_key TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            filename TEXT,
            messages TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(owner_key, doc_id)
        );
        """
    )
    conn.commit()
    conn.close()
