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
import re

try:
    from dotenv import load_dotenv
except ImportError as exc:
    raise SystemExit(
        "python-dotenv is not installed for this interpreter. "
        "On Ubuntu run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt, "
        "then start the bot with .venv/bin/python main.py ..."
    ) from exc

ROOT = Path(__file__).resolve().parent.parent

# utf-8-sig strips the BOM Windows editors (Notepad) add, which otherwise corrupts the first key.
ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, encoding="utf-8-sig")
else:
    print(f"Warning: {ENV_FILE} not found; using environment variables and defaults only.")


# Discord role that identifies members of each faction; override with FACTION_<TAG>_ROLE.
DEFAULT_FACTION_ROLES = {
    "GTS": "Saints",
    "GTH": "Spartan",
}


class FactionConfig:
    """Configuration for a specific tracked faction."""

    def __init__(self, tag: str, name: str = "", faction_id: int | None = None, api_keys: list[str] | None = None, role_name: str = ""):
        self.tag = tag.upper().strip()
        self.name = name.strip() or self.tag
        self.faction_id = int(faction_id) if faction_id else None
        self.api_keys = [str(k).strip() for k in (api_keys or []) if str(k).strip()]
        self.role_name = (
            role_name.strip()
            or os.environ.get(f"FACTION_{self.tag}_ROLE", "").strip()
            or DEFAULT_FACTION_ROLES.get(self.tag, "")
        )
        # Discord role pinged for this faction's bank requests; falls back to TORN_DISCORD_BANKER_ROLE.
        self.banker_role_name = os.environ.get(f"FACTION_{self.tag}_BANKER_ROLE", "").strip()

    def __repr__(self):
        return f"<FactionConfig tag={self.tag} id={self.faction_id} name={self.name} keys={len(self.api_keys)}>"


class Settings:

    def __init__(self):

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

        # Global and Shoplifting API key pools
        global_keys_env = os.environ.get("GLOBAL_API_KEYS", "") or os.environ.get("TORN_GLOBAL_API_KEYS", "")
        shoplifting_keys_env = os.environ.get("TORN_SHOPLIFTING_API_KEYS", "")
        shoplifting_key_single = os.environ.get("TORN_SHOPLIFTING_API_KEY", "")

        global_list = []
        if global_keys_env:
            global_list.extend([k.strip() for k in global_keys_env.split(",") if k.strip()])
        if shoplifting_keys_env:
            global_list.extend([k.strip() for k in shoplifting_keys_env.split(",") if k.strip()])
        if shoplifting_key_single and shoplifting_key_single not in global_list:
            global_list.append(shoplifting_key_single)

        self.global_api_keys = global_list
        self.shoplifting_api_key = shoplifting_key_single or (self.global_api_keys[0] if self.global_api_keys else "")
        self.shoplifting_webhook_url = os.environ.get("TORN_SHOPLIFTING_WEBHOOK_URL", "").strip()
        self.shoplifting_mention = os.environ.get("TORN_SHOPLIFTING_MENTION", "").strip()
        self.shoplifting_poll_seconds = int(os.environ.get("TORN_SHOPLIFTING_POLL_SECONDS", "30"))

        # Factions mapping (e.g. GTS, GTH)
        self.factions = self._parse_factions()

        # Primary / default faction
        if "GTS" in self.factions:
            self.default_faction = self.factions["GTS"]
        elif self.factions:
            self.default_faction = next(iter(self.factions.values()))
        else:
            default_gts = FactionConfig(
                tag="GTS",
                name="Glory to Saints",
                faction_id=None,
                api_keys=['XwEyLp4K1Y4ZFSMr'],
            )
            self.factions["GTS"] = default_gts
            self.default_faction = default_gts

        # Legacy compatibility properties
        self.faction_id = self.default_faction.faction_id
        self.api_keys = list(self.default_faction.api_keys)
        self.api_key = self.api_keys[0] if self.api_keys else ""

        # Database path
        db_path = os.environ.get("TORN_DATABASE_PATH", "data/tornintel.db")
        if db_path.startswith("/"):
            self.database_path = Path(db_path)
        else:
            self.database_path = ROOT / db_path

        self.default_page_size = int(os.environ.get("TORN_DEFAULT_PAGE_SIZE", "100"))

        # Local revive request listener
        self.revive_listener_host = os.environ.get("TORN_REVIVE_LISTENER_HOST", "127.0.0.1")
        self.revive_listener_port = int(os.environ.get("TORN_REVIVE_LISTENER_PORT", "8765"))

        # Discord bot bridge
        self.discord_bot_token = os.environ.get("TORN_DISCORD_BOT_TOKEN", "").strip()
        self.discord_command_prefix = os.environ.get("TORN_DISCORD_BOT_PREFIX", "!ti").strip() or "!ti"
        guild_id_env = os.environ.get("TORN_DISCORD_GUILD_ID", "").strip()
        self.discord_guild_id = int(guild_id_env) if guild_id_env else None
        self.discord_command_timeout = int(os.environ.get("TORN_DISCORD_COMMAND_TIMEOUT", "180"))
        self.discord_enable_message_content_intent = os.environ.get(
            "TORN_DISCORD_ENABLE_MESSAGE_CONTENT_INTENT", "0"
        ).strip().lower() in ("1", "true", "yes", "on")
        self.discord_banker_role = os.environ.get("TORN_DISCORD_BANKER_ROLE", "Bankers").strip()
        revive_channel_env = os.environ.get("TORN_DISCORD_REVIVE_CHANNEL_ID", "").strip()
        self.discord_revive_channel_id = int(revive_channel_env) if revive_channel_env else None
        self.discord_revive_poll_seconds = int(os.environ.get("TORN_DISCORD_REVIVE_POLL_SECONDS", "20"))
        oc_delay_channel_env = os.environ.get("TORN_DISCORD_OC_DELAY_CHANNEL_ID", "").strip()
        self.discord_oc_delay_channel_id = int(oc_delay_channel_env) if oc_delay_channel_env else None
        self.discord_oc_delay_poll_seconds = int(os.environ.get("TORN_DISCORD_OC_DELAY_POLL_SECONDS", "60"))
        self.discord_attacks_poll_seconds = int(os.environ.get("TORN_DISCORD_ATTACKS_POLL_SECONDS", "15"))
        self.discord_attacks_autosync = os.environ.get(
            "TORN_DISCORD_ATTACKS_AUTOSYNC", "1"
        ).strip().lower() in ("1", "true", "yes", "on")

    #######################################################

    def _parse_factions(self) -> dict[str, FactionConfig]:
        """Discover factions from FACTION_<TAG>_* env vars and legacy fallback."""
        factions: dict[str, FactionConfig] = {}
        tag_pattern = re.compile(r"^FACTION_([A-Za-z0-9]+)_(KEYS|ID|NAME)$")

        discovered_tags = set()
        for env_key in os.environ:
            match = tag_pattern.match(env_key.upper())
            if match:
                discovered_tags.add(match.group(1))

        # Default faction names
        default_names = {
            "GTS": "Glory to Saints",
            "GTH": "Glory to Heroes",
        }

        for tag in discovered_tags:
            keys_raw = os.environ.get(f"FACTION_{tag}_KEYS", "")
            id_raw = os.environ.get(f"FACTION_{tag}_ID", "")
            name_raw = os.environ.get(f"FACTION_{tag}_NAME", "") or default_names.get(tag, tag)

            api_keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
            faction_id = int(id_raw) if id_raw and id_raw.isdigit() else None

            factions[tag] = FactionConfig(
                tag=tag,
                name=name_raw,
                faction_id=faction_id,
                api_keys=api_keys,
            )

        # Legacy TORN_API_KEYS / TORN_FACTION_ID fallback
        legacy_keys_env = os.environ.get("TORN_API_KEYS", "")
        legacy_single_key = os.environ.get("TORN_API_KEY", "")
        legacy_faction_id_env = os.environ.get("TORN_FACTION_ID", "")
        legacy_faction_id = int(legacy_faction_id_env) if legacy_faction_id_env and legacy_faction_id_env.isdigit() else None

        legacy_keys = []
        if legacy_keys_env:
            legacy_keys.extend([k.strip() for k in legacy_keys_env.split(",") if k.strip()])
        elif legacy_single_key:
            legacy_keys.append(legacy_single_key.strip())

        if "GTS" not in factions and (legacy_keys or legacy_faction_id):
            factions["GTS"] = FactionConfig(
                tag="GTS",
                name="Glory to Saints",
                faction_id=legacy_faction_id,
                api_keys=legacy_keys or ['XwEyLp4K1Y4ZFSMr'],
            )
        elif "GTS" in factions:
            if not factions["GTS"].api_keys and legacy_keys:
                factions["GTS"].api_keys = legacy_keys
            if factions["GTS"].faction_id is None and legacy_faction_id:
                factions["GTS"].faction_id = legacy_faction_id

        return factions

    #######################################################

    def get_faction(self, tag_or_id) -> FactionConfig | None:
        """Resolve a FactionConfig by tag (case-insensitive) or integer faction_id."""
        if not tag_or_id:
            return self.default_faction

        query_str = str(tag_or_id).strip().upper()
        if query_str in self.factions:
            return self.factions[query_str]

        if str(tag_or_id).isdigit():
            fid = int(tag_or_id)
            for faction in self.factions.values():
                if faction.faction_id == fid:
                    return faction

        return None

    def get_faction_id(self, tag_or_id) -> int | None:
        faction = self.get_faction(tag_or_id)
        return faction.faction_id if faction else None

    def get_faction_tag(self, tag_or_id) -> str:
        faction = self.get_faction(tag_or_id)
        return faction.tag if faction else (self.default_faction.tag if self.default_faction else "GTS")

    def list_factions(self) -> list[FactionConfig]:
        return list(self.factions.values())