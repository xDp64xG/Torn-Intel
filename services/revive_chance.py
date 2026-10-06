"""Optional target-key estimates using the target's incoming revive history."""

from __future__ import annotations

import time
from dataclasses import dataclass

from services.faction_alerts import _torn_request_json
from services.revive_operations import estimate_contract_chance


@dataclass(frozen=True)
class ReviveChanceEstimate:
    chance: float | None
    checked_at: int
    successes: int | None = None
    reason: str | None = None

    def text(self) -> str:
        if self.chance is None:
            return f"Unavailable: {self.reason}"
        warning = "\nWarning: estimated chance is 50% or lower." if self.chance <= 50 else ""
        return (
            f"Rough estimate: {self.chance:.2f}% for a skill-100 reviver.\n"
            f"Successful revives received in the previous 24h: {self.successes}.\n"
            "Based on the target's personal incoming logs and a community model, "
            "not a live Torn quote. Current ED effects are not included."
            f"\nAs of <t:{self.checked_at}:f>.{warning}"
        )


def fetch_received_revive_timestamps(
    api_key: str, target_id: int, base_url: str, comment: str, now: int,
) -> list[int]:
    since = now - 86400
    until = now
    seen: set[int] = set()
    successes: list[int] = []
    for _ in range(100):
        payload = _torn_request_json(
            "v2/user/revives",
            {
                "key": api_key, "comment": comment, "filters": "incoming",
                "from": since, "to": until, "sort": "DESC", "limit": 100,
            },
            base_url,
        )
        rows = payload.get("revives")
        if not isinstance(rows, list):
            raise ValueError("Torn did not return an incoming revive list.")
        timestamps = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("target"), dict):
                raise ValueError("Torn returned an invalid incoming revive.")
            try:
                revive_id = int(row["id"])
                timestamp = int(row["timestamp"])
                received_by = int(row["target"]["id"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("Torn returned a revive without a valid ID, target or timestamp.") from None
            if revive_id <= 0 or timestamp <= 0 or received_by != target_id:
                raise ValueError("Torn returned a revive that does not belong to the target.")
            if not since <= timestamp <= until:
                raise ValueError("Torn returned a revive outside the requested history window.")
            result = str(row.get("result") or "").lower()
            if result not in ("success", "failure", "failed"):
                raise ValueError("Torn returned a revive with an unknown result.")
            timestamps.append(timestamp)
            if revive_id not in seen:
                seen.add(revive_id)
                if result == "success" and timestamp > since:
                    successes.append(timestamp)
        if len(rows) < 100:
            return successes
        oldest = min(timestamps)
        # Keep the boundary second to avoid skipping revives with equal timestamps.
        if oldest >= until:
            raise ValueError("Incoming revive pagination stalled; complete history is unavailable.")
        until = oldest
    raise ValueError("Incoming revive history exceeded the pagination limit.")


class ReviveChanceTracker:
    def __init__(self, store, settings, logger):
        self.store = store
        self.settings = settings
        self.logger = logger

    def estimate(self, target_id: int, now: int | None = None) -> ReviveChanceEstimate:
        now = int(time.time()) if now is None else int(now)
        if target_id <= 0:
            raise ValueError("Use a positive Torn target ID.")
        try:
            api_key = self.store.get_user_api_key_for_torn_id(target_id)
            if api_key is None:
                return ReviveChanceEstimate(None, now, reason="the target has not submitted an API key.")
            timestamps = fetch_received_revive_timestamps(
                api_key, target_id, self.settings.base_url,
                getattr(self.settings, "comment", "Torn Intel"), now,
            )
        except (ValueError, RuntimeError) as exc:
            self.logger.warning(f"Revive chance unavailable for Torn user {target_id}: {exc}")
            return ReviveChanceEstimate(None, now, reason=str(exc))
        return ReviveChanceEstimate(estimate_contract_chance(100, timestamps, now), now, len(timestamps))
