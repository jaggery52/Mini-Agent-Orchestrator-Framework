import sqlite3

from mini_agent.settings import USERS_DB

# Single table for now. ``email`` is the username (case-insensitive unique); the
# password is never stored in plaintext (see ``users._hash_password``).
USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    token         TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL
);
"""

# Saved flow-builder configs, one row per (user, name).
CONFIGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_configs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(user_id, name),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
"""


def get_connection() -> sqlite3.Connection:
    """Get a connection to the users DB. Caller is responsible for closing it."""
    USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USERS_DB, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Create the schema if it does not exist. Idempotent; called at app startup."""
    with get_connection() as conn:
        conn.executescript(USERS_SCHEMA)
        conn.executescript(CONFIGS_SCHEMA)
