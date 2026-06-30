"""Persistence layer: SQLite-backed user accounts + access tokens.

``server.py`` imports the public surface from here.
"""

from mini_agent.db.configs import (
    delete_config,
    get_config,
    list_configs,
    save_config,
)
from mini_agent.db.database import init_db
from mini_agent.db.users import (
    DuplicateEmailError,
    create_user,
    get_user_by_token,
    regenerate_token,
    verify_login,
)

__all__ = [
    "init_db",
    "create_user",
    "verify_login",
    "get_user_by_token",
    "regenerate_token",
    "DuplicateEmailError",
    "save_config",
    "list_configs",
    "get_config",
    "delete_config",
]
