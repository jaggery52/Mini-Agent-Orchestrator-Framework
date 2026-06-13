import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Repo root: src/mini_agent/settings.py -> parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# On-disk store for the per-session KB collections (created/deleted at runtime).
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

# Auth gate for the WebSocket — the ONLY secret the running server reads from env.
# LLM / search API keys, model names, and KB docs are NOT read here; they are supplied
# by the client per connection in the `init`/`documents` handshake (see server.py).
SERVER_ACCESS_TOKEN = os.getenv("SERVER_ACCESS_TOKEN", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "logs/agent.log")

_log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)


def _setup_logging():
    fmt = "%(asctime)s  %(levelname)-8s  %(message)s"
    date_fmt = "%H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=date_fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(_log_level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)


_setup_logging()
