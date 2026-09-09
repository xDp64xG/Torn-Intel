"""Poll Torn shoplifting availability and notify Discord when watched areas open up."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests


class ShopliftingWatcher:
    # trigger "all": alert once every watched obstacle is disabled. trigger "any": alert as soon as one is disabled.
    AREAS = {
        "jewelry_store": {"label": "Jewelry Store", "trigger": "all", "obstacles": ("Three cameras", "One guard")},
        "big_als": {"label": "Big Al's Gun Shop", "trigger": "any", "obstacles": ("Four cameras", "Two guards")},
        "pharmacy": {"label": "Pharmacy", "trigger": "any", "obstacles": ("Three cameras", "Checkpoint")},
        "cyber_force": {"label": "Cyber Force", "trigger": "any", "obstacles": ("Two cameras", "One guard")},
        "super_store": {"label": "Super Store", "trigger": "any", "obstacles": ("Two cameras", "Checkpoint")},
        "tc_clothing": {"label": "TC Clothing", "trigger": "any", "obstacles": ("One camera", "Checkpoint")},
        "bits_n_bobs": {"label": "Bits 'n' Bobs", "trigger": "any", "obstacles": ("Two cameras",)},
        "sallys_sweet_shop": {"label": "Sally's Sweet Shop", "trigger": "any", "obstacles": ("One camera",)},
    }
    TRIGGERS = ("any", "all", "cameras", "guards", "checkpoint")
    # Security kinds are matched against obstacle titles such as "Four cameras" or "Two guards".
    SECURITY_KINDS = {
        "cameras": ("camera",),
        "guards": ("guard",),
        "checkpoint": ("checkpoint",),
    }

    def __init__(self, settings, http_client, logger):
        self.settings = settings
        self.http_client = http_client
        self.logger = logger
        self.state_path = Path(settings.database_path).parent / "shoplifting_watcher.json"

    def start(self, api_key=None, webhook_url=None, mention=None, poll_seconds=None):
        state = self._read_state()
        effective_api_key = api_key or self.settings.shoplifting_api_key or self.settings.api_key
        effective_webhook_url = webhook_url or self.settings.shoplifting_webhook_url
        effective_mention = mention if mention is not None else self.settings.shoplifting_mention
        effective_poll_seconds = max(5, int(poll_seconds or state.get("poll_seconds") or self.settings.shoplifting_poll_seconds))
        if not effective_api_key:
            raise ValueError("shoplifting start requires --api-key or TORN_SHOPLIFTING_API_KEY")
        if not effective_webhook_url:
            raise ValueError("shoplifting start requires --webhook-url or TORN_SHOPLIFTING_WEBHOOK_URL")

        self._write_state({"enabled": True, "poll_seconds": effective_poll_seconds})
        self.logger.info("Shoplifting watcher started. Use 'shoplifting stop' to disable it.")
        self._run(effective_api_key, effective_webhook_url, effective_mention, effective_poll_seconds)

    def stop(self):
        state = self._read_state()
        state["enabled"] = False
        self._write_state(state)
        self.logger.info("Shoplifting watcher disabled.")

    def status(self):
        state = self._read_state()
        enabled = bool(state.get("enabled"))
        return "Shoplifting watcher is enabled." if enabled else "Shoplifting watcher is disabled."

    def _run(self, api_key, webhook_url, mention, poll_seconds):
        area_states = {area: None for area in self.AREAS}
        try:
            while self._read_state().get("enabled"):
                try:
                    payload = self._fetch_shoplifting(api_key)
                    for area in self.AREAS:
                        should_alert, area_states[area], titles = self.evaluate_area(payload, area, area_states[area])
                        if should_alert:
                            self._send_alert(webhook_url, mention, area, titles)
                except Exception as error:
                    self.logger.error(f"Shoplifting watcher poll failed: {error}")
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            self.logger.info("Shoplifting watcher stopped.")

    def _fetch_shoplifting(self, api_key):
        base_url = self.settings.base_url.rstrip("/")
        return self.http_client.get(
            f"{base_url}/torn/",
            params={"key": api_key, "comment": self.settings.comment, "selections": "shoplifting"},
            max_retries=self.settings.max_retries,
            retry_backoff_base=self.settings.retry_backoff_base,
        )

    @classmethod
    def area_label(cls, area):
        return cls.AREAS.get(area, {}).get("label", str(area).replace("_", " ").title())

    @classmethod
    def area_trigger(cls, area, trigger=None):
        requested = str(trigger or "").strip().lower()
        if requested in cls.available_triggers(area):
            return requested
        return cls.AREAS.get(area, {}).get("trigger", "any")

    @staticmethod
    def parse_watch_list(raw):
        """Split a comma/semicolon/newline separated obstacle filter into a tuple of titles."""
        if not raw:
            return ()
        if isinstance(raw, (list, tuple, set)):
            parts = [str(item) for item in raw]
        else:
            parts = re.split(r"[\n,;|]+", str(raw))
        return tuple(part.strip() for part in parts if part.strip())

    @staticmethod
    def _area_obstacles(payload, area):
        shoplifting = payload.get("shoplifting", {}) if isinstance(payload, dict) else {}
        if not isinstance(shoplifting, dict):
            return []
        obstacles = shoplifting.get(area)
        if obstacles is None:
            # Torn returns some area keys with inconsistent casing, e.g. "Bits_n_bobs".
            lookup = {str(key).lower(): value for key, value in shoplifting.items()}
            obstacles = lookup.get(str(area).lower(), [])
        return [obstacle for obstacle in obstacles if isinstance(obstacle, dict)]

    @classmethod
    def obstacle_kind(cls, title):
        text = str(title or "").lower()
        for kind, keywords in cls.SECURITY_KINDS.items():
            if any(keyword in text for keyword in keywords):
                return kind
        return None

    @classmethod
    def area_obstacles(cls, area):
        return cls.AREAS.get(area, {}).get("obstacles", ())

    @classmethod
    def available_triggers(cls, area):
        """Triggers that can actually fire for an area, based on the security it has."""
        obstacles = cls.area_obstacles(area)
        if len(obstacles) < 2:
            return ("any",)
        kinds = []
        for title in obstacles:
            kind = cls.obstacle_kind(title)
            if kind and kind not in kinds:
                kinds.append(kind)
        return ("any", "all", *kinds)

    @classmethod
    def validate_watch_list(cls, area, raw):
        """Return (known titles, unrecognised entries) for an obstacle filter."""
        known = {title.lower(): title for title in cls.area_obstacles(area)}
        titles = []
        unknown = []
        for entry in cls.parse_watch_list(raw):
            match = known.get(entry.lower())
            if match:
                titles.append(match)
            else:
                unknown.append(entry)
        return tuple(titles), tuple(unknown)

    @classmethod
    def trigger_summary(cls, area, trigger):
        label = cls.area_label(area)
        obstacles = cls.area_obstacles(area)
        if trigger == "all":
            return f"Alert once every watched item is down ({' + '.join(obstacles)})"
        if trigger in cls.SECURITY_KINDS:
            matching = [title for title in obstacles if cls.obstacle_kind(title) == trigger]
            return f"Alert only when {' or '.join(matching) or trigger} goes down"
        return f"Alert each time any {label} security goes down"

    @classmethod
    def describe_area(cls, area):
        obstacles = cls.area_obstacles(area)
        lines = [
            f"{cls.area_label(area)} ({area})",
            f"  Security: {', '.join(obstacles) if obstacles else 'unknown'}",
            f"  Default trigger: {cls.area_trigger(area)}",
            "  Triggers:",
        ]
        lines.extend(f"    {trigger} - {cls.trigger_summary(area, trigger)}" for trigger in cls.available_triggers(area))
        return "\n".join(lines)

    @classmethod
    def describe_triggers(cls):
        return (
            "How alerts fire\n"
            "  any        - one alert per security item the moment it goes down, naming it. It will not repeat\n"
            "               while that item stays down, and re-arms once the item comes back up.\n"
            "  all        - a single alert when every watched item is down at the same time. It will not repeat\n"
            "               until the area is secured again.\n"
            "  cameras    - same edge behaviour as any, but only watches the camera item.\n"
            "  guards     - same edge behaviour as any, but only watches the guard item.\n"
            "  checkpoint - same edge behaviour as any, but only watches the checkpoint item.\n"
            "\n"
            "The obstacles option narrows the watch list first, then the trigger is applied to what is left.\n"
            "Changing the trigger or obstacles resets tracking, so the next matching state fires a fresh alert."
        )

    @classmethod
    def watched_obstacles(cls, payload, area, watch=None, kind=None):
        titles = {title.lower() for title in cls.parse_watch_list(watch)}
        obstacles = []
        for obstacle in cls._area_obstacles(payload, area):
            title = str(obstacle.get("title") or "Unnamed obstacle")
            if titles and title.lower() not in titles:
                continue
            if kind and cls.obstacle_kind(title) != kind:
                continue
            obstacles.append((title, obstacle.get("disabled") is True))
        return obstacles

    @classmethod
    def disabled_titles(cls, payload, area, watch=None, kind=None):
        return [title for title, is_disabled in cls.watched_obstacles(payload, area, watch, kind) if is_disabled]

    @classmethod
    def evaluate_area(cls, payload, area, previous_state, trigger=None, watch=None):
        """Return (should_alert, next_state, titles) for one watched area."""
        effective = cls.area_trigger(area, trigger)
        kind = effective if effective in cls.SECURITY_KINDS else None
        obstacles = cls.watched_obstacles(payload, area, watch, kind)
        disabled = [title for title, is_disabled in obstacles if is_disabled]

        if effective == "all":
            is_clear = bool(obstacles) and len(disabled) == len(obstacles)
            return (is_clear and not bool(previous_state)), is_clear, disabled

        previous = set(previous_state or ())
        current = set(disabled)
        newly_disabled = sorted(current - previous)
        return bool(newly_disabled), current, newly_disabled

    @staticmethod
    def _jewelry_store_is_clear(payload):
        obstacles = ShopliftingWatcher._area_obstacles(payload, "jewelry_store")
        return len(obstacles) == 2 and all(obstacle.get("disabled") is True for obstacle in obstacles)

    @classmethod
    def alert_message(cls, message=None, area="jewelry_store", trigger=None):
        if message and str(message).strip():
            return str(message).strip()
        effective = cls.area_trigger(area, trigger)
        if effective == "all":
            return f"{cls.area_label(area)} is clear for shoplifting."
        if effective == "checkpoint":
            return f"{cls.area_label(area)} checkpoint is down."
        if effective in cls.SECURITY_KINDS:
            return f"{cls.area_label(area)} {effective} are down."
        return f"{cls.area_label(area)} has a disabled obstacle."

    @classmethod
    def format_alert(cls, message=None, area="jewelry_store", titles=None, trigger=None):
        text = cls.alert_message(message, area, trigger)
        if titles:
            text = f"{text}\nDisabled: {', '.join(titles)}"
        return text

    def _send_alert(self, webhook_url, mention, area="jewelry_store", titles=None):
        prefix = f"{mention} " if mention else ""
        response = requests.post(
            webhook_url,
            json={
                "content": f"{prefix}{self.format_alert(area=area, titles=titles)}",
                "allowed_mentions": {"parse": ["users", "roles"]},
            },
            timeout=self.settings.request_timeout,
        )
        response.raise_for_status()
        self.logger.success(f"Sent {self.area_label(area)} shoplifting alert.")

    def _read_state(self):
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state), encoding="utf-8")