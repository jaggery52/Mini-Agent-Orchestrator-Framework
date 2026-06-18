import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHROMA_DIR = PROJECT_ROOT / "chroma_db"
USERS_DB = Path(os.getenv("USERS_DB_PATH", PROJECT_ROOT / "data" / "users.db"))
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
