"""Persistent Discord retaliation alerts and chain-warning state."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class FactionWatchRepository:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS discord_retal_alerts (
                    faction_tag TEXT NOT NULL,
                    attack_id TEXT NOT NULL,
                    attacker_id INTEGER NOT NULL,
                    attacker_name TEXT NOT NULL,
                    attacker_faction TEXT NOT NULL,
                    defender_name TEXT NOT NULL,
                    result TEXT NOT NULL,
                    attacked_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    fulfilled_by TEXT,
                    fulfilled_attack_id TEXT,
                    channel_id INTEGER,
                    message_id INTEGER,
                    posted_status TEXT,
                    PRIMARY KEY (faction_tag, attack_id)
                );
                CREATE INDEX IF NOT EXISTS discord_retal_pending
                    ON discord_retal_alerts (faction_tag, status, expires_at);
                CREATE TABLE IF NOT EXISTS discord_chain_watch_state (
                    faction_tag TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL
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

    def record_incoming(self, tag, attack):
        with self.connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO discord_retal_alerts (
                    faction_tag, attack_id, attacker_id, attacker_name,
                    attacker_faction, defender_name, result, attacked_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tag, attack["id"], attack["attacker_id"], attack["attacker_name"],
                attack["attacker_faction_name"], attack["defender_name"], attack["result"],
                attack["ended"], attack["ended"] + 300,
            ))

    def fulfill(self, tag, attack):
        with self.connect() as conn:
            conn.execute("""
                UPDATE discord_retal_alerts
                SET status = 'fulfilled', fulfilled_by = ?, fulfilled_attack_id = ?
                WHERE faction_tag = ? AND status IN ('pending', 'missed') AND attacker_id = ?
                    AND attacked_at <= ? AND expires_at >= ?
            """, (
                attack["attacker_name"], attack["id"], tag, attack["defender_id"],
                attack["started"], attack["ended"],
            ))

    def expire(self, tag, now):
        with self.connect() as conn:
            conn.execute("""
                UPDATE discord_retal_alerts SET status = 'missed'
                WHERE faction_tag = ? AND status = 'pending' AND expires_at <= ?
            """, (tag, now))

    def pending_since(self, tag):
        with self.connect() as conn:
            row = conn.execute("""
                SELECT MIN(attacked_at) FROM discord_retal_alerts
                WHERE faction_tag = ? AND status = 'pending'
            """, (tag,)).fetchone()
            return row[0]

    def notifications(self, tag):
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT * FROM discord_retal_alerts
                WHERE faction_tag = ? AND (message_id IS NULL OR posted_status != status)
                ORDER BY attacked_at, attack_id
            """, (tag,)).fetchall()
            return [dict(row) for row in rows]

    def mark_posted(self, tag, attack_id, channel_id, message_id, status):
        with self.connect() as conn:
            conn.execute("""
                UPDATE discord_retal_alerts
                SET channel_id = ?, message_id = ?, posted_status = ?
                WHERE faction_tag = ? AND attack_id = ?
            """, (channel_id, message_id, status, tag, attack_id))

    def chain_state(self, tag):
        with self.connect() as conn:
            row = conn.execute("""
                SELECT state_json FROM discord_chain_watch_state WHERE faction_tag = ?
            """, (tag,)).fetchone()
            return json.loads(row[0]) if row else None

    def save_chain_state(self, tag, state):
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO discord_chain_watch_state (faction_tag, state_json) VALUES (?, ?)
                ON CONFLICT(faction_tag) DO UPDATE SET state_json = excluded.state_json
            """, (tag, json.dumps(state)))
