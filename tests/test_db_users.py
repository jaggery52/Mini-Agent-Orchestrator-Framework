"""Unit tests for the SQLite user store. No network/LLM — a temp DB file only."""

import pytest

from mini_agent.db import database, users


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "USERS_DB", tmp_path / "users.db")
    database.init_db()
    return database


def test_create_and_login(db):
    created = users.create_user("Ada", "ada@example.com", "secret1")
    assert created["email"] == "ada@example.com"
    assert created["token"]

    ok = users.verify_login("ada@example.com", "secret1")
    assert ok is not None
    assert ok["token"] == created["token"]

    # Email match is case-insensitive.
    assert users.verify_login("ADA@example.com", "secret1") is not None


def test_login_rejects_bad_password_and_unknown_email(db):
    users.create_user("Ada", "ada@example.com", "secret1")
    assert users.verify_login("ada@example.com", "wrong") is None
    assert users.verify_login("nobody@example.com", "secret1") is None


def test_password_is_hashed_not_plaintext(db):
    users.create_user("Ada", "ada@example.com", "secret1")
    with database.get_connection() as conn:
        row = conn.execute("SELECT password_hash FROM users").fetchone()
    assert row["password_hash"] != "secret1"


def test_duplicate_email_raises(db):
    users.create_user("Ada", "ada@example.com", "secret1")
    with pytest.raises(users.DuplicateEmailError):
        users.create_user("Ada Two", "ada@example.com", "another")


def test_token_lookup_and_regenerate(db):
    created = users.create_user("Ada", "ada@example.com", "secret1")
    found = users.get_user_by_token(created["token"])
    assert found is not None and found["email"] == "ada@example.com"

    new_token = users.regenerate_token(found["id"])
    assert new_token != created["token"]
    # Old token no longer resolves; the new one does.
    assert users.get_user_by_token(created["token"]) is None
    assert users.get_user_by_token(new_token) is not None


def test_get_user_by_empty_token(db):
    assert users.get_user_by_token("") is None
