"""Environment configuration for the FileBee Telegram bot."""
import os
from dotenv import load_dotenv

load_dotenv()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int_set(name: str) -> set[int]:
    values: set[int] = set()
    for part in os.getenv(name, "").split(","):
        part = part.strip()
        if part:
            try:
                values.add(int(part))
            except ValueError as exc:
                raise RuntimeError(f"Invalid numeric value in {name}: {part}") from exc
    return values


API_ID = env_int("API_ID", 0)
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = env_int_set("ADMIN_IDS")

BOT_NAME = os.getenv("BOT_NAME", "FileBee Telegram Storage Bot").strip()
MAX_FILE_GB = env_int("MAX_FILE_GB", 4)
MAX_UPLOAD_BYTES = MAX_FILE_GB * 1024**3

# FileBee's public website is known; its programmatic upload API is not verified.
FILEBEE_WEBSITE = os.getenv("FILEBEE_WEBSITE", "https://filebee.live/").strip().rstrip("/")
FILEBEE_UPLOAD_URL = os.getenv("FILEBEE_UPLOAD_URL", "").strip()
FILEBEE_API_TOKEN = os.getenv("FILEBEE_API_TOKEN", "").strip()
FILEBEE_AUTH_HEADER = os.getenv("FILEBEE_AUTH_HEADER", "Authorization").strip()
FILEBEE_AUTH_PREFIX = os.getenv("FILEBEE_AUTH_PREFIX", "Bearer ")
FILEBEE_FILE_FIELD = os.getenv("FILEBEE_FILE_FIELD", "file").strip()
FILEBEE_RESPONSE_URL_FIELD = os.getenv("FILEBEE_RESPONSE_URL_FIELD", "").strip()
FILEBEE_UPLOAD_TIMEOUT = env_int("FILEBEE_UPLOAD_TIMEOUT", 3600)

# Optional bot-side record lifetime. This does NOT delete files from FileBee.
LINK_RECORD_TTL_DAYS = env_int("LINK_RECORD_TTL_DAYS", 0)
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/bot.db").strip()
PORT = env_int("PORT", 10000)
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin").strip()
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()


def validate_config() -> None:
    missing = []
    if API_ID <= 0:
        missing.append("API_ID")
    if not API_HASH:
        missing.append("API_HASH")
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    if not (1 <= MAX_FILE_GB <= 4):
        raise RuntimeError("MAX_FILE_GB must be between 1 and 4")
    if LINK_RECORD_TTL_DAYS < 0:
        raise RuntimeError("LINK_RECORD_TTL_DAYS cannot be negative")
    if FILEBEE_UPLOAD_URL and not FILEBEE_UPLOAD_URL.startswith("https://"):
        raise RuntimeError("FILEBEE_UPLOAD_URL must be an HTTPS endpoint")
    if not FILEBEE_FILE_FIELD:
        raise RuntimeError("FILEBEE_FILE_FIELD cannot be empty")
