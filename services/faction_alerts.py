"""Faction armoury stock alerts and overdose tracking helpers."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _torn_request_json(path: str, params: dict, base_url: str, timeout: int = 20):
    base = str(base_url or "https://api.torn.com").rstrip("/")
    if base.lower().endswith("/v2"):
        base = base[:-3]
    request = Request(
        f"{base}/{path.lstrip('/')}?{urlencode(params)}",
        headers={"User-Agent": "TornIntel-DiscordBot/1.0", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except HTTPError as exc:
        raise ValueError(f"Torn API returned HTTP {exc.code}.") from None
    except Exception as exc:
        raise ValueError(f"Could not reach Torn API ({type(exc).__name__}).") from None
    if not isinstance(payload, dict):
        raise ValueError("Torn returned an invalid API response.")
    error = payload.get("error")
    if error:
        raise ValueError(
            f"Torn API error {error.get('code', '?')}: {error.get('error', 'request rejected')}"
        )
    return payload


def fetch_user_od_count(api_key: str, user_id: int, base_url: str, comment: str = "TornIntel") -> int:
    params = {"cat": "drugs", "key": api_key, "comment": comment}
    payload = _torn_request_json(
        f"v2/user/{int(user_id)}/personalstats",
        params,
        base_url,
    )
    count = _find_od_count(payload)
    if count is not None:
        return count

    v2_fields = ", ".join(_response_field_paths(payload)[:12]) or "none"
    v1_payload = _torn_request_json(
        f"user/{int(user_id)}/",
        {"selections": "personalstats", **params},
        base_url,
    )
    count = _find_od_count(v1_payload)
    if count is None:
        v1_fields = ", ".join(_response_field_paths(v1_payload)[:12]) or "none"
        raise ValueError(
            "Torn responses did not contain the overdosed personal stat "
            f"(v2 fields: {v2_fields}; v1 fields: {v1_fields})."
        )
    if count < 0:
        raise ValueError("Torn returned an invalid overdose count.")
    return count


def _find_od_count(payload: dict) -> int | None:
    pending = [(payload, False)]
    while pending:
        current, selected_stat_context = pending.pop()
        if isinstance(current, list):
            if selected_stat_context and len(current) == 1:
                count = _coerce_od_count(current[0])
                if count is not None:
                    return count
            if selected_stat_context and len(current) == 2 and str(current[0]).lower() in (
                "drugoverdoses", "overdosed"
            ):
                count = _coerce_od_count(current[1])
                if count is not None:
                    return count
            pending.extend((item, selected_stat_context) for item in current if isinstance(item, (dict, list)))
            continue
        if not isinstance(current, dict):
            continue
        for field in ("overdoses", "drugoverdoses", "overdosed"):
            value = current.get(field)
            count = _coerce_od_count(value)
            if count is not None:
                return count
        stat_name = str(current.get("stat") or current.get("name") or current.get("key") or "").lower()
        if stat_name in ("overdoses", "drugoverdoses", "overdosed"):
            for value_key in ("value", "count", "amount"):
                count = _coerce_od_count(current.get(value_key))
                if count is not None:
                    return count
        for key, value in current.items():
            if isinstance(value, (dict, list)):
                pending.append((value, selected_stat_context or str(key).lower() == "personalstats"))
    return None


def _coerce_od_count(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _response_field_paths(payload: dict, prefix: str = "", depth: int = 0) -> list[str]:
    if not isinstance(payload, dict) or depth >= 4:
        return []
    paths = []
    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.append(f"{path} ({type(value).__name__})")
        if isinstance(value, dict):
            paths.extend(_response_field_paths(value, path, depth + 1))
        elif isinstance(value, list):
            if not value:
                paths.append(f"{path}[] (empty)")
            for index, item in enumerate(value[:5]):
                item_path = f"{path}[{index}]"
                if isinstance(item, dict):
                    paths.extend(_response_field_paths(item, item_path, depth + 1))
                else:
                    paths.append(f"{item_path} ({type(item).__name__})")
    return paths


def validate_user_api_key(
    api_key: str,
    expected_user_id: int,
    expected_faction_id: int,
    base_url: str,
    comment: str = "TornIntel",
) -> dict:
    """Confirm a key belongs to the linked user and can read the OD stat."""
    basic = _torn_request_json(
        "user/",
        {"selections": "basic", "key": api_key, "comment": comment},
        base_url,
    )
    identity = basic.get("basic") or basic.get("profile") or basic
    try:
        actual_user_id = int(
            identity.get("player_id") or identity.get("user_id") or identity.get("id") or 0
        )
    except (TypeError, ValueError):
        actual_user_id = 0
    if actual_user_id != int(expected_user_id):
        raise ValueError("That API key does not belong to the Torn account linked with /add.")

    faction_response = _torn_request_json(
        "v2/user/faction",
        {"key": api_key, "comment": comment},
        base_url,
    )
    faction = faction_response.get("faction") or faction_response
    try:
        actual_faction_id = int(faction.get("id") or 0)
    except (TypeError, ValueError):
        actual_faction_id = 0
    if actual_faction_id != int(expected_faction_id):
        raise ValueError("That Torn account is not currently a member of the selected faction.")

    od_count = fetch_user_od_count(api_key, expected_user_id, base_url, comment)
    return {
        "torn_user_id": actual_user_id,
        "user_name": str(identity.get("name") or f"User {actual_user_id}"),
        "od_count": od_count,
    }


def normalize_faction_inventory(response: dict) -> dict[int, dict]:
    if not isinstance(response, dict) or response.get("error"):
        raise ValueError("Torn returned an invalid faction inventory response.")
    inventory = response.get("inventory")
    if not isinstance(inventory, list):
        raise ValueError("Faction inventory response did not include an inventory list.")
    normalized = {}
    for item in inventory:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id") or 0)
            amount = int(item.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if item_id > 0 and amount >= 0:
            normalized[item_id] = {
                "item_name": str(item.get("name") or f"Item {item_id}"),
                "amount": amount,
            }
    return normalized


def normalize_faction_contributors(response: dict) -> list[dict]:
    if not isinstance(response, dict) or response.get("error"):
        raise ValueError("Torn returned an invalid faction contributors response.")
    contributors = response.get("contributors")
    if not isinstance(contributors, list):
        raise ValueError("Faction contributors response did not include a contributors list.")
    normalized = []
    for member in contributors:
        if not isinstance(member, dict):
            continue
        try:
            user_id = int(member.get("id") or 0)
            od_count = int(member.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if user_id > 0 and od_count >= 0:
            normalized.append({
                "torn_user_id": user_id,
                "user_name": str(member.get("username") or f"User {user_id}"),
                "od_count": od_count,
            })
    return normalized


class ArmouryStockTracker:
    """Fetch once per configured category, then check every item threshold."""

    def __init__(self, gateway, store):
        self.gateway = gateway
        self.store = store

    def check_faction(self, faction) -> list[dict]:
        thresholds = self.store.list_armoury_thresholds(faction.faction_id)
        if not thresholds:
            return []

        by_category = {}
        for threshold in thresholds:
            by_category.setdefault(threshold["item_category"], []).append(threshold)

        alerts = []
        for category, category_thresholds in by_category.items():
            response = self.gateway.faction_inventory(
                category=category,
                pool=faction.tag,
            )
            inventory = normalize_faction_inventory(response)
            for item in category_thresholds:
                current = inventory.get(int(item["item_id"]))
                amount = current["amount"] if current else 0
                if amount <= int(item["threshold"]):
                    alerts.append({
                        "item_id": int(item["item_id"]),
                        "item_name": (current or {}).get("item_name") or item["item_name"],
                        "amount": amount,
                        "threshold": int(item["threshold"]),
                        "category": category,
                    })
        return alerts


class OverdoseTracker:
    """Check member keys first, then use one faction contributors request as fallback."""

    def __init__(self, gateway, store, settings, logger=None):
        self.gateway = gateway
        self.store = store
        self.settings = settings
        self.logger = logger

    def _read_personal_stat(self, member):
        try:
            count = fetch_user_od_count(
                member["api_key"],
                int(member["torn_user_id"]),
                self.settings.base_url,
                getattr(self.settings, "comment", "TornIntel"),
            )
            return int(member["torn_user_id"]), count
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    f"OD personal key check failed for Torn user {member.get('torn_user_id')}: {type(exc).__name__}"
                )
            return int(member["torn_user_id"]), None

    def check_faction(self, faction) -> list[dict]:
        try:
            members = self.store.get_user_api_keys_for_faction(faction.faction_id)
        except RuntimeError as exc:
            if self.logger:
                self.logger.warning(f"OD personal keys unavailable for [{faction.tag}]: {exc}")
            members = []
        members_by_id = {int(member["torn_user_id"]): member for member in members}
        processed = set()
        alerts = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = executor.map(self._read_personal_stat, members)
            for user_id, current_count in results:
                if current_count is None:
                    continue
                processed.add(user_id)
                baseline = self.store.get_od_baseline(faction.faction_id, user_id)
                member = members_by_id.get(user_id, {})
                user_name = str(member.get("user_name") or f"User {user_id}")
                previous = int(baseline["last_known_od_count"]) if baseline else None
                if previous is not None and current_count > previous:
                    alerts.append({
                        "torn_user_id": user_id,
                        "user_name": user_name,
                        "previous_count": previous,
                        "od_count": current_count,
                        "delta": current_count - previous,
                        "source": "personal key",
                    })
                self.store.set_od_baseline(
                    faction.faction_id, faction.tag, user_id, user_name, current_count
                )

        try:
            response = self.gateway.faction_contributors(
                stat="drugoverdoses",
                pool=faction.tag,
            )
            contributors = normalize_faction_contributors(response)
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    f"OD faction fallback failed for [{faction.tag}]: {type(exc).__name__}"
                )
            return alerts
        for contributor in contributors:
            user_id = contributor["torn_user_id"]
            if user_id in processed:
                continue
            current_count = contributor["od_count"]
            user_name = contributor["user_name"]
            baseline = self.store.get_od_baseline(faction.faction_id, user_id)
            if baseline is None:
                self.store.set_od_baseline(
                    faction.faction_id, faction.tag, user_id, user_name, current_count
                )
                continue
            previous = int(baseline["last_known_od_count"])
            if current_count > previous:
                alerts.append({
                    "torn_user_id": user_id,
                    "user_name": user_name,
                    "previous_count": previous,
                    "od_count": current_count,
                    "delta": current_count - previous,
                    "source": "faction fallback",
                })
            self.store.set_od_baseline(
                faction.faction_id, faction.tag, user_id, user_name, current_count
            )
        return alerts