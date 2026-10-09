"""Persistent OC payout reminders and member OC participation."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from services.oc_watchers import DAY, crime_paid_at, last_crime_times, needs_payout


class OcWatchRepository:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS discord_oc_payouts (
                    faction_tag TEXT NOT NULL,
                    crime_id INTEGER NOT NULL,
                    crime_name TEXT NOT NULL,
                    difficulty INTEGER NOT NULL DEFAULT 0,
                    executed_at INTEGER NOT NULL,
                    money INTEGER NOT NULL DEFAULT 0,
                    paid_at INTEGER,
                    dismissed INTEGER NOT NULL DEFAULT 0,
                    last_reminded_at INTEGER,
                    PRIMARY KEY (faction_tag, crime_id)
                );
                CREATE TABLE IF NOT EXISTS discord_oc_participation (
                    faction_tag TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    first_seen_at INTEGER NOT NULL,
                    last_in_oc_at INTEGER,
                    is_in_oc INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (faction_tag, user_id)
                );
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.database_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # Payouts ------------------------------------------------------------

    def record_crimes(self, tag, crimes):
        with self.connect() as conn:
            for crime in crimes:
                if not needs_payout(crime):
                    continue
                paid_at = crime_paid_at(crime)
                conn.execute(
                    """
                    INSERT INTO discord_oc_payouts
                        (faction_tag, crime_id, crime_name, difficulty, executed_at, money, paid_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(faction_tag, crime_id) DO UPDATE SET
                        paid_at = COALESCE(excluded.paid_at, discord_oc_payouts.paid_at),
                        money = excluded.money
                    """,
                    (
                        tag, int(crime["id"]), str(crime.get("name") or "Unknown crime"),
                        int(crime.get("difficulty") or 0), int(crime["executed_at"]),
                        int((crime.get("rewards") or {}).get("money") or 0), paid_at,
                    ),
                )

    def overdue_payouts(self, tag, now, hours, max_age_days=7):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                """
                SELECT * FROM discord_oc_payouts
                WHERE faction_tag = ? AND paid_at IS NULL AND dismissed = 0
                  AND executed_at <= ? AND executed_at >= ?
                ORDER BY executed_at
                """,
                (tag, int(now - hours * 3600), int(now - max_age_days * DAY)),
            )]

    def mark_reminded(self, tag, crime_ids, now):
        with self.connect() as conn:
            conn.executemany(
                "UPDATE discord_oc_payouts SET last_reminded_at = ? WHERE faction_tag = ? AND crime_id = ?",
                [(int(now), tag, int(crime_id)) for crime_id in crime_ids],
            )

    def dismiss_payout(self, tag, crime_id):
        with self.connect() as conn:
            return conn.execute(
                "UPDATE discord_oc_payouts SET dismissed = 1 WHERE faction_tag = ? AND crime_id = ?",
                (tag, int(crime_id)),
            ).rowcount > 0

    # Participation ------------------------------------------------------

    def sync_participation(self, tag, members, crimes, now, history_from):
        """Track members' latest OC activity; history_from is how far back `crimes` was scanned."""
        latest = last_crime_times(crimes)
        member_ids = [member["id"] for member in members]
        with self.connect() as conn:
            for member in members:
                user_id = member["id"]
                last_in_oc = now if member["is_in_oc"] else latest.get(user_id)
                joined_at = now - member.get("days_in_faction", 0) * DAY
                first_seen_at = max(int(history_from), int(joined_at))
                conn.execute(
                    """
                    INSERT INTO discord_oc_participation
                        (faction_tag, user_id, user_name, first_seen_at, last_in_oc_at, is_in_oc)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(faction_tag, user_id) DO UPDATE SET
                        user_name = excluded.user_name,
                        is_in_oc = excluded.is_in_oc,
                        last_in_oc_at = MAX(
                            COALESCE(discord_oc_participation.last_in_oc_at, 0),
                            COALESCE(excluded.last_in_oc_at, 0)
                        )
                    """,
                    (tag, user_id, member["name"], first_seen_at, last_in_oc, int(member["is_in_oc"])),
                )
            placeholders = ",".join("?" for _ in member_ids)
            if member_ids:
                conn.execute(
                    f"DELETE FROM discord_oc_participation WHERE faction_tag = ? AND user_id NOT IN ({placeholders})",
                    (tag, *member_ids),
                )

    def inactive_members(self, tag, now, days):
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM discord_oc_participation WHERE faction_tag = ? AND is_in_oc = 0",
                (tag,),
            )]
        result = []
        for row in rows:
            since = row["last_in_oc_at"] or row["first_seen_at"]
            row["idle_seconds"] = max(0, int(now) - int(since))
            row["never_seen_in_oc"] = not row["last_in_oc_at"]
            if row["idle_seconds"] >= days * DAY:
                result.append(row)
        return sorted(result, key=lambda row: -row["idle_seconds"])

    def has_participation(self, tag):
        with self.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM discord_oc_participation WHERE faction_tag = ? LIMIT 1", (tag,),
            ).fetchone() is not None
