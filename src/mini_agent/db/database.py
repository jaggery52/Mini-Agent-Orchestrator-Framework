"""SQLite connection + schema for the user-account store.

Deliberately tiny: stdlib ``sqlite3`` only, no ORM. The DB file lives on a Docker
volume (``USERS_DB`` in settings) so accounts survive container restarts. Any future
table is added to ``USERS_SCHEMA`` / a sibling statement here — user-domain logic
stays in ``users.py``.
"""

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


def get_connection() -> sqlite3.Connection:
    """Open a short-lived connection to the users DB.

    ``check_same_thread=False`` because FastAPI/uvicorn may touch the DB from worker
    threads. ``row_factory`` yields dict-like rows. A short ``busy_timeout`` lets a
    connection wait out a transient lock instead of failing immediately when both
    replicas touch the shared file at once.

    We deliberately keep the default (rollback-journal) mode rather than WAL: two
    replicas booting against the same mounted file race on the WAL-mode switch
    (``database is locked``), and WAL relies on shared memory that does not work over
    a network filesystem (e.g. Azure Files / SMB). Writes here are tiny and rare, so
    the rollback journal is plenty.
    """
    USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USERS_DB, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Create the schema if it does not exist. Idempotent; called at app startup."""
    with get_connection() as conn:
        conn.executescript(USERS_SCHEMA)
