"""Pure helpers for organized-crime payout and participation tracking."""

from __future__ import annotations

DAY = 86400


def as_list(value):
    if isinstance(value, dict):
        return list(value.values())
    return list(value or [])


def crime_participants(crime):
    users = set()
    for slot in crime.get("slots") or []:
        user = slot.get("user")
        user_id = user.get("id") if isinstance(user, dict) else slot.get("user_id")
        if user_id:
            users.add(int(user_id))
    return users


def crime_paid_at(crime):
    payout = (crime.get("rewards") or {}).get("payout")
    if isinstance(payout, dict) and payout.get("paid_at"):
        return int(payout["paid_at"])
    return None


def needs_payout(crime):
    """Successful crimes with a cash reward should eventually be paid out."""
    if str(crime.get("status") or "").lower() != "successful" or not crime.get("executed_at"):
        return False
    return int((crime.get("rewards") or {}).get("money") or 0) > 0


def normalize_members(payload):
    members = []
    for member in as_list((payload or {}).get("members")):
        if not member.get("id"):
            continue
        members.append({
            "id": int(member["id"]),
            "name": str(member.get("name") or member["id"]),
            "is_in_oc": bool(member.get("is_in_oc")),
            "days_in_faction": int(member.get("days_in_faction") or 0),
        })
    return members


def last_crime_times(crimes):
    """Latest executed_at per participating user."""
    latest = {}
    for crime in crimes:
        executed_at = int(crime.get("executed_at") or 0)
        if not executed_at:
            continue
        for user_id in crime_participants(crime):
            latest[user_id] = max(latest.get(user_id, 0), executed_at)
    return latest


def format_duration(seconds):
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, DAY)
    hours = rem // 3600
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {(rem % 3600) // 60}m"
