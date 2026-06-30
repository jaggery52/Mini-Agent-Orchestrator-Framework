"""Unit tests for the SQLite saved-config store. No network/LLM — a temp DB file only."""

import pytest

from mini_agent.db import configs, database, users

FLOW = {"stateMachine": {"Start": {"function": "start", "args": [], "nextState": "EndFinal"}}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "USERS_DB", tmp_path / "users.db")
    database.init_db()
    return database


def _make_user(email: str) -> int:
    created = users.create_user("Ada", email, "secret1")
    return users.get_user_by_token(created["token"])["id"]


def test_save_then_list(db):
    user_id = _make_user("ada@example.com")
    configs.save_config(user_id, "my-flow", FLOW)
    saved = configs.list_configs(user_id)
    assert len(saved) == 1
    assert saved[0]["name"] == "my-flow"
    assert "config" not in saved[0]  # listing stays lightweight


def test_save_same_name_overwrites(db):
    user_id = _make_user("ada@example.com")
    configs.save_config(user_id, "my-flow", FLOW)
    configs.save_config(user_id, "my-flow", {"stateMachine": {"Other": {}}})
    saved = configs.list_configs(user_id)
    assert len(saved) == 1
    loaded = configs.get_config(user_id, saved[0]["id"])
    assert "Other" in loaded["config"]["stateMachine"]


def test_get_config_round_trips(db):
    user_id = _make_user("ada@example.com")
    configs.save_config(user_id, "my-flow", FLOW)
    config_id = configs.list_configs(user_id)[0]["id"]
    loaded = configs.get_config(user_id, config_id)
    assert loaded["name"] == "my-flow"
    assert loaded["config"] == FLOW


def test_delete(db):
    user_id = _make_user("ada@example.com")
    configs.save_config(user_id, "my-flow", FLOW)
    config_id = configs.list_configs(user_id)[0]["id"]
    assert configs.delete_config(user_id, config_id) is True
    assert configs.delete_config(user_id, config_id) is False
    assert configs.list_configs(user_id) == []


def test_users_are_isolated(db):
    owner_id = _make_user("owner@example.com")
    other_id = _make_user("other@example.com")
    configs.save_config(owner_id, "my-flow", FLOW)
    config_id = configs.list_configs(owner_id)[0]["id"]

    assert configs.list_configs(other_id) == []
    assert configs.get_config(other_id, config_id) is None
    assert configs.delete_config(other_id, config_id) is False
