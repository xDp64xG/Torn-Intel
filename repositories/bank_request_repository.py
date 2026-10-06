"""
Repository for faction bank (vault) withdrawal requests.
"""

import json
import time


BANK_REQUESTS_DDL = """
CREATE TABLE IF NOT EXISTS bank_requests (
    request_id TEXT PRIMARY KEY,
    requester_id INTEGER,
    requester_name TEXT NOT NULL,
    amount INTEGER NOT NULL,
    faction_tag TEXT NOT NULL DEFAULT 'GTS',
    source TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    raw_payload TEXT,
    created_at INTEGER NOT NULL,
    discord_posted_at INTEGER,
    channel_id TEXT,
    message_id TEXT,
    requested_text TEXT,
    balance INTEGER,
    resolved_at INTEGER,
    resolved_by TEXT,
    resolution_note TEXT,
    claimed_by TEXT,
    claimed_at INTEGER,
    expires_at INTEGER,
    userscript_notified_at INTEGER
)
"""

# Columns added after the original table shipped; applied to older databases on startup.
BANK_REQUEST_ADDED_COLUMNS = {
    "faction_tag": "TEXT NOT NULL DEFAULT 'GTS'",
    "requested_text": "TEXT",
    "balance": "INTEGER",
    "resolved_at": "INTEGER",
    "resolved_by": "TEXT",
    "resolution_note": "TEXT",
    "claimed_by": "TEXT",
    "claimed_at": "INTEGER",
    "expires_at": "INTEGER",
    "userscript_notified_at": "INTEGER",
}

MAX_BANK_AMOUNT = 1_000_000_000_000
BANK_REQUEST_TIMEOUT_SECONDS = 3600
# How long after a banker clicks Fulfill we keep checking faction funds news for the payment.
BANK_VERIFY_WINDOW_SECONDS = 300


BANK_CLAIMS_DDL = """
CREATE TABLE IF NOT EXISTS bank_request_claims (
    claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    banker_name TEXT NOT NULL,
    banker_discord_id TEXT,
    claimed_at INTEGER NOT NULL,
    ended_at INTEGER,
    outcome TEXT NOT NULL DEFAULT 'in_process'
)
"""


def bank_request_expiry(row):
    return int(row.get("expires_at") or (int(row.get("created_at") or 0) + BANK_REQUEST_TIMEOUT_SECONDS))


def bank_request_migrations(existing_columns):
    existing = {str(column).lower() for column in existing_columns}
    return [
        f"ALTER TABLE bank_requests ADD COLUMN {name} {ddl}"
        for name, ddl in BANK_REQUEST_ADDED_COLUMNS.items()
        if name not in existing
    ]


class BankRequestRepository:

    def __init__(self, database):
        self.db = database
        self.db.create_table(BANK_REQUESTS_DDL)
        self.db.create_table(BANK_CLAIMS_DDL)
        columns = {row["name"] for row in self.db.select("PRAGMA table_info(bank_requests)")}
        migrations = bank_request_migrations(columns)
        for statement in migrations:
            self.db.execute(statement)
        if migrations:
            self.db.commit()

    def create_request(self, payload):
        requester_name = str(payload.get("requester_name") or "").strip()
        if not requester_name:
            raise ValueError("requester_name_required")

        try:
            requester_id = int(payload.get("requester_id"))
        except (TypeError, ValueError):
            raise ValueError("requester_id_required")

        try:
            amount = int(payload.get("amount"))
        except (TypeError, ValueError):
            raise ValueError("amount_invalid")
        if amount <= 0 or amount > MAX_BANK_AMOUNT:
            raise ValueError("amount_out_of_range")

        now = int(time.time())
        row = {
            "request_id": f"bankreq:{int(time.time() * 1000)}:{requester_id or requester_name}",
            "requester_id": requester_id,
            "requester_name": requester_name[:64],
            "amount": amount,
            "faction_tag": str(payload.get("faction_tag") or "GTS").strip().upper()[:32],
            "source": str(payload.get("source") or "external")[:64],
            "notes": str(payload.get("notes") or "")[:500] or None,
            "status": "pending",
            "raw_payload": json.dumps(payload)[:4000],
            "created_at": now,
            "expires_at": now + BANK_REQUEST_TIMEOUT_SECONDS,
            "requested_text": str(payload.get("requested_text") or amount)[:32],
            "balance": int(payload["balance"]) if payload.get("balance") is not None else None,
        }
        self.db.insert("bank_requests", row)
        return row

    def pop_userscript_notifications(self, requester_id: int, max_age_seconds: int = 86400, limit: int = 10):
        """Return cancelled/expired requests not yet shown in the userscript, marking them delivered."""
        cutoff = int(time.time()) - int(max_age_seconds)
        rows = [
            dict(row)
            for row in self.db.select(
                """
                SELECT request_id, amount, status, resolved_by, resolution_note, resolved_at
                FROM bank_requests
                WHERE requester_id = ?
                  AND status IN ('cancelled', 'expired')
                  AND userscript_notified_at IS NULL
                  AND COALESCE(resolved_at, 0) >= ?
                ORDER BY resolved_at ASC
                LIMIT ?
                """,
                (int(requester_id), cutoff, int(limit)),
            )
        ]
        if rows:
            placeholders = ",".join("?" for _ in rows)
            self.db.execute(
                f"UPDATE bank_requests SET userscript_notified_at = ? WHERE request_id IN ({placeholders})",
                (int(time.time()), *[row["request_id"] for row in rows]),
            )
            self.db.commit()
        return rows
