"""Faction-scoped retal matching and adaptive live-chain warning decisions."""

from __future__ import annotations

from dataclasses import dataclass


WINNING_RESULTS = frozenset(("Attacked", "Mugged", "Hospitalized", "Special"))


def _valid_response(payload, field):
    if not isinstance(payload, dict):
        raise ValueError(f"Torn returned an invalid {field} response.")
    if payload.get("error"):
        error = payload["error"]
        raise ValueError(f"Torn API error: {error}")
    if field not in payload:
        raise ValueError(f"Torn response did not include {field}.")
    return payload[field]


def normalize_attacks(payload):
    raw = _valid_response(payload, "attacks")
    if isinstance(raw, dict):
        entries = raw.items()
    elif isinstance(raw, list):
        entries = ((None, item) for item in raw)
    else:
        raise ValueError("Torn attacks response must be a mapping or a list.")
    attacks = []
    for key, item in entries:
        if not isinstance(item, dict):
            raise ValueError("Torn returned an invalid attack.")
        attacker = item.get("attacker") or {}
        defender = item.get("defender") or {}
        attacker_faction = attacker.get("faction") or {}
        defender_faction = defender.get("faction") or {}
        attack_id = item.get("id") or key
        started = int(item.get("timestamp_started", item.get("started", 0)))
        ended = int(item.get("timestamp_ended", item.get("ended", 0)))
        if not attack_id or started <= 0 or ended < started:
            raise ValueError("Torn returned an attack without a valid ID or timestamps.")
        attacks.append({
            "id": str(attack_id),
            "started": started,
            "ended": ended,
            "attacker_id": int(item.get("attacker_id", attacker.get("id")) or 0),
            "attacker_name": str(item.get("attacker_name", attacker.get("name")) or ""),
            "attacker_faction": int(item.get("attacker_faction", attacker_faction.get("id")) or 0),
            "attacker_faction_name": str(
                item.get("attacker_factionname", attacker_faction.get("name")) or "No faction"
            ),
            "defender_id": int(item.get("defender_id", defender.get("id")) or 0),
            "defender_name": str(item.get("defender_name", defender.get("name")) or "Unknown defender"),
            "defender_faction": int(item.get("defender_faction", defender_faction.get("id")) or 0),
            "stealthed": bool(item.get("stealthed", item.get("is_stealthed", False))),
            "ranked_war": bool(item.get("is_ranked_war", item.get("ranked_war", False))),
            "result": str(item.get("result") or ""),
            "retaliation": (item.get("modifiers") or {}).get("retaliation"),
        })
    return sorted(attacks, key=lambda attack: (attack["ended"], attack["id"]))


class RetalTracker:
    def __init__(self, gateway, repository):
        self.gateway = gateway
        self.repository = repository

    def fetch_attacks(self, tag, since, now):
        """Walk all pages before advancing the cursor, including high-activity periods."""
        attacks = {}
        until = now
        while until >= since:
            page = normalize_attacks(self.gateway.faction_attacks(
                pool=tag, from_timestamp=since, to_timestamp=until, limit=100, sort="DESC",
            ))
            for attack in page:
                attacks[attack["id"]] = attack
            if len(page) < 100:
                break
            oldest = min(attack["started"] for attack in page)
            if oldest >= until:
                raise ValueError("Attack pagination could not advance; retal cursor was not updated.")
            # Keep the boundary second so attacks sharing a timestamp are not silently skipped.
            until = oldest
        return sorted(attacks.values(), key=lambda attack: (attack["ended"], attack["id"]))

    def check(self, faction, mode, since, now, activated_at):
        pending_since = self.repository.pending_since(faction.tag)
        fetch_since = min(since, now - 300)
        if pending_since is not None:
            fetch_since = min(fetch_since, pending_since)
        attacks = self.fetch_attacks(faction.tag, max(0, fetch_since - 2), now)
        for attack in attacks:
            if (
                attack["defender_faction"] == faction.faction_id
                and attack["attacker_faction"] != faction.faction_id
                and attack["attacker_id"] > 0
                and attack["attacker_name"].strip()
                and not attack["stealthed"]
                and attack["ended"] >= activated_at
                and (mode == "all" or attack["ranked_war"])
            ):
                self.repository.record_incoming(faction.tag, attack)
            if (
                attack["attacker_faction"] == faction.faction_id
                and attack["result"] in WINNING_RESULTS
                and attack["retaliation"] == 1
            ):
                self.repository.fulfill(faction.tag, attack)
        self.repository.expire(faction.tag, now)


@dataclass(frozen=True)
class ChainWatchConfig:
    minimum: int = 10
    warning: int = 120
    urgent: int = 60
    final: int = 30

    def __post_init__(self):
        if self.minimum < 1 or not 0 < self.final < self.urgent < self.warning < 300:
            raise ValueError("Use minimum >= 1 and 0 < final < urgent < warning < 300 seconds.")


def evaluate_chain(payload, config, previous, now):
    """Return (warning stage or None, durable next state, next poll delay)."""
    chain = _valid_response(payload, "chain")
    if not isinstance(chain, dict):
        raise ValueError("Torn response did not include a valid chain object.")
    required = ("current", "timeout", "start", "cooldown")
    if any(field not in chain for field in required):
        raise ValueError("Torn chain response is missing timer fields.")
    current, timeout, start, cooldown = (int(chain[field]) for field in required)
    if min(current, timeout, start, cooldown) < 0:
        raise ValueError("Torn returned negative chain timer values.")
    if current < config.minimum or timeout == 0 or cooldown > 0:
        return None, {"start": start, "deadline": 0, "stage": 0}, 240
    deadline = now + timeout
    previous = previous or {}
    reset = start != previous.get("start") or deadline > previous.get("deadline", 0) + 5
    stage = 0 if reset else int(previous.get("stage", 0))
    thresholds = (config.warning, config.urgent, config.final)
    reached = sum(timeout < threshold for threshold in thresholds)
    warning = reached if reached > stage else None
    stage = max(stage, reached)
    state = {"start": start, "deadline": deadline, "stage": stage}
    intervals = (240, 60, 30, 15)
    delay = intervals[stage]
    if stage < 3:
        delay = min(delay, max(1, timeout - thresholds[stage] + 1))
    return warning, state, delay
