"""
Parse OC 2.0 slot payloads into normalized rows.
"""

import time


class CrimeParser:

    ACTIVE_STATUSES = {"recruiting", "planning"}

    @staticmethod
    def parse_slots(response, member_names=None, allowed_statuses=None, item_names=None):
        """
        Parse recruiting/planning slots with assigned users and item requirements.
        """
        now = int(time.time())
        parsed = []

        raw_crimes = response.get("crimes", []) if isinstance(response, dict) else []

        if isinstance(raw_crimes, dict):
            iterable = raw_crimes.values()
        else:
            iterable = raw_crimes

        member_names = member_names or {}
        item_names = item_names or {}
        if allowed_statuses is None:
            allowed = {s.lower() for s in CrimeParser.ACTIVE_STATUSES}
        else:
            allowed = {str(s).lower() for s in allowed_statuses}
        allow_all = "*" in allowed

        for crime in iterable:
            if not isinstance(crime, dict):
                continue

            status = str(crime.get("status", "")).strip()
            if not allow_all and status.lower() not in allowed:
                continue

            crime_id = int(crime.get("id") or 0)
            crime_name = crime.get("name") or "Unknown"
            difficulty = int(crime.get("difficulty") or 0)

            for slot_index, slot in enumerate(crime.get("slots", []) or []):
                user = slot.get("user") or {}
                item = slot.get("item_requirement") or {}

                user_id = int(user.get("id") or 0)
                item_id = int(item.get("id") or 0)

                # Active crime slots require item requirements for auditing,
                # but completed crimes may not expose item_requirement.
                if item_id <= 0 and status.lower() in CrimeParser.ACTIVE_STATUSES:
                    continue

                # Keep unassigned active slots (user_id=0) when they already
                # have an item requirement so audit can forecast stock needs.
                if user_id <= 0 and not (
                    status.lower() in CrimeParser.ACTIVE_STATUSES and item_id > 0
                ):
                    continue

                position = slot.get("position") or "Unknown"
                cpr = int(slot.get("checkpoint_pass_rate") or 0)

                parsed.append(
                    {
                        "history_key": (
                            f"{crime_id}:{status}:{position}:{slot_index}:{user_id}:{item_id}:{cpr}"
                        ),
                        "slot_key": f"{crime_id}:{position}:{slot_index}:{user_id}:{item_id}",
                        "crime_id": crime_id,
                        "crime_name": crime_name,
                        "status": status,
                        "difficulty": difficulty,
                        "slot_position": position,
                        "user_id": user_id,
                        "user_name": (
                            user.get("name")
                            or member_names.get(user_id)
                            or member_names.get(str(user_id))
                            or ("Unassigned" if user_id <= 0 else f"User {user_id}")
                        ),
                        "checkpoint_pass_rate": cpr,
                        "required_item_id": item_id,
                        "required_item_name": (
                            item.get("name")
                            or item_names.get(item_id)
                            or item_names.get(str(item_id))
                            or (f"Item {item_id}" if item_id > 0 else "-")
                        ),
                        "item_is_available": 1 if item.get("is_available") else 0,
                        "item_is_reusable": 1 if item.get("is_reusable") else 0,
                        "updated_at": now,
                    }
                )

        return parsed

    @staticmethod
    def parse_members(response):
        """
        Parse current faction roster from faction basic payload.
        """
        now = int(time.time())
        parsed = []

        if not isinstance(response, dict):
            return parsed

        members = response.get("members", {})
        if isinstance(members, dict):
            iterable = members.items()
        elif isinstance(members, list):
            iterable = [
                (member.get("id"), member)
                for member in members
                if isinstance(member, dict)
            ]
        else:
            iterable = []

        for user_id_raw, payload in iterable:
            if not isinstance(payload, dict):
                continue

            user_id = int(payload.get("id") or user_id_raw or 0)
            if user_id <= 0:
                continue

            parsed.append(
                {
                    "user_id": user_id,
                    "user_name": payload.get("name") or f"User {user_id}",
                    "position": payload.get("position") or "",
                    "is_in_oc": (
                        1 if payload.get("is_in_oc") is True
                        else 0 if payload.get("is_in_oc") is False
                        else None
                    ),
                    "last_action": int(payload.get("last_action", {}).get("timestamp", 0) or 0)
                    if isinstance(payload.get("last_action"), dict)
                    else int(payload.get("last_action") or 0),
                    "updated_at": now,
                }
            )

        return parsed

    @staticmethod
    def parse_cpr_rows(slots):

        now = int(time.time())
        rows = []

        for slot in slots:
            if int(slot.get("user_id") or 0) <= 0:
                continue

            cpr_key = f"{slot['user_id']}:{slot['difficulty']}:{str(slot['slot_position']).lower()}"
            rows.append(
                {
                    "cpr_key": cpr_key,
                    "user_id": int(slot["user_id"]),
                    "user_name": slot["user_name"],
                    "crime_level": int(slot["difficulty"]),
                    "position": slot["slot_position"],
                    "cpr": int(slot["checkpoint_pass_rate"] or 0),
                    "updated_at": now,
                }
            )

        return rows
