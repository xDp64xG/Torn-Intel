"""
config/settings.py

Single source of truth for configuration.
Everything else pulls values from a Settings instance,
never from os.environ or hardcoded constants directly.

Loads configuration from:
1. .env file (if it exists)
2. Environment variables
3. Defaults
"""

from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Load .env file from project root
ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings:

    def __init__(self):

        # Support multiple API keys for rate limit distribution
        # Can be separated by comma in env var: KEY1,KEY2,KEY3
        api_keys_env = os.environ.get("TORN_API_KEYS", "")
        api_key_single = os.environ.get("TORN_API_KEY", "")
        
        if api_keys_env:
            self.api_keys = [k.strip() for k in api_keys_env.split(",") if k.strip()]
        elif api_key_single:
            self.api_keys = [api_key_single]
        else:
            # Default for development
            self.api_keys = ['XwEyLp4K1Y4ZFSMr']
        
        # Use first key by default, but API key manager will rotate
        self.api_key = self.api_keys[0] if self.api_keys else ""

        self.base_url = os.environ.get("TORN_API_BASE_URL", "https://api.torn.com")

        # Request handling
        self.request_delay = float(os.environ.get("TORN_REQUEST_DELAY", "0.6"))
        self.request_timeout = int(os.environ.get("TORN_REQUEST_TIMEOUT", "30"))
        
        # Rate limit retry settings
        self.max_retries = int(os.environ.get("TORN_MAX_RETRIES", "5"))
        self.retry_backoff_base = int(os.environ.get("TORN_RETRY_BACKOFF_BASE", "2"))
        self.rate_limit_error_code = int(os.environ.get("TORN_RATE_LIMIT_ERROR_CODE", "5"))
        retry_schedule_env = os.environ.get("TORN_RATE_LIMIT_RETRY_SCHEDULE", "10,20,30,60")
        self.rate_limit_retry_schedule = [
            int(v.strip())
            for v in retry_schedule_env.split(",")
            if v.strip().isdigit()
        ] or [10, 20, 30, 60]

        self.comment = os.environ.get("TORN_COMMENT", "TornIntel")

        # Faction ID — used to filter reports to your faction members only
        faction_id_env = os.environ.get("TORN_FACTION_ID", "")
        self.faction_id = int(faction_id_env) if faction_id_env else None

        # Database path
        db_path = os.environ.get("TORN_DATABASE_PATH", "data/tornintel.db")
        if db_path.startswith("/"):
            # Absolute path
            self.database_path = Path(db_path)
        else:
            # Relative to project root
            self.database_path = ROOT / db_path

        self.default_page_size = int(os.environ.get("TORN_DEFAULT_PAGE_SIZE", "100"))

        # Local revive request listener
        self.revive_listener_host = os.environ.get("TORN_REVIVE_LISTENER_HOST", "127.0.0.1")
        self.revive_listener_port = int(os.environ.get("TORN_REVIVE_LISTENER_PORT", "8765"))