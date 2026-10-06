"""Logged revive evidence, contract accounting and request eligibility."""

from __future__ import annotations

import math
import time
import uuid

from modules.revives.parser import ReviveParser
from models.revive import Revive, ReviveRequest
from repositories.faction_watch_repository import FactionWatchRepository


def hospital_observation(payload, target_id):
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError(f"Could not read Torn profile: {(payload or {}).get('error') if isinstance(payload, dict) else 'invalid response'}")
    profile = payload.get("profile") or payload
    if not isinstance(profile, dict):
        raise ValueError("Torn returned an invalid profile.")
    status = profile.get("status")
    if not isinstance(status, dict) or not status.get("state"):
        raise ValueError("Torn profile did not include a hospital status.")
    faction = profile.get("faction") or {}
    if not isinstance(faction, dict):
        raise ValueError("Torn returned an invalid profile faction.")
    try:
        faction_id = int(faction.get("faction_id", faction.get("id", 0)) or 0)
    except (TypeError, ValueError):
        raise ValueError("Torn returned an invalid profile faction ID.") from None
    if faction_id < 0:
        raise ValueError("Torn returned an invalid profile faction ID.")
    return {
        "ok": str(status["state"]).lower() == "hospital",
        "target_name": str(profile.get("name") or f"User {target_id}"),
        "state": str(status["state"]),
        "description": str(status.get("description") or status["state"]),
        "faction_id": faction_id,
    }


def estimate_contract_chance(skill, timestamps, now):
    """Apply a linearly decaying 24-hour penalty to the supplied revive skill."""
    skill = float(skill)
    if not math.isfinite(skill) or not 1 <= skill <= 100:
        raise ValueError("Revive skill must be between 1 and 100.")
    recent = [timestamp for timestamp in timestamps if 0 <= now - timestamp < 86400]
    penalty = sum((86400 - (now - timestamp)) / 86400 for timestamp in recent)
    baseline = 90 + skill / 10
    return round(max(0, min(100, baseline - penalty * (8 - skill / 25))), 2)


def revive_payment_text(context, reviver):
    if context["contract_id"]:
        return (
            f"This revive is covered by contract `{context['contract_id']}`. "
            "Payment is handled through the contract; do not pay individually."
        )
    if context["needs_review"]:
        return (
            "Contract coverage could not be confirmed for this completed revive. "
            "Check with the contract administrator before paying individually."
        )
    return f"Please pay {reviver} the agreed regular revive fee."


class ReviveOperations(FactionWatchRepository):
    def __init__(self, database_path, gateway):
        super().__init__(database_path)
        self.gateway = gateway
        with self.connect() as conn:
            for model in (Revive, ReviveRequest):
                definitions = [field.build(name) for name, field in model.fields().items()]
                conn.execute(f"CREATE TABLE IF NOT EXISTS {model.table_name} ({', '.join(definitions)})")
                existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({model.table_name})")}
                for name, field in model.fields().items():
                    if name not in existing:
                        definition = field.build(name).replace("PRIMARY KEY", "").strip()
                        conn.execute(f"ALTER TABLE {model.table_name} ADD COLUMN {definition}")
            conn.executescript("""
                CREATE INDEX IF NOT EXISTS revive_target_time ON revives (target_id, timestamp);
                CREATE TABLE IF NOT EXISTS revive_contracts (
                    contract_id TEXT PRIMARY KEY, provider_tag TEXT NOT NULL,
                    provider_faction_id INTEGER NOT NULL, target_faction_id INTEGER NOT NULL,
                    start_at INTEGER NOT NULL, end_at INTEGER,
                    success_target INTEGER NOT NULL, success_price INTEGER NOT NULL,
                    failure_price INTEGER NOT NULL, created_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discord_revive_details (
                    request_id TEXT PRIMARY KEY, contract_id TEXT,
                    chance REAL, chance_at INTEGER, warning TEXT,
                    payment_dm_status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS revive_log_cursors (
                    faction_tag TEXT PRIMARY KEY, timestamp INTEGER NOT NULL
                );
            """)
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(discord_revive_details)")}
            for name, definition in (
                ("contract_check_status", "TEXT"),
                ("request_target_faction_id", "INTEGER"),
            ):
                if name not in existing:
                    conn.execute(f"ALTER TABLE discord_revive_details ADD COLUMN {name} {definition}")

    def profile(self, target_id):
        if target_id <= 0:
            raise ValueError("Use a positive Torn target ID.")
        if self.gateway is None:
            raise RuntimeError("Torn profile access is unavailable: no Torn gateway configured.")
        payload = self.gateway.user_profile(target_id)
        observation = hospital_observation(payload, target_id)
        profile = payload.get("profile") or payload
        if not isinstance(profile.get("faction"), dict) or not (
            "faction_id" in profile["faction"] or "id" in profile["faction"]
        ):
            raise ValueError("Torn profile did not include a verifiable faction ID.")
        return observation

    def sync(self, faction, now=None):
        now = int(time.time()) if now is None else int(now)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT timestamp FROM revive_log_cursors WHERE faction_tag = ?", (faction.tag,),
            ).fetchone()
            since = max(0, (int(row[0]) - 2) if row else now - 86400)
        until = now
        while until >= since:
            payload = self.gateway.faction_revives(
                pool=faction.tag, from_timestamp=since, to_timestamp=until, limit=100, sort="DESC",
            )
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError(f"Torn revive log request failed: {payload.get('error') if isinstance(payload, dict) else 'invalid response'}")
            raw = payload.get("revives")
            if not isinstance(raw, dict):
                raise ValueError("Torn did not return a v1 revive log mapping.")
            parsed = [ReviveParser.parse({**item, "id": int(key)}) for key, item in raw.items()]
            if any(revive.timestamp <= 0 or revive.revive_id <= 0 for revive in parsed):
                raise ValueError("Torn returned a revive without a valid ID or timestamp.")
            with self.connect() as conn:
                for revive in parsed:
                    columns = revive.column_names()
                    conn.execute(
                        f"INSERT OR IGNORE INTO revives ({', '.join(columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)})",
                        tuple(getattr(revive, column) for column in columns),
                    )
            if len(parsed) < 100:
                break
            oldest = min(revive.timestamp for revive in parsed)
            if oldest >= until:
                raise ValueError("Revive pagination stalled; the log cursor was not advanced.")
            until = oldest
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO revive_log_cursors VALUES (?, ?)
                ON CONFLICT(faction_tag) DO UPDATE SET timestamp = excluded.timestamp
                WHERE revive_log_cursors.timestamp = ?
            """, (faction.tag, now, int(row[0]) if row else -1))

    def recent_logs(self, faction_id, direction, limit=10):
        filters = {
            "incoming": "target_faction_id = ?",
            "outgoing": "reviver_faction_id = ?",
            "both": "(target_faction_id = ? OR reviver_faction_id = ?)",
        }
        if direction not in filters:
            raise ValueError("Choose incoming, outgoing or both.")
        params = [faction_id] * (2 if direction == "both" else 1)
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                f"SELECT * FROM revives WHERE {filters[direction]} "
                "ORDER BY timestamp DESC, revive_id DESC LIMIT ?",
                (*params, max(1, min(25, int(limit)))),
            )]

    def historical_chance(self, target_id, now):
        with self.connect() as conn:
            row = conn.execute("""
                SELECT chance, timestamp, target_early_discharge
                FROM revives WHERE target_id = ? AND timestamp > ? AND timestamp <= ?
                ORDER BY timestamp DESC, revive_id DESC LIMIT 1
            """, (target_id, now - 86400, now)).fetchone()
            return dict(row) if row else None

    def estimate(self, target_id, skill, now):
        with self.connect() as conn:
            timestamps = [
                row[0] for row in conn.execute("""
                    SELECT timestamp FROM revives WHERE target_id = ?
                    AND LOWER(result) = 'success' AND timestamp > ? AND timestamp <= ?
                """, (target_id, now - 86400, now))
            ]
        return estimate_contract_chance(skill, timestamps, now), len(timestamps)

    def start_contract(self, faction, target_faction_id, start_at, success_target, success_price, failure_price, actor, now):
        if (
            not faction.faction_id or faction.faction_id <= 0
            or target_faction_id <= 0 or start_at <= 0 or start_at > now
            or success_target < 1 or min(success_price, failure_price) < 0
        ):
            raise ValueError("Use a positive target faction/quantity, a past or current start timestamp, and non-negative prices.")
        contract_id = uuid.uuid4().hex[:12]
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            overlap = conn.execute("""
                SELECT contract_id FROM revive_contracts
                WHERE target_faction_id = ?
                AND (end_at IS NULL OR end_at > ?)
            """, (target_faction_id, start_at)).fetchone()
            if overlap:
                raise ValueError(f"That faction/time window overlaps contract {overlap[0]}.")
            conn.execute("""
                INSERT INTO revive_contracts VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """, (
                contract_id, faction.tag, faction.faction_id, target_faction_id,
                start_at, success_target, success_price, failure_price, str(actor),
            ))
            conn.execute("""
                INSERT INTO revive_log_cursors VALUES (?, ?)
                ON CONFLICT(faction_tag) DO UPDATE SET timestamp = MIN(timestamp, excluded.timestamp)
            """, (faction.tag, start_at))
        return contract_id

    def end_contract(self, contract_id, now):
        with self.connect() as conn:
            changed = conn.execute("""
                UPDATE revive_contracts SET end_at = ?
                WHERE contract_id = ? AND end_at IS NULL AND start_at <= ?
            """, (now, contract_id, now)).rowcount
            if not changed:
                raise ValueError("No active contract found with that ID.")

    def contracts(self, active_only=False):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM revive_contracts "
                + ("WHERE end_at IS NULL " if active_only else "")
                + "ORDER BY start_at DESC",
            ).fetchall()
            return [dict(row) for row in rows]

    def contract_for(self, target_faction_id, timestamp):
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT * FROM revive_contracts WHERE target_faction_id = ?
                AND start_at <= ? AND (end_at IS NULL OR end_at > ?)
            """, (target_faction_id, timestamp, timestamp)).fetchall()
            if len(rows) > 1:
                raise ValueError("Multiple provider contracts match this target. An administrator must resolve the overlap.")
            return dict(rows[0]) if rows else None

    def contract_summary(self, contract_id, now):
        with self.connect() as conn:
            contract = conn.execute(
                "SELECT * FROM revive_contracts WHERE contract_id = ?", (contract_id,),
            ).fetchone()
            if not contract:
                raise ValueError("Unknown contract ID.")
            contract = dict(contract)
            rows = conn.execute("""
                SELECT LOWER(result) AS result, COUNT(*) AS count FROM revives
                WHERE reviver_faction_id = ? AND target_faction_id = ?
                AND timestamp >= ? AND timestamp < ?
                GROUP BY LOWER(result)
            """, (
                contract["provider_faction_id"], contract["target_faction_id"],
                contract["start_at"], min(contract["end_at"], now + 1) if contract["end_at"] is not None else now + 1,
            )).fetchall()
            counts = {str(row["result"]).lower(): row["count"] for row in rows}
            success = counts.get("success", 0)
            failures = counts.get("failure", 0) + counts.get("failed", 0)
            return {
                **contract, "successes": success, "failures": failures,
                "target_reached": success >= contract["success_target"],
                "unknown_results": sum(counts.values()) - success - failures,
                "total_due": success * contract["success_price"] + failures * contract["failure_price"],
            }

    def save_request_details(self, request_id, contract, historical):
        chance = historical["chance"] if historical else None
        warning = (
            f"Low historical revive chance: {chance:.2f}% (last attempt, not a live quote)."
            if contract is None and chance is not None and chance <= 50 else None
        )
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO discord_revive_details (request_id, contract_id, chance, chance_at, warning)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    contract_id = excluded.contract_id, chance = excluded.chance,
                    chance_at = excluded.chance_at, warning = excluded.warning
            """, (
                request_id, contract["contract_id"] if contract else None,
                chance, historical["timestamp"] if historical else None, warning,
            ))

    def request_details(self, request_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM discord_revive_details WHERE request_id = ?", (request_id,),
            ).fetchone()
            return dict(row) if row else None

    def save_contract_assignment(self, request_id, contract, status, target_faction_id=None):
        if status not in ("matched", "none", "unverified"):
            raise ValueError("Invalid contract assignment status.")
        if (status == "matched") != (contract is not None):
            raise ValueError("A matched contract assignment must include a contract.")
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO discord_revive_details (
                    request_id, contract_id, contract_check_status, request_target_faction_id
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    contract_id = excluded.contract_id,
                    contract_check_status = excluded.contract_check_status,
                    request_target_faction_id = excluded.request_target_faction_id
            """, (request_id, contract["contract_id"] if contract else None, status, target_faction_id))
            if contract:
                conn.execute(
                    "UPDATE revive_requests SET request_kind = 'contract' WHERE request_id = ?",
                    (request_id,),
                )

    def assign_request_contract(self, request_id, target_id, requested_timestamp):
        details = self.request_details(request_id)
        if details and details["contract_check_status"] in ("matched", "none"):
            return details
        # Use the request's original time even when its listener notification arrives late.
        with self.connect() as conn:
            request = conn.execute(
                "SELECT requested_timestamp, target_id FROM revive_requests WHERE request_id = ?", (request_id,),
            ).fetchone()
        if request:
            requested_timestamp = int(request["requested_timestamp"])
            target_id = int(request["target_id"])
        candidates = [
            contract for contract in self.contracts()
            if contract["start_at"] <= requested_timestamp
            and (contract["end_at"] is None or requested_timestamp < contract["end_at"])
        ]
        if not candidates:
            self.save_contract_assignment(request_id, None, "none")
        else:
            profile = self.profile(target_id)
            contract = self.contract_for(profile["faction_id"], requested_timestamp)
            self.save_contract_assignment(
                request_id, contract, "matched" if contract else "none", profile["faction_id"],
            )
        return self.request_details(request_id)

    def payment_context(self, request_id):
        details = self.request_details(request_id) or {}
        with self.connect() as conn:
            row = conn.execute("""
                SELECT r.request_kind, r.target_id AS requested_target_id, r.fulfilled_by_id, v.*
                FROM revive_requests r
                LEFT JOIN revives v ON v.revive_id = r.fulfilled_revive_id
                WHERE r.request_id = ? AND r.status = 'fulfilled'
            """, (request_id,)).fetchone()
        requested_contract = details.get("contract_id")
        manual_contract = row and str(row["request_kind"] or "").lower() == "contract"
        context = {"contract_id": None, "needs_review": False}
        if row is None or row["revive_id"] is None:
            return {**context, "needs_review": True}
        if (
            str(row["result"] or "").lower() != "success"
            or row["reviver_id"] != row["fulfilled_by_id"]
            or row["target_id"] != row["requested_target_id"]
        ):
            return {**context, "needs_review": True}
        # A request-time assignment is only intent; the actual logged attempt determines coverage.
        try:
            contract = self.contract_for(row["target_faction_id"], row["timestamp"])
        except ValueError:
            return {**context, "needs_review": True}
        if contract and row["reviver_faction_id"] == contract["provider_faction_id"]:
            return {**context, "contract_id": contract["contract_id"]}
        if requested_contract or manual_contract or details.get("contract_check_status") == "unverified":
            return {**context, "needs_review": True}
        if contract:
            return {**context, "needs_review": True}
        return context

    def payment_notifications(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT * FROM (
                SELECT COALESCE(NULLIF(d.discord_user_id, ''), (
                    SELECT l.discord_user_id FROM discord_user_links l
                    WHERE l.torn_user_id = r.requester_id
                    ORDER BY l.updated_at DESC, l.discord_user_id LIMIT 1
                )) AS discord_user_id, r.*, m.contract_id, m.payment_dm_status
                FROM revive_requests r
                JOIN discord_revive_details m USING (request_id)
                LEFT JOIN discord_revive_requests d USING (request_id)
                WHERE r.status = 'fulfilled' AND m.payment_dm_status = 'pending'
                ) WHERE discord_user_id IS NOT NULL
                ORDER BY revived_timestamp LIMIT 50
            """)]

    def mark_payment_notification(self, request_id, status):
        if status not in ("sent", "blocked"):
            raise ValueError("Invalid payment notification status.")
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO discord_revive_details (request_id, payment_dm_status) VALUES (?, ?)
                ON CONFLICT(request_id) DO UPDATE SET payment_dm_status = excluded.payment_dm_status
            """, (request_id, status))
