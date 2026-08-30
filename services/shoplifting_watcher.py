"""Poll Torn shoplifting availability and notify Discord when Jewelry Store is clear."""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests


class ShopliftingWatcher:
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
        was_clear = False
        try:
            while self._read_state().get("enabled"):
                try:
                    is_clear = self._jewelry_store_is_clear(self._fetch_shoplifting(api_key))
                    if is_clear and not was_clear:
                        self._send_alert(webhook_url, mention)
                    was_clear = is_clear
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

    @staticmethod
    def _jewelry_store_is_clear(payload):
        shoplifting = payload.get("shoplifting", {}) if isinstance(payload, dict) else {}
        obstacles = shoplifting.get("jewelry_store", [])
        return len(obstacles) == 2 and all(obstacle.get("disabled") is True for obstacle in obstacles)

    @staticmethod
    def alert_message(message=None):
        return str(message).strip() if message and str(message).strip() else "Jewelry Store is clear for shoplifting."

    def _send_alert(self, webhook_url, mention):
        prefix = f"{mention} " if mention else ""
        response = requests.post(
            webhook_url,
            json={
                "content": f"{prefix}Jewelry Store is clear for shoplifting.",
                "allowed_mentions": {"parse": ["users", "roles"]},
            },
            timeout=self.settings.request_timeout,
        )
        response.raise_for_status()
        self.logger.success("Sent Jewelry Store shoplifting alert.")

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