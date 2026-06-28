import json
from datetime import datetime, timezone

from mini_agent.db.database import get_connection


def save_config(user_id: int, name: str, config: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO user_configs (user_id, name, config_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, name) DO UPDATE SET config_json = excluded.config_json, updated_at = excluded.updated_at",
            (user_id, name, json.dumps(config), now, now),
        )
    return {"name": name, "updated_at": now}


def list_configs(user_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, updated_at FROM user_configs WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [{"id": row["id"], "name": row["name"], "updated_at": row["updated_at"]} for row in rows]


def get_config(user_id: int, config_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, config_json FROM user_configs WHERE id = ? AND user_id = ?",
            (config_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "config": json.loads(row["config_json"])}


def delete_config(user_id: int, config_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM user_configs WHERE id = ? AND user_id = ?",
            (config_id, user_id),
        )
    return cursor.rowcount > 0
