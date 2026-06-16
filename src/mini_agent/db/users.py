"""User-account operations: signup, login, and per-user access tokens.

Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib ``hashlib``) + a per-user random
salt — never stored or logged in plaintext. Each user holds exactly one access token
(``secrets.token_urlsafe``) that gates the WebSocket ``init`` handshake; regenerating
it overwrites the old one.
"""

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone

from mini_agent.db.database import get_connection

_PBKDF2_ROUNDS = 200_000


class DuplicateEmailError(Exception):
    """Raised by ``create_user`` when the email is already registered."""


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS).hex()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _public(row: sqlite3.Row) -> dict:
    """Project a DB row to the fields safe to return to the client."""
    return {"name": row["name"], "email": row["email"], "token": row["token"]}


def create_user(name: str, email: str, password: str) -> dict:
    """Insert a new user and issue an access token. Raises ``DuplicateEmailError``."""
    salt = secrets.token_bytes(16)
    record = {
        "name": name.strip(),
        "email": email.strip(),
        "password_hash": _hash_password(password, salt),
        "salt": salt.hex(),
        "token": _new_token(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, salt, token, created_at) "
                "VALUES (:name, :email, :password_hash, :salt, :token, :created_at)",
                record,
            )
    except sqlite3.IntegrityError as error:
        raise DuplicateEmailError(email) from error
    return {"name": record["name"], "email": record["email"], "token": record["token"]}


def verify_login(email: str, password: str) -> dict | None:
    """Return the user (incl. token) if the password matches, else ``None``."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip(),)).fetchone()
    if row is None:
        return None
    expected = _hash_password(password, bytes.fromhex(row["salt"]))
    if not hmac.compare_digest(expected, row["password_hash"]):
        return None
    return _public(row)


def get_user_by_token(token: str) -> dict | None:
    """Look up a user by access token — the WebSocket auth path. Returns id + fields."""
    if not token:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], **_public(row)}


def regenerate_token(user_id: int) -> str:
    """Issue a fresh token for the user, overwriting the old one. Returns the new token."""
    token = _new_token()
    with get_connection() as conn:
        conn.execute("UPDATE users SET token = ? WHERE id = ?", (token, user_id))
    return token
