"""
Discord bot bridge for TornIntel CLI.

This layer keeps CLI as source-of-truth and adds:
- Embed-based output.
- Structured slash helpers that resemble common CLI usage.
- DB-backed autocomplete for war IDs, chain IDs, item names, and categories.
"""

from __future__ import annotations

import shlex
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import re
import asyncio
import io
import csv
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


from config.settings import Settings


EMBED_TEXT_LIMIT = 3900
DEFAULT_TAIL_LINES = 80
LONG_RUNNING_COMMANDS = {"watch", "revive_listener"}
REVIVE_SOURCE = "discord-bot"

REPORT_TYPES_BY_MODULE = {
    "attacks": ["chain_hit", "chain_stats", "chain_leaderboard", "chain_player"],
    "chains": ["chain_hit", "chain_stats", "chain_leaderboard", "chain_player"],
    "rankedwars": ["war_stats", "war_leaderboard", "war_player", "war_payout", "war_costs", "chain_costs"],
    "armoury": ["player_usage", "category", "medical_summary", "loan_tracker"],
    "crimes": ["oc_item_audit", "oc_cpr", "oc_outside"],
    "revives": ["requests_list"],
}


@dataclass
class BackgroundJob:
    job_id: str
    command_text: str
    process: subprocess.Popen
    started_at: float
    output: deque = field(default_factory=lambda: deque(maxlen=1200))


class DbAutocomplete:

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    #######################################################

    def _query(self, sql: str, params=()):
        try:
            conn = sqlite3.connect(str(self.database_path))
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(sql, params)
                return cur.fetchall()
            finally:
                conn.close()
        except Exception:
            return []

    #######################################################

    @staticmethod
    def _match_text(current: str):
        text = (current or "").strip().lower()
        if not text:
            return None
        return f"%{text}%"

    #######################################################

    def recent_wars(self, current: str = "", limit: int = 20):
        like = self._match_text(current)
        if like:
            rows = self._query(
                """
                SELECT war_id, opponent_faction_name, war_start
                FROM rankedwars
                WHERE CAST(war_id AS TEXT) LIKE ? OR LOWER(COALESCE(opponent_faction_name, '')) LIKE ?
                ORDER BY war_start DESC
                LIMIT ?
                """,
                (like, like, int(limit)),
            )
        else:
            rows = self._query(
                """
                SELECT war_id, opponent_faction_name, war_start
                FROM rankedwars
                ORDER BY war_start DESC
                LIMIT ?
                """,
                (int(limit),),
            )

        out = []
        for row in rows:
            started = int(row["war_start"] or 0)
            dt = datetime.fromtimestamp(started).strftime("%m-%d") if started else "?"
            name = row["opponent_faction_name"] or "Unknown"
            out.append((f"{row['war_id']} - {name} ({dt})", int(row["war_id"])))
        return out

    #######################################################

    def recent_chains(self, current: str = "", limit: int = 20):
        like = self._match_text(current)
        if like:
            rows = self._query(
                """
                SELECT chain_id, chain_number, timestamp_start
                FROM chains
                WHERE CAST(chain_id AS TEXT) LIKE ? OR CAST(chain_number AS TEXT) LIKE ?
                ORDER BY timestamp_start DESC
                LIMIT ?
                """,
                (like, like, int(limit)),
            )
        else:
            rows = self._query(
                """
                SELECT chain_id, chain_number, timestamp_start
                FROM chains
                ORDER BY timestamp_start DESC
                LIMIT ?
                """,
                (int(limit),),
            )

        out = []
        for row in rows:
            started = int(row["timestamp_start"] or 0)
            dt = datetime.fromtimestamp(started).strftime("%m-%d") if started else "?"
            chain_num = int(row["chain_number"] or 0)
            out.append((f"{row['chain_id']} - chain #{chain_num} ({dt})", int(row["chain_id"])))
        return out

    #######################################################

    def items(self, current: str = "", limit: int = 20):
        like = self._match_text(current)
        rows = self._query(
            """
            SELECT item_name
            FROM (
                SELECT DISTINCT item_name AS item_name FROM item_prices WHERE item_name IS NOT NULL AND item_name != ''
                UNION
                SELECT DISTINCT item_name AS item_name FROM armoury_news WHERE item_name IS NOT NULL AND item_name != ''
            )
            WHERE (? IS NULL OR LOWER(item_name) LIKE ?)
            ORDER BY item_name ASC
            LIMIT ?
            """,
            (like, like, int(limit)),
        )
        return [str(row["item_name"]) for row in rows if row["item_name"]]

    #######################################################

    def categories(self, current: str = "", limit: int = 20):
        like = self._match_text(current)
        rows = self._query(
            """
            SELECT item_category
            FROM (
                SELECT DISTINCT item_category AS item_category FROM item_prices WHERE item_category IS NOT NULL AND item_category != ''
                UNION
                SELECT DISTINCT item_category AS item_category FROM armoury_news WHERE item_category IS NOT NULL AND item_category != ''
            )
            WHERE (? IS NULL OR LOWER(item_category) LIKE ?)
            ORDER BY item_category ASC
            LIMIT ?
            """,
            (like, like, int(limit)),
        )
        return [str(row["item_category"]) for row in rows if row["item_category"]]


class ReviveDiscordStore:

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self._ensure_tables()

    #######################################################

    def _connect(self):
        conn = sqlite3.connect(str(self.database_path))
        conn.row_factory = sqlite3.Row
        return conn

    #######################################################

    def _ensure_tables(self):
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discord_user_links (
                    discord_user_id TEXT PRIMARY KEY,
                    torn_user_id INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discord_revive_requests (
                    request_id TEXT PRIMARY KEY,
                    discord_user_id TEXT NOT NULL,
                    torn_user_id INTEGER,
                    target_id INTEGER,
                    target_name TEXT,
                    channel_id TEXT,
                    message_id TEXT,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    cancelled_at INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discord_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    #######################################################

    def set_user_torn_id(self, discord_user_id: int, torn_user_id: int):
        now = int(time.time())
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO discord_user_links (discord_user_id, torn_user_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE SET
                    torn_user_id = excluded.torn_user_id,
                    updated_at = excluded.updated_at
                """,
                (str(discord_user_id), int(torn_user_id), now),
            )
            conn.commit()
        finally:
            conn.close()

    #######################################################

    def get_user_torn_id(self, discord_user_id: int):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT torn_user_id FROM discord_user_links WHERE discord_user_id = ? LIMIT 1",
                (str(discord_user_id),),
            ).fetchone()
            return int(row["torn_user_id"]) if row else None
        finally:
            conn.close()

    #######################################################

    def set_setting(self, key: str, value: str):
        now = int(time.time())
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO discord_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at
                """,
                (str(key), str(value), now),
            )
            conn.commit()
        finally:
            conn.close()

    #######################################################

    def get_setting(self, key: str):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT setting_value FROM discord_settings WHERE setting_key = ? LIMIT 1",
                (str(key),),
            ).fetchone()
            return str(row["setting_value"]) if row and row["setting_value"] is not None else None
        finally:
            conn.close()

    #######################################################

    def create_request(self, discord_user_id: int, torn_user_id: int | None, target_id: int, target_name: str | None, requester_name: str):
        now = int(time.time())
        request_id = f"revreq:{int(time.time() * 1000)}:{target_id}"
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO revive_requests (
                    request_id,
                    requested_timestamp,
                    created_at,
                    requester_id,
                    requester_name,
                    target_id,
                    target_name,
                    source,
                    status,
                    fulfilled_revive_id,
                    revived_timestamp,
                    fulfilled_at,
                    fulfilled_by_id,
                    fulfilled_by_name,
                    matched_at,
                    notified_at,
                    notes,
                    raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, NULL)
                """,
                (
                    request_id,
                    now,
                    now,
                    int(torn_user_id) if torn_user_id is not None else None,
                    str(requester_name),
                    int(target_id),
                    str(target_name) if target_name else None,
                    REVIVE_SOURCE,
                    f"Requested from Discord by user {discord_user_id}",
                ),
            )

            conn.execute(
                """
                INSERT INTO discord_revive_requests (
                    request_id,
                    discord_user_id,
                    torn_user_id,
                    target_id,
                    target_name,
                    channel_id,
                    message_id,
                    status,
                    created_at,
                    cancelled_at
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 'active', ?, NULL)
                """,
                (
                    request_id,
                    str(discord_user_id),
                    int(torn_user_id) if torn_user_id is not None else None,
                    int(target_id),
                    str(target_name) if target_name else None,
                    now,
                ),
            )
            conn.commit()
            return request_id
        finally:
            conn.close()

    #######################################################

    def attach_message(self, request_id: str, channel_id: int, message_id: int):
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE discord_revive_requests
                SET channel_id = ?, message_id = ?
                WHERE request_id = ?
                """,
                (str(channel_id), str(message_id), str(request_id)),
            )
            conn.commit()
        finally:
            conn.close()

    #######################################################

    def cancel_request(self, request_id: str, discord_user_id: int, allow_force: bool = False):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT d.*, r.status AS revive_status
                FROM discord_revive_requests d
                LEFT JOIN revive_requests r ON r.request_id = d.request_id
                WHERE d.request_id = ?
                LIMIT 1
                """,
                (str(request_id),),
            ).fetchone()
            if not row:
                return False, "request_not_found", None

            if str(row["status"]).lower() != "active":
                return False, "request_not_active", dict(row)

            owner_id = str(row["discord_user_id"] or "")
            if not allow_force and owner_id != str(discord_user_id):
                return False, "not_owner", dict(row)

            now = int(time.time())
            conn.execute(
                "DELETE FROM revive_requests WHERE request_id = ? AND status = 'pending'",
                (str(request_id),),
            )
            deleted = conn.total_changes

            if deleted <= 0:
                return False, "already_closed", dict(row)

            conn.execute(
                """
                UPDATE discord_revive_requests
                SET status = 'cancelled', cancelled_at = ?
                WHERE request_id = ?
                """,
                (now, str(request_id)),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM discord_revive_requests WHERE request_id = ? LIMIT 1",
                (str(request_id),),
            ).fetchone()
            return True, "cancelled", dict(updated) if updated else dict(row)
        finally:
            conn.close()

    #######################################################

    def get_discord_request(self, request_id: str):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM discord_revive_requests WHERE request_id = ? LIMIT 1",
                (str(request_id),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    #######################################################

    def list_active_requests(self, limit: int = 25):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    d.request_id,
                    d.discord_user_id,
                    d.torn_user_id,
                    d.target_id,
                    COALESCE(d.target_name, r.target_name) AS target_name,
                    r.requester_name,
                    r.requested_timestamp,
                    r.status AS revive_status,
                    d.status AS discord_status,
                    d.channel_id,
                    d.message_id,
                    d.created_at
                FROM discord_revive_requests d
                LEFT JOIN revive_requests r ON r.request_id = d.request_id
                WHERE d.status = 'active' AND COALESCE(r.status, 'pending') = 'pending'
                ORDER BY COALESCE(r.requested_timestamp, d.created_at) DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    #######################################################

    def list_fulfilled_pending_embed_updates(self, limit: int = 50):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    d.request_id,
                    d.discord_user_id,
                    d.torn_user_id,
                    d.target_id,
                    COALESCE(d.target_name, r.target_name) AS target_name,
                    r.requester_name,
                    r.requested_timestamp,
                    r.fulfilled_by_name,
                    r.fulfilled_by_id,
                    r.revived_timestamp,
                    d.channel_id,
                    d.message_id
                FROM discord_revive_requests d
                INNER JOIN revive_requests r ON r.request_id = d.request_id
                WHERE d.status = 'active'
                  AND r.status = 'fulfilled'
                  AND d.channel_id IS NOT NULL
                  AND d.message_id IS NOT NULL
                ORDER BY r.revived_timestamp DESC, r.requested_timestamp DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    #######################################################

    def mark_embed_fulfilled(self, request_id: str):
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE discord_revive_requests
                SET status = 'fulfilled'
                WHERE request_id = ?
                """,
                (str(request_id),),
            )
            conn.commit()
        finally:
            conn.close()


class CliBridge:

    def __init__(self, repo_root: Path, timeout_seconds: int = 180):
        self.repo_root = repo_root
        self.main_path = repo_root / "main.py"
        self.timeout_seconds = max(10, int(timeout_seconds or 180))
        self._jobs = {}
        self._lock = threading.RLock()

    #######################################################

    def _tokenize(self, command_text: str):
        text = str(command_text or "").strip()
        if not text:
            raise ValueError("Command cannot be empty.")
        try:
            tokens = shlex.split(text)
        except ValueError as exc:
            raise ValueError(f"Unable to parse command: {exc}") from exc

        if not tokens:
            raise ValueError("Command cannot be empty.")

        if tokens[0] == "discord":
            raise ValueError("Running discord from inside Discord is blocked to prevent recursion.")

        return tokens

    #######################################################

    def _build_invocation(self, tokens):
        return [sys.executable, str(self.main_path), *tokens]

    #######################################################

    def run_foreground(self, command_text: str, timeout_seconds: int | None = None):
        tokens = self._tokenize(command_text)
        invocation = self._build_invocation(tokens)
        timeout = max(10, int(timeout_seconds or self.timeout_seconds))

        try:
            result = subprocess.run(
                invocation,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = self._merge_output(result.stdout, result.stderr)
            return {
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "output": output,
                "tokens": tokens,
            }
        except subprocess.TimeoutExpired as exc:
            partial = self._merge_output(
                getattr(exc, "stdout", "") or "",
                getattr(exc, "stderr", "") or "",
            )
            return {
                "ok": False,
                "returncode": -1,
                "output": (
                    partial + "\n\n"
                    f"Timed out after {timeout}s. "
                    "Run as background job to keep it running."
                ).strip(),
                "tokens": tokens,
            }

    #######################################################

    def start_background(self, command_text: str):
        tokens = self._tokenize(command_text)
        invocation = self._build_invocation(tokens)
        job_id = uuid.uuid4().hex[:8]

        process = subprocess.Popen(
            invocation,
            cwd=str(self.repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        job = BackgroundJob(
            job_id=job_id,
            command_text=command_text,
            process=process,
            started_at=time.time(),
        )

        with self._lock:
            self._jobs[job_id] = job

        reader = threading.Thread(
            target=self._read_background_output,
            args=(job_id,),
            daemon=True,
        )
        reader.start()

        return job_id

    #######################################################

    def _read_background_output(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return

        pipe = job.process.stdout
        if pipe is None:
            return

        for line in pipe:
            clean = line.rstrip("\n")
            with self._lock:
                existing = self._jobs.get(job_id)
                if not existing:
                    return
                existing.output.append(clean)

    #######################################################

    def list_jobs(self):
        rows = []
        with self._lock:
            for job_id, job in self._jobs.items():
                code = job.process.poll()
                status = "running" if code is None else f"exited ({code})"
                uptime = int(time.time() - job.started_at)
                rows.append({
                    "job_id": job_id,
                    "command": job.command_text,
                    "status": status,
                    "uptime": uptime,
                })
        rows.sort(key=lambda r: r["job_id"])
        return rows

    #######################################################

    def stop_job(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return False, f"No job found for id {job_id}."

        code = job.process.poll()
        if code is not None:
            return True, f"Job {job_id} already exited with code {code}."

        job.process.terminate()
        try:
            job.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=4)

        return True, f"Stopped job {job_id}."

    #######################################################

    def get_job_output(self, job_id: str, tail_lines: int = DEFAULT_TAIL_LINES):
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return False, f"No job found for id {job_id}."

        code = job.process.poll()
        status = "running" if code is None else f"exited ({code})"
        tail_count = max(5, int(tail_lines or DEFAULT_TAIL_LINES))

        with self._lock:
            lines = list(job.output)[-tail_count:]

        header = (
            f"Job {job_id} | {status} | tail={len(lines)} line(s)\n"
            f"Command: {job.command_text}"
        )
        text = "\n".join(lines) if lines else "(no output yet)"
        return True, f"{header}\n\n{text}"

    #######################################################

    @staticmethod
    def _merge_output(stdout: str, stderr: str):
        out = []
        if stdout:
            out.append(stdout.rstrip())
        if stderr:
            out.append(stderr.rstrip())
        merged = "\n\n".join(part for part in out if part).strip()
        return merged or "(no output)"


def _text_chunks(text: str):
    payload = str(text or "(no output)")
    limit = EMBED_TEXT_LIMIT
    chunks = []
    current = []
    current_len = 0

    for line in payload.splitlines() or ["(no output)"]:
        addition = line + "\n"
        if current_len + len(addition) > limit and current:
            chunks.append("".join(current).rstrip("\n"))
            current = [addition]
            current_len = len(addition)
            continue
        current.append(addition)
        current_len += len(addition)

    if current:
        chunks.append("".join(current).rstrip("\n"))

    return chunks or ["(no output)"]


def _render_job_rows(rows):
    if not rows:
        return "No jobs found."

    lines = [
        "Active/known jobs:",
        "ID       | Status       | Uptime | Command",
        "---------+--------------+--------+--------------------------------",
    ]
    for row in rows:
        uptime = f"{row['uptime']}s"
        lines.append(
            f"{row['job_id']:<8} | {row['status']:<12} | {uptime:>6} | {row['command']}"
        )
    return "\n".join(lines)


def _build_report_command(
    module,
    report_type,
    chain_id=None,
    war_id=None,
    hit_number=None,
    player=None,
    item=None,
    category=None,
    top_n=10,
    limit=50,
    total_payout=None,
    xanax_cost=0,
    faction_cut=0,
    bounty_cost=0,
    per_assist=0,
    pay_outside_hits=0,
):
    parts = ["report", module, report_type]
    if chain_id is not None:
        parts.extend(["--chain_id", str(chain_id)])
    if war_id is not None:
        parts.extend(["--war_id", str(war_id)])
    if hit_number is not None:
        parts.extend(["--hit_number", str(hit_number)])
    if player:
        parts.extend(["--player", str(player)])
    if item:
        parts.extend(["--item", str(item)])
    if category:
        parts.extend(["--category", str(category)])
    if top_n is not None:
        parts.extend(["--top_n", str(top_n)])
    if limit is not None:
        parts.extend(["--limit", str(limit)])

    if report_type == "war_payout":
        if total_payout is not None:
            parts.extend(["--total_payout", str(total_payout)])
        parts.extend(["--xanax_cost", str(xanax_cost or 0)])
        parts.extend(["--faction_cut", str(faction_cut or 0)])
        parts.extend(["--bounty_cost", str(bounty_cost or 0)])
        parts.extend(["--per_assist", str(per_assist or 0)])
        parts.extend(["--pay_outside_hits", str(int(pay_outside_hits or 0))])

    if module == "revives" and report_type == "requests_list":
        parts = ["revive_requests", "list"]
        if category:
            parts.extend(["--status", str(category)])
        if item:
            parts.extend(["--target-name", str(item)])
        if limit is not None:
            parts.extend(["--limit", str(limit)])

    return " ".join(shlex.quote(p) for p in parts)


def _build_war_payout_command(
    war_id,
    total_payout,
    xanax_cost=0,
    faction_cut=0,
    bounty_cost=0,
    per_assist=0,
    pay_outside_hits=0,
):
    parts = [
        "payout",
        "rankedwars",
        "--war_id",
        str(war_id),
        "--total_payout",
        str(total_payout),
        "--xanax_cost",
        str(xanax_cost or 0),
        "--faction_cut",
        str(faction_cut or 0),
        "--bounty_cost",
        str(bounty_cost or 0),
        "--per_assist",
        str(per_assist or 0),
        "--pay_outside_hits",
        str(int(pay_outside_hits or 0)),
    ]
    return " ".join(shlex.quote(p) for p in parts)


def _build_revives_search_command(reviver=None, target=None, result=None, limit=25, oldest=False):
    parts = ["sync", "revives", "--mode", "search"]
    if reviver:
        parts.extend(["--reviver-name", str(reviver)])
    if target:
        parts.extend(["--target-name", str(target)])
    if result:
        parts.extend(["--result", str(result)])
    if limit is not None:
        parts.extend(["--limit", str(limit)])
    if oldest:
        parts.append("--oldest")
    return " ".join(shlex.quote(p) for p in parts)


def _parse_channel_id(channel_ref):
    text = str(channel_ref or "").strip()
    if not text:
        return None

    if text.isdigit():
        return int(text)

    match = re.match(r"^<#(\d+)>$", text)
    if match:
        return int(match.group(1))

    return None


def serve_discord_bot(token: str, prefix: str = "!ti", guild_id: int | None = None, timeout_seconds: int = 180, logger=None):
    try:
        import discord
        from discord import app_commands
        from discord.ext import commands
    except ImportError as exc:
        raise RuntimeError(
            "discord.py is required for Discord integration. Install with: pip install discord.py"
        ) from exc

    repo_root = Path(__file__).resolve().parent.parent
    bridge = CliBridge(repo_root=repo_root, timeout_seconds=timeout_seconds)
    settings = Settings()
    autocomplete = DbAutocomplete(settings.database_path)
    revive_store = ReviveDiscordStore(settings.database_path)
    api_keys = [str(key).strip() for key in (settings.api_keys or []) if str(key).strip()]
    if not api_keys and getattr(settings, "api_key", None):
        fallback_key = str(settings.api_key or "").strip()
        if fallback_key:
            api_keys = [fallback_key]

    intents = discord.Intents.default()
    intents.message_content = bool(settings.discord_enable_message_content_intent)
    bot = commands.Bot(command_prefix=prefix, intents=intents)
    allow_prefix_commands = bool(settings.discord_enable_message_content_intent)
    revive_watcher_task = None

    def embed_color(ok: bool):
        return 0x2ecc71 if ok else 0xe74c3c

    async def send_embed_chunks(target_send, title: str, text: str, ok: bool = True, footer: str | None = None):
        chunks = _text_chunks(text)
        for idx, chunk in enumerate(chunks, start=1):
            suffix = f" ({idx}/{len(chunks)})" if len(chunks) > 1 else ""
            embed = discord.Embed(
                title=f"{title}{suffix}",
                description=f"```ansi\n{chunk}\n```",
                color=embed_color(ok),
            )
            if footer and idx == 1:
                embed.set_footer(text=footer)
            await target_send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    def resolve_revive_channel_id(default_channel_id: int | None = None):
        configured = revive_store.get_setting("revive_channel_id")
        if configured and str(configured).isdigit():
            return int(configured)
        if settings.discord_revive_channel_id:
            return int(settings.discord_revive_channel_id)
        return int(default_channel_id) if default_channel_id is not None else None

    async def resolve_revive_channel(interaction: discord.Interaction):
        channel_id = resolve_revive_channel_id(interaction.channel_id)
        if channel_id is None:
            return interaction.channel

        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                channel = interaction.channel
        return channel

    def check_hospital_status(target_id: int):
        if not api_keys:
            raise RuntimeError("No Torn API key configured. Set TORN_API_KEYS or TORN_API_KEY.")

        base = str(settings.base_url or "https://api.torn.com").rstrip("/")
        if base.lower().endswith("/v2"):
            base = base[:-3]
        url_v1 = f"{base}/user/{int(target_id)}/"
        url_v2 = f"{base}/v2/user/{int(target_id)}/profile"
        timeout_seconds = max(10, int(settings.request_timeout))

        def parse_payload(payload, fallback_name):
            status = payload.get("status") or {}
            life = payload.get("life") or {}
            state = str(status.get("state") or "").strip()
            description = str(status.get("description") or "").strip()
            current_life = int(life.get("current") or 0)
            is_hospital = state.lower() == "hospital" or current_life <= 0 or "hospital" in description.lower()
            return {
                "ok": is_hospital,
                "target_name": payload.get("name") or fallback_name,
                "state": state or "Unknown",
                "description": description or "-",
                "life_current": current_life,
            }

        def request_json(url, query):
            request = Request(
                f"{url}?{query}",
                headers={
                    "User-Agent": "TornIntel-DiscordBot/1.0",
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                payload_text = response.read().decode("utf-8", errors="replace")
            import json
            return json.loads(payload_text or "{}")

        last_error = None
        latest_observation = {
            "ok": False,
            "target_name": f"User {target_id}",
            "state": "Unknown",
            "description": "-",
            "life_current": 0,
        }

        # Two-pass check to reduce false negatives when hospital state has just changed.
        for attempt in range(2):
            for key in api_keys:
                checks = [
                    (url_v1, urlencode({"selections": "profile", "key": key, "comment": settings.comment})),
                    (url_v2, urlencode({"key": key, "comment": settings.comment})),
                ]

                for url, query in checks:
                    try:
                        payload = request_json(url, query)
                    except HTTPError as exc:
                        last_error = exc
                        continue
                    except Exception as exc:
                        last_error = exc
                        continue

                    if isinstance(payload, dict) and payload.get("error"):
                        error_obj = payload.get("error") or {}
                        last_error = RuntimeError(
                            f"Torn API error {error_obj.get('code', '?')}: {error_obj.get('error', 'unknown_error')}"
                        )
                        continue

                    observation = parse_payload(payload, f"User {target_id}")
                    latest_observation = observation
                    if observation["ok"]:
                        return observation

            if attempt == 0:
                time.sleep(1.2)

        if isinstance(last_error, HTTPError):
            raise RuntimeError(
                f"Torn API returned HTTP {last_error.code}. "
                "Check API key permissions, IP restrictions, and base URL configuration."
            )

        if last_error and latest_observation["state"] == "Unknown":
            raise RuntimeError(f"Torn API request failed: {last_error}")

        return latest_observation

    def build_revive_request_embed(
        request_id: str,
        requester_name: str,
        requester_torn_id: int | None,
        target_id: int,
        target_name: str,
        hospital_description: str,
        request_kind: str | None = None,
        cancelled: bool = False,
        fulfilled: bool = False,
        reviver_name: str | None = None,
        reviver_id: int | None = None,
        revived_timestamp: int | None = None,
    ):
        kind = str(request_kind or "revive").strip().lower()
        kind_label = "Contract" if kind == "contract" else "Revive"

        if fulfilled:
            color = 0x2ecc71
            title = f"{kind_label} Request Fulfilled"
        elif cancelled:
            color = 0x7f8c8d
            title = f"{kind_label} Request Cancelled"
        else:
            color = 0xe67e22
            title = f"{kind_label} Request Active"

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="Request ID", value=str(request_id), inline=False)
        embed.add_field(name="Kind", value=kind_label, inline=False)
        target_url = f"https://www.torn.com/profiles.php?XID={int(target_id)}"
        embed.add_field(name="Target", value=f"[{target_name} [{target_id}]]({target_url})", inline=False)
        requester_label = f"{requester_name} [{requester_torn_id}]" if requester_torn_id else requester_name
        if requester_torn_id:
            requester_url = f"https://www.torn.com/profiles.php?XID={int(requester_torn_id)}"
            requester_label = f"[{requester_label}]({requester_url})"
        embed.add_field(name="Requester", value=requester_label, inline=False)
        embed.add_field(name="Hospital", value=hospital_description or "-", inline=False)

        if fulfilled:
            if reviver_name or reviver_id:
                reviver_text = str(reviver_name or f"User {reviver_id}")
                if reviver_id:
                    reviver_url = f"https://www.torn.com/profiles.php?XID={int(reviver_id)}"
                    reviver_text = f"[{reviver_text} [{int(reviver_id)}]]({reviver_url})"
                embed.add_field(name="Reviver", value=reviver_text, inline=False)
                embed.add_field(
                    name="Pay Reviver",
                    value=f"Please send revive payment to {reviver_text}.",
                    inline=False,
                )
            if revived_timestamp:
                revived_text = datetime.fromtimestamp(int(revived_timestamp)).strftime("%m-%d %H:%M")
                embed.add_field(name="Revived At", value=revived_text, inline=False)
            embed.set_footer(text=f"Fulfillment detected from TornIntel {kind_label.lower()} records")
        elif cancelled:
            embed.set_footer(text="Cancelled from Discord command")
        else:
            embed.set_footer(text=f"Use /ti_revive_cancel <request_id> to cancel while pending")

        return embed

    async def run_and_respond(target_send, command_text: str, background: bool = False, timeout_override: int | None = None):
        if background:
            job_id = bridge.start_background(command_text)
            await send_embed_chunks(
                target_send,
                title="TornIntel Job Started",
                text=(
                    f"Job ID: {job_id}\n"
                    f"Command: {command_text}\n"
                    "Use /ti_jobs for status and /ti_job_output to tail logs."
                ),
                ok=True,
            )
            return

        result = bridge.run_foreground(command_text, timeout_seconds=timeout_override)
        status_prefix = "SUCCESS" if result["ok"] else "ERROR"
        body = f"[{status_prefix}] exit={result['returncode']}\n$ {command_text}\n\n{result['output']}"
        await send_embed_chunks(
            target_send,
            title="TornIntel Command Result",
            text=body,
            ok=result["ok"],
        )

    def _currency(value):
        return f"${float(value or 0):,.2f}"

    def load_latest_war_payout_rows(war_id: int):
        conn = sqlite3.connect(str(settings.database_path))
        conn.row_factory = sqlite3.Row
        try:
            latest_row = conn.execute(
                "SELECT MAX(calculated_at) AS calculated_at FROM payouts WHERE war_id = ?",
                (int(war_id),),
            ).fetchone()
            latest_ts = int(latest_row["calculated_at"] or 0) if latest_row else 0
            if latest_ts <= 0:
                return latest_ts, []

            rows = conn.execute(
                """
                SELECT *
                FROM payouts
                WHERE war_id = ? AND calculated_at = ?
                ORDER BY player_share DESC, player_name ASC
                """,
                (int(war_id), latest_ts),
            ).fetchall()
            return latest_ts, [dict(r) for r in rows]
        finally:
            conn.close()

    def build_war_payout_summary_text(war_id, total_payout, xanax_cost, faction_cut, bounty_cost, per_assist, pay_outside_hits, rows, calculated_at):
        faction_cut_amount = float(total_payout) * (float(faction_cut) / 100.0)
        after_cut = float(total_payout) - faction_cut_amount
        assist_cost_total = float(sum(float(r.get("assist_payout") or 0) for r in rows))
        distribution_pool = after_cut - float(xanax_cost) - float(bounty_cost) - assist_cost_total
        total_paid = float(sum(float(r.get("player_share") or 0) for r in rows))
        total_respect = float(sum(float(r.get("total_respect") or 0) for r in rows))
        dollar_per_respect = (distribution_pool / total_respect) if total_respect > 0 else 0.0
        calc_text = datetime.fromtimestamp(int(calculated_at)).strftime("%m-%d %H:%M:%S") if calculated_at else "-"

        lines = [
            f"War ID: {int(war_id)}",
            f"Calculated At: {calc_text}",
            "",
            f"Total Payout: {_currency(total_payout)}",
            f"Faction Cut ({float(faction_cut):.2f}%): {_currency(faction_cut_amount)}",
            f"After Faction Cut: {_currency(after_cut)}",
            f"Xanax Cost: {_currency(xanax_cost)}",
            f"Bounty Cost: {_currency(bounty_cost)}",
            f"Assist Cost Total: {_currency(assist_cost_total)}",
            f"Distribution Pool: {_currency(distribution_pool)}",
            f"Total Respect: {total_respect:,.2f}",
            f"$ / Respect: {_currency(dollar_per_respect)}",
            f"Outside Hits Enabled: {'YES' if bool(pay_outside_hits) else 'NO'}",
            f"Paid Out Total: {_currency(total_paid)}",
        ]
        if distribution_pool < 0:
            lines.append("WARNING: Distribution pool is negative. Reduce costs or increase total payout.")
        return "\n".join(lines)

    def build_war_payout_summary_metrics(total_payout, xanax_cost, faction_cut, bounty_cost, rows):
        faction_cut_amount = float(total_payout) * (float(faction_cut) / 100.0)
        after_cut = float(total_payout) - faction_cut_amount
        assist_cost_total = float(sum(float(r.get("assist_payout") or 0) for r in rows))
        distribution_pool = after_cut - float(xanax_cost) - float(bounty_cost) - assist_cost_total
        total_paid = float(sum(float(r.get("player_share") or 0) for r in rows))
        total_respect = float(sum(float(r.get("total_respect") or 0) for r in rows))
        dollar_per_respect = (distribution_pool / total_respect) if total_respect > 0 else 0.0
        return {
            "faction_cut_amount": faction_cut_amount,
            "after_cut": after_cut,
            "assist_cost_total": assist_cost_total,
            "distribution_pool": distribution_pool,
            "total_paid": total_paid,
            "total_respect": total_respect,
            "dollar_per_respect": dollar_per_respect,
        }

    def build_war_payout_top_text(rows, limit=20):
        if not rows:
            return "No payout rows found."

        shown = rows[: max(1, int(limit))]
        lines = [
            "Rank  Name               Hits  Ast   Respect      Share",
            "----  -----------------  ----  ---  ----------  -------------",
        ]
        for idx, row in enumerate(shown, start=1):
            name = str(row.get("player_name") or "?")[:17]
            hits = int(row.get("war_hits") or row.get("num_hits") or 0)
            ast = int(row.get("assist_count") or 0)
            respect = float(row.get("total_respect") or 0)
            share = float(row.get("player_share") or 0)
            lines.append(f"{idx:<4}  {name:<17}  {hits:>4}  {ast:>3}  {respect:>10.2f}  {_currency(share):>13}")

        return "\n".join(lines)

    def build_war_payout_full_ansi_text(rows):
        if not rows:
            return "No payout rows found."

        esc = "\u001b["
        reset = f"{esc}0m"
        bold_cyan = f"{esc}1;36m"
        dim = f"{esc}2;37m"
        green = f"{esc}32m"
        yellow = f"{esc}33m"
        blue = f"{esc}34m"
        white = f"{esc}37m"

        lines = [
            f"{bold_cyan}Rank  Name               Hits  Ast   Respect      Share{reset}",
            f"{dim}----  -----------------  ----  ---  ----------  -------------{reset}",
        ]
        for idx, row in enumerate(rows, start=1):
            name = str(row.get("player_name") or "?")[:17]
            hits = int(row.get("war_hits") or row.get("num_hits") or 0)
            ast = int(row.get("assist_count") or 0)
            respect = float(row.get("total_respect") or 0)
            share = float(row.get("player_share") or 0)

            if idx == 1:
                rank_color = yellow
            elif idx <= 3:
                rank_color = blue
            else:
                rank_color = white

            share_color = green if share > 0 else white
            lines.append(
                f"{rank_color}{idx:<4}{reset}  {white}{name:<17}{reset}  {hits:>4}  {ast:>3}  {respect:>10.2f}  {share_color}{_currency(share):>13}{reset}"
            )

        return "\n".join(lines)

    def build_war_payout_csv_bytes(rows):
        columns = [
            "war_id",
            "player_id",
            "player_name",
            "war_hits",
            "assist_count",
            "outside_hits",
            "total_respect",
            "respect_percentage",
            "assist_payout",
            "outside_payout",
            "player_share",
            "calculated_at",
        ]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            out = {k: row.get(k) for k in columns}
            writer.writerow(out)
        return stream.getvalue().encode("utf-8")

    def build_war_payout_image_bytes(rows, war_id: int, limit=20):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception as exc:
            return None, f"Could not create image export: Pillow not available ({type(exc).__name__})."

        total_rows = len(rows)
        limit = max(2, int(limit))
        if total_rows <= limit:
            shown = list(rows)
            omitted_count = 0
            gap_index = -1
        else:
            top_count = max(1, limit // 2)
            bottom_count = max(1, limit - top_count)
            top_rows = list(rows[:top_count])
            bottom_rows = list(rows[-bottom_count:])
            shown = top_rows + [None] + bottom_rows
            omitted_count = max(0, total_rows - (top_count + bottom_count))
            gap_index = len(top_rows)

        if omitted_count > 0:
            title = f"War {int(war_id)} - Payouts (Top + Bottom)"
        else:
            title = f"War {int(war_id)} - Payouts (Full)"
        font = ImageFont.load_default()
        header_font = ImageFont.load_default()

        def text_size(draw_obj, text):
            box = draw_obj.textbbox((0, 0), text, font=font)
            return box[2] - box[0], box[3] - box[1]

        def blend(c1, c2, t):
            t = max(0.0, min(1.0, float(t)))
            return tuple(int(round((a * (1.0 - t)) + (b * t))) for a, b in zip(c1, c2))

        scratch = Image.new("RGB", (8, 8), color=(255, 255, 255))
        scratch_draw = ImageDraw.Draw(scratch)
        title_w, title_h = text_size(scratch_draw, title)

        col_specs = [
            ("#", 36),
            ("Player", 190),
            ("Hits", 58),
            ("Ast", 50),
            ("Respect", 108),
            ("Share", 168),
        ]
        table_w = sum(w for _, w in col_specs)

        row_h = 24
        footer_h = 18
        footer_gap = 8
        pad_x = 22
        pad_y = 18
        width = max(760, pad_x * 2 + table_w)
        table_height = row_h * (len(shown) + 1)
        height = max(260, pad_y * 2 + title_h + 12 + table_height + footer_gap + footer_h)

        img = Image.new("RGB", (width, height), color=(16, 22, 30))
        draw = ImageDraw.Draw(img)

        for y in range(height):
            t = y / max(1, (height - 1))
            line_color = blend((15, 22, 30), (30, 44, 58), math.pow(t, 0.8))
            draw.line((0, y, width, y), fill=line_color)

        draw.rectangle((10, 10, width - 10, height - 10), outline=(72, 100, 126), width=1)

        draw.text((pad_x, pad_y), title, fill=(236, 245, 255), font=header_font)

        y = pad_y + title_h + 12
        x = pad_x
        draw.rectangle((x, y, x + table_w, y + row_h), fill=(41, 61, 82), outline=(105, 138, 167), width=1)
        cx = x
        for col_name, col_w in col_specs:
            draw.text((cx + 6, y + 6), col_name, fill=(222, 236, 250), font=font)
            cx += col_w

        real_rows = [r for r in shown if isinstance(r, dict)]
        max_share = max((float(r.get("player_share") or 0) for r in real_rows), default=0.0)
        y += row_h

        for idx, row in enumerate(shown, start=1):
            if row is None:
                gap_fill = (34, 52, 69)
                draw.rectangle((x, y, x + table_w, y + row_h), fill=gap_fill, outline=(86, 114, 139), width=1)
                gap_text = f"{omitted_count} middle row(s) omitted" if omitted_count > 0 else "middle rows omitted"
                gap_w, _ = text_size(draw, gap_text)
                gap_x = x + max(8, (table_w - gap_w) // 2)
                draw.text((gap_x, y + 6), gap_text, fill=(170, 194, 217), font=font)
                y += row_h
                continue

            share = float(row.get("player_share") or 0)
            share_t = (share / max_share) if max_share > 0 else 0.0

            base_row = blend((33, 49, 66), (45, 68, 92), 0.18 + (0.36 * share_t))
            if idx == 1:
                base_row = blend(base_row, (171, 134, 34), 0.35)
            elif idx == 2:
                base_row = blend(base_row, (136, 146, 158), 0.25)
            elif idx == 3:
                base_row = blend(base_row, (151, 102, 64), 0.28)

            draw.rectangle((x, y, x + table_w, y + row_h), fill=base_row, outline=(86, 114, 139), width=1)

            name = str(row.get("player_name") or "?")[:24]
            hits = int(row.get("war_hits") or row.get("num_hits") or 0)
            ast = int(row.get("assist_count") or 0)
            respect = float(row.get("total_respect") or 0)
            if gap_index >= 0 and idx > gap_index + 1:
                bottom_start_rank = total_rows - (len(shown) - idx)
                rank_label = f"#{bottom_start_rank}"
            else:
                rank_label = f"#{idx}"

            if idx == 1:
                rank_fill = (255, 226, 124)
            elif idx == 2:
                rank_fill = (219, 228, 237)
            elif idx == 3:
                rank_fill = (232, 170, 129)
            else:
                rank_fill = (222, 236, 248)

            row_fill = (236, 244, 252)

            cx = x
            draw.text((cx + 6, y + 6), rank_label, fill=rank_fill, font=font)
            cx += col_specs[0][1]
            draw.text((cx + 6, y + 6), name, fill=row_fill, font=font)
            cx += col_specs[1][1]
            draw.text((cx + 6, y + 6), str(hits), fill=row_fill, font=font)
            cx += col_specs[2][1]
            draw.text((cx + 6, y + 6), str(ast), fill=row_fill, font=font)
            cx += col_specs[3][1]
            draw.text((cx + 6, y + 6), f"{respect:,.2f}", fill=row_fill, font=font)
            cx += col_specs[4][1]
            draw.text((cx + 6, y + 6), _currency(share), fill=(192, 255, 214), font=font)

            y += row_h

        footer_y = y + footer_gap
        draw.line((x, footer_y - 4, x + table_w, footer_y - 4), fill=(79, 107, 132), width=1)
        foot = f"Generated: {datetime.now().strftime('%m-%d %H:%M:%S')}"
        draw.text((pad_x, footer_y), foot, fill=(150, 177, 201), font=font)

        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue(), None

    async def send_war_payout_rich_summary(interaction: discord.Interaction, *, war_id, total_payout, xanax_cost, faction_cut, bounty_cost, per_assist, pay_outside_hits, rows, calculated_at):
        metrics = build_war_payout_summary_metrics(total_payout, xanax_cost, faction_cut, bounty_cost, rows)
        pool_ok = metrics["distribution_pool"] >= 0
        calc_text = datetime.fromtimestamp(int(calculated_at)).strftime("%m-%d %H:%M:%S") if calculated_at else "-"

        embed = discord.Embed(
            title=f"War Payout Summary - War {int(war_id)}",
            color=(0x2ecc71 if pool_ok else 0xe74c3c),
        )
        embed.description = (
            f"Calculated: **{calc_text}**\n"
            f"Pool health: **{'Healthy' if pool_ok else 'Negative'}**"
        )
        embed.add_field(
            name="Pool Setup",
            value=(
                f"Total: **{_currency(total_payout)}**\n"
                f"Faction Cut ({float(faction_cut):.2f}%): **{_currency(metrics['faction_cut_amount'])}**\n"
                f"After Cut: **{_currency(metrics['after_cut'])}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Costs",
            value=(
                f"Xanax: **{_currency(xanax_cost)}**\n"
                f"Bounty: **{_currency(bounty_cost)}**\n"
                f"Assist Total: **{_currency(metrics['assist_cost_total'])}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Distribution",
            value=(
                f"Pool: **{_currency(metrics['distribution_pool'])}**\n"
                f"Respect: **{metrics['total_respect']:,.2f}**\n"
                f"$/Respect: **{_currency(metrics['dollar_per_respect'])}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Payout State",
            value=(
                f"Paid Out: **{_currency(metrics['total_paid'])}**\n"
                f"Per Assist: **{_currency(per_assist)}**\n"
                f"Outside Hits: **{'ON' if bool(pay_outside_hits) else 'OFF'}**"
            ),
            inline=False,
        )
        if not pool_ok:
            embed.add_field(
                name="Warning",
                value="Distribution pool is negative. Reduce costs or increase total payout.",
                inline=False,
            )
        embed.set_footer(text="Inputs applied and payout rows persisted to database")
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def send_war_payout_rich_top(interaction: discord.Interaction, *, war_id: int, rows, limit: int = 20):
        shown = rows[: max(1, int(limit))]
        medals = {1: "1st", 2: "2nd", 3: "3rd"}
        lines = []
        for idx, row in enumerate(shown, start=1):
            prefix = medals.get(idx, f"{idx:>2}")
            name = str(row.get("player_name") or "?")
            share = float(row.get("player_share") or 0)
            respect = float(row.get("total_respect") or 0)
            hits = int(row.get("war_hits") or row.get("num_hits") or 0)
            ast = int(row.get("assist_count") or 0)
            lines.append(
                f"{prefix}  {name} | Share {_currency(share)} | Respect {respect:,.2f} | Hits {hits} | Ast {ast}"
            )

        top_three = shown[:3]
        podium_text = "\n".join(
            f"{medals.get(i+1, str(i+1))}: **{str(r.get('player_name') or '?')}** ({_currency(float(r.get('player_share') or 0))})"
            for i, r in enumerate(top_three)
        ) or "No rows"

        embed = discord.Embed(
            title=f"War Payout Top Players - War {int(war_id)}",
            color=0x3498db,
            description=podium_text,
        )

        # Discord embed field value max length is 1024 characters.
        max_field_len = 1000
        field_chunks = []
        current = []
        current_len = 0
        for line in lines:
            addition = f"{line}\n"
            if current and (current_len + len(addition) > max_field_len):
                field_chunks.append("".join(current).rstrip("\n"))
                current = [addition]
                current_len = len(addition)
            else:
                current.append(addition)
                current_len += len(addition)
        if current:
            field_chunks.append("".join(current).rstrip("\n"))

        for idx, chunk in enumerate(field_chunks[:25], start=1):
            field_name = "Ranking" if idx == 1 else f"Ranking (cont. {idx})"
            embed.add_field(name=field_name, value=chunk, inline=False)

        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def create_revive_request_flow(interaction: discord.Interaction, target_id: int | None = None):
        requester_discord_id = int(interaction.user.id)
        requester_name = str(getattr(interaction.user, "display_name", None) or interaction.user.name)
        requester_torn_id = revive_store.get_user_torn_id(requester_discord_id)

        if requester_torn_id is None:
            await send_embed_chunks(
                interaction.followup.send,
                title="Revive Request Error",
                text="No Torn ID linked for your Discord user. Run /add first.",
                ok=False,
            )
            return

        resolved_target_id = int(target_id) if target_id is not None else int(requester_torn_id)

        try:
            status = check_hospital_status(target_id=resolved_target_id)
        except Exception as exc:
            await send_embed_chunks(
                interaction.followup.send,
                title="Revive Request Error",
                text=f"Could not validate hospital status from Torn API: {type(exc).__name__}: {exc}",
                ok=False,
            )
            return

        if not status.get("ok"):
            await send_embed_chunks(
                interaction.followup.send,
                title="Revive Request Rejected",
                text=(
                    f"Target {status.get('target_name')} [{resolved_target_id}] is not currently in hospital.\n"
                    f"State: {status.get('state')}\n"
                    f"Status: {status.get('description')}"
                ),
                ok=False,
            )
            return

        target_name = str(status.get("target_name") or f"User {target_id}")
        request_id = revive_store.create_request(
            discord_user_id=requester_discord_id,
            torn_user_id=requester_torn_id,
            target_id=resolved_target_id,
            target_name=target_name,
            requester_name=requester_name,
        )

        revive_channel = await resolve_revive_channel(interaction)
        request_embed = build_revive_request_embed(
            request_id=request_id,
            requester_name=requester_name,
            requester_torn_id=requester_torn_id,
            target_id=resolved_target_id,
            target_name=target_name,
            hospital_description=str(status.get("description") or "In hospital"),
            request_kind="revive",
            cancelled=False,
        )
        message = await revive_channel.send(embed=request_embed, allowed_mentions=discord.AllowedMentions.none())
        revive_store.attach_message(request_id, channel_id=int(revive_channel.id), message_id=int(message.id))

        await send_embed_chunks(
            interaction.followup.send,
            title="Revive Request Created",
            text=(
                f"Request ID: {request_id}\n"
                f"Target: {target_name} [{resolved_target_id}]\n"
                f"Posted in channel: <#{revive_channel.id}>"
            ),
            ok=True,
        )

    async def revive_fulfillment_watcher():
        last_reconcile_at = 0.0
        poll_seconds = max(8, int(getattr(settings, "discord_revive_poll_seconds", 20) or 20))

        while not bot.is_closed():
            try:
                now = time.time()
                active_rows = revive_store.list_active_requests(limit=200)

                # Mirror listener behavior: when pending revive requests exist,
                # periodically sync revives and reconcile requests to detect fulfillment.
                if active_rows and (now - last_reconcile_at) >= poll_seconds:
                    sync_result = bridge.run_foreground(
                        "sync revives --mode live",
                        timeout_seconds=max(120, int(timeout_seconds or 180)),
                    )
                    if not sync_result.get("ok") and logger:
                        logger.warning(
                            f"Discord revive watcher sync failed (exit {sync_result.get('returncode')}): "
                            f"{str(sync_result.get('output') or '').splitlines()[-1] if sync_result.get('output') else 'no output'}"
                        )

                    reconcile_result = bridge.run_foreground(
                        "revive_requests reconcile --status pending --limit 200 --window-seconds 21600",
                        timeout_seconds=max(120, int(timeout_seconds or 180)),
                    )
                    if not reconcile_result.get("ok") and logger:
                        logger.warning(
                            f"Discord revive watcher reconcile failed (exit {reconcile_result.get('returncode')}): "
                            f"{str(reconcile_result.get('output') or '').splitlines()[-1] if reconcile_result.get('output') else 'no output'}"
                        )

                    last_reconcile_at = time.time()

                rows = revive_store.list_fulfilled_pending_embed_updates(limit=50)
                for row in rows:
                    request_id = str(row.get("request_id"))
                    channel_id = row.get("channel_id")
                    message_id = row.get("message_id")

                    if not channel_id or not message_id:
                        revive_store.mark_embed_fulfilled(request_id)
                        continue

                    channel = bot.get_channel(int(channel_id))
                    if channel is None:
                        try:
                            channel = await bot.fetch_channel(int(channel_id))
                        except Exception:
                            revive_store.mark_embed_fulfilled(request_id)
                            continue

                    try:
                        message = await channel.fetch_message(int(message_id))
                        embed = build_revive_request_embed(
                            request_id=request_id,
                            requester_name=str(row.get("requester_name") or row.get("discord_user_id") or "Requester"),
                            requester_torn_id=row.get("torn_user_id"),
                            target_id=int(row.get("target_id") or 0),
                            target_name=str(row.get("target_name") or f"User {row.get('target_id') or '?'}"),
                            hospital_description="Revive completed",
                            request_kind=row.get("request_kind"),
                            fulfilled=True,
                            reviver_name=str(row.get("fulfilled_by_name") or "") if row.get("fulfilled_by_name") is not None else None,
                            reviver_id=int(row.get("fulfilled_by_id")) if row.get("fulfilled_by_id") is not None else None,
                            revived_timestamp=int(row.get("revived_timestamp")) if row.get("revived_timestamp") is not None else None,
                        )
                        await message.edit(embed=embed)
                        revive_store.mark_embed_fulfilled(request_id)
                    except (discord.NotFound, discord.Forbidden):
                        revive_store.mark_embed_fulfilled(request_id)
                    except Exception:
                        # Keep as active for retry on transient Discord API errors.
                        continue
            except Exception as exc:
                if logger:
                    logger.warning(f"Revive fulfillment watcher error: {type(exc).__name__}: {exc}")

            await asyncio.sleep(5)

    async def report_type_autocomplete(interaction, current: str):
        module = str(getattr(interaction.namespace, "module", "") or "")
        types = REPORT_TYPES_BY_MODULE.get(module, [])
        current_l = (current or "").lower()
        options = [t for t in types if current_l in t.lower()]
        return [app_commands.Choice(name=t, value=t) for t in options[:25]]

    async def war_id_autocomplete(_interaction, current: str):
        choices = autocomplete.recent_wars(current=current, limit=25)
        return [app_commands.Choice(name=name[:100], value=value) for name, value in choices[:25]]

    async def chain_id_autocomplete(_interaction, current: str):
        choices = autocomplete.recent_chains(current=current, limit=25)
        return [app_commands.Choice(name=name[:100], value=value) for name, value in choices[:25]]

    async def item_autocomplete(_interaction, current: str):
        names = autocomplete.items(current=current, limit=25)
        return [app_commands.Choice(name=name[:100], value=name) for name in names[:25]]

    async def category_autocomplete(_interaction, current: str):
        categories = autocomplete.categories(current=current, limit=25)
        return [app_commands.Choice(name=name[:100], value=name) for name in categories[:25]]

    @bot.event
    async def on_ready():
        nonlocal revive_watcher_task
        if logger:
            logger.success(f"Discord bot logged in as {bot.user}")
            try:
                permissions = discord.Permissions(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    read_message_history=True,
                )
                invite_url = discord.utils.oauth_url(
                    int(bot.user.id),
                    permissions=permissions,
                    scopes=("bot", "applications.commands"),
                )
                logger.info(f"Discord bot invite URL: {invite_url}")
            except Exception as exc:
                logger.warning(f"Unable to generate invite URL automatically: {type(exc).__name__}: {exc}")

        try:
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                try:
                    bot.tree.copy_global_to(guild=guild)
                    await bot.tree.sync(guild=guild)
                    if logger:
                        logger.info(f"Discord slash commands synced to guild {guild_id}")
                except discord.Forbidden:
                    if logger:
                        logger.warning(
                            f"Guild slash sync failed for guild {guild_id}: Missing Access. "
                            "Falling back to global sync."
                        )
                    await bot.tree.sync()
                    if logger:
                        logger.info("Discord global slash commands synced (fallback)")
            else:
                await bot.tree.sync()
                if logger:
                    logger.info("Discord global slash commands synced")
        except Exception as exc:
            if logger:
                logger.error(f"Failed to sync slash commands: {type(exc).__name__}: {exc}")

        if revive_watcher_task is None or revive_watcher_task.done():
            revive_watcher_task = asyncio.create_task(revive_fulfillment_watcher())
            if logger:
                logger.info("Started revive fulfillment watcher task")

    if allow_prefix_commands:
        @bot.command(name="ti")
        async def ti_message(ctx, *, command: str):
            await run_and_respond(ctx.send, command_text=command, background=False, timeout_override=timeout_seconds)

        @bot.command(name="ti_bg")
        async def ti_background(ctx, *, command: str):
            await run_and_respond(ctx.send, command_text=command, background=True)

        @bot.command(name="ti_jobs")
        async def ti_jobs(ctx):
            rows = bridge.list_jobs()
            await send_embed_chunks(ctx.send, title="TornIntel Jobs", text=_render_job_rows(rows), ok=True)

        @bot.command(name="ti_stop")
        async def ti_stop(ctx, job_id: str):
            ok, text = bridge.stop_job(job_id)
            await send_embed_chunks(ctx.send, title="TornIntel Job Stop", text=text, ok=ok)

        @bot.command(name="ti_output")
        async def ti_output(ctx, job_id: str, tail_lines: int = DEFAULT_TAIL_LINES):
            ok, text = bridge.get_job_output(job_id, tail_lines=tail_lines)
            await send_embed_chunks(ctx.send, title="TornIntel Job Output", text=text, ok=ok)

        @bot.command(name="add")
        async def add_torn_user(ctx, torn_user_id: int):
            revive_store.set_user_torn_id(ctx.author.id, torn_user_id)
            await send_embed_chunks(
                ctx.send,
                title="Torn ID Linked",
                text=f"Linked Discord user {ctx.author.display_name} to Torn ID {int(torn_user_id)}.",
                ok=True,
            )

        @bot.command(name="revive")
        async def revive_cmd(ctx, target_id: int | None = None):
            class _CtxInteraction:
                def __init__(self, source_ctx):
                    self.user = source_ctx.author
                    self.channel = source_ctx.channel
                    self.channel_id = int(source_ctx.channel.id)
                    self.followup = type("Followup", (), {"send": source_ctx.send})

            interaction_like = _CtxInteraction(ctx)
            await create_revive_request_flow(interaction_like, target_id=int(target_id) if target_id is not None else None)

        @bot.command(name="r")
        async def revive_short_cmd(ctx, target_id: int | None = None):
            await revive_cmd(ctx, target_id)

        @bot.command(name="revive_cancel")
        async def revive_cancel_cmd(ctx, request_id: str):
            allow_force = bool(getattr(ctx.author.guild_permissions, "manage_messages", False))
            ok, reason, _request_row = revive_store.cancel_request(
                request_id=str(request_id),
                discord_user_id=int(ctx.author.id),
                allow_force=allow_force,
            )
            if not ok:
                reason_text = {
                    "request_not_found": "No request found for that ID.",
                    "request_not_active": "That request is not active.",
                    "not_owner": "Only the original requester (or a moderator) can cancel this request.",
                    "already_closed": "This request is already closed.",
                }.get(reason, f"Unable to cancel request ({reason}).")
                await send_embed_chunks(ctx.send, title="Revive Cancel Failed", text=reason_text, ok=False)
                return

            await send_embed_chunks(ctx.send, title="Revive Request Cancelled", text=f"Cancelled request {request_id}.", ok=True)

        @bot.command(name="revive_active")
        async def revive_active_cmd(ctx, limit: int = 25):
            rows = revive_store.list_active_requests(limit=max(1, min(100, int(limit))))
            if not rows:
                await send_embed_chunks(ctx.send, title="Active Revive Requests", text="No active revive requests.", ok=True)
                return

            lines = []
            for row in rows:
                ts = int(row.get("requested_timestamp") or row.get("created_at") or 0)
                ts_text = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "-"
                target_name = row.get("target_name") or f"User {row.get('target_id') or '?'}"
                lines.append(
                    f"{ts_text} | {row.get('request_id')} | {target_name} [{row.get('target_id')}] | requester={row.get('requester_name') or row.get('discord_user_id')}"
                )

            await send_embed_chunks(ctx.send, title="Active Revive Requests", text="\n".join(lines), ok=True)

    @bot.tree.command(name="ti", description="Run any TornIntel CLI command")
    @app_commands.describe(
        command="CLI command to run, without python main.py",
        background="Run in background mode for long-running commands",
        timeout_seconds="Foreground timeout in seconds",
    )
    async def ti_slash(interaction: discord.Interaction, command: str, background: bool = False, timeout_seconds: int = 180):
        await interaction.response.defer(thinking=True)

        async def send_followup(**kwargs):
            await interaction.followup.send(**kwargs)

        await run_and_respond(
            send_followup,
            command_text=command,
            background=background,
            timeout_override=timeout_seconds,
        )

    @bot.tree.command(name="add", description="Link your Discord user to your Torn player ID")
    @app_commands.describe(user_id="Your Torn player ID")
    async def add_slash(interaction: discord.Interaction, user_id: int):
        await interaction.response.defer(thinking=False)
        revive_store.set_user_torn_id(interaction.user.id, int(user_id))
        await send_embed_chunks(
            interaction.followup.send,
            title="Torn ID Linked",
            text=f"Linked Discord user {interaction.user.display_name} to Torn ID {int(user_id)}.",
            ok=True,
        )

    @bot.tree.command(name="revive", description="Request a revive for a target Torn ID")
    @app_commands.describe(target_id="Optional target Torn ID (omit for yourself)")
    async def revive_slash(interaction: discord.Interaction, target_id: int | None = None):
        await interaction.response.defer(thinking=True)
        await create_revive_request_flow(interaction, target_id=int(target_id) if target_id is not None else None)

    @bot.tree.command(name="r", description="Short alias of /revive")
    @app_commands.describe(target_id="Optional target Torn ID (omit for yourself)")
    async def revive_short_slash(interaction: discord.Interaction, target_id: int | None = None):
        await interaction.response.defer(thinking=True)
        await create_revive_request_flow(interaction, target_id=int(target_id) if target_id is not None else None)

    @bot.tree.command(name="ti_revive_cancel", description="Cancel a pending revive request")
    @app_commands.describe(request_id="Revive request ID")
    async def ti_revive_cancel_slash(interaction: discord.Interaction, request_id: str):
        await interaction.response.defer(thinking=True)

        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        allow_force = bool(member and member.guild_permissions.manage_messages)
        ok, reason, request_row = revive_store.cancel_request(
            request_id=str(request_id),
            discord_user_id=int(interaction.user.id),
            allow_force=allow_force,
        )

        if not ok:
            reason_text = {
                "request_not_found": "No request found for that ID.",
                "request_not_active": "That request is not active.",
                "not_owner": "Only the original requester (or a moderator) can cancel this request.",
                "already_closed": "This request is already closed.",
            }.get(reason, f"Unable to cancel request ({reason}).")
            await send_embed_chunks(
                interaction.followup.send,
                title="Revive Cancel Failed",
                text=reason_text,
                ok=False,
            )
            return

        channel_id = request_row.get("channel_id")
        message_id = request_row.get("message_id")
        if channel_id and message_id:
            try:
                channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
                message = await channel.fetch_message(int(message_id))
                edited = build_revive_request_embed(
                    request_id=str(request_id),
                    requester_name=str(interaction.user.display_name),
                    requester_torn_id=request_row.get("torn_user_id"),
                    target_id=int(request_row.get("target_id") or 0),
                    target_name=str(request_row.get("target_name") or f"User {request_row.get('target_id') or '?'}"),
                    hospital_description="Cancelled via Discord command",
                    request_kind=request_row.get("request_kind"),
                    cancelled=True,
                )
                await message.edit(embed=edited)
            except Exception:
                pass

        await send_embed_chunks(
            interaction.followup.send,
            title="Revive Request Cancelled",
            text=f"Cancelled request {request_id}.",
            ok=True,
        )

    @bot.tree.command(name="ti_revive_active", description="List active revive requests")
    @app_commands.describe(limit="Maximum rows to show")
    async def ti_revive_active_slash(interaction: discord.Interaction, limit: int = 25):
        await interaction.response.defer(thinking=False)
        rows = revive_store.list_active_requests(limit=max(1, min(100, int(limit))))
        if not rows:
            await send_embed_chunks(
                interaction.followup.send,
                title="Active Revive Requests",
                text="No active revive requests.",
                ok=True,
            )
            return

        lines = []
        for row in rows:
            ts = int(row.get("requested_timestamp") or row.get("created_at") or 0)
            ts_text = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "-"
            target_name = row.get("target_name") or f"User {row.get('target_id') or '?'}"
            lines.append(
                f"{ts_text} | {row.get('request_id')} | {target_name} [{row.get('target_id')}] | requester={row.get('requester_name') or row.get('discord_user_id')}"
            )

        await send_embed_chunks(
            interaction.followup.send,
            title="Active Revive Requests",
            text="\n".join(lines),
            ok=True,
        )

    @bot.tree.command(name="ti_revive_channel", description="View or set the channel used for active revive request posts")
    @app_commands.describe(channel_ref="Optional channel ID or mention, e.g. 123... or <#123...>")
    async def ti_revive_channel_slash(interaction: discord.Interaction, channel_ref: str | None = None):
        await interaction.response.defer(thinking=False)
        if channel_ref is not None:
            if interaction.guild is None:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="Revive Channel Update Failed",
                    text="Run this command in a server channel (not DM).",
                    ok=False,
                )
                return

            member = interaction.guild.get_member(interaction.user.id)
            interaction_perms = getattr(interaction, "permissions", None)
            has_manage = False

            if interaction_perms is not None:
                has_manage = bool(
                    getattr(interaction_perms, "administrator", False)
                    or getattr(interaction_perms, "manage_guild", False)
                    or getattr(interaction_perms, "manage_channels", False)
                )

            if not has_manage and member is not None:
                guild_perms = member.guild_permissions
                has_manage = bool(
                    getattr(guild_perms, "administrator", False)
                    or getattr(guild_perms, "manage_guild", False)
                    or getattr(guild_perms, "manage_channels", False)
                )

            if not has_manage:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="Revive Channel Update Failed",
                    text="You need Manage Channels (or Administrator/Manage Server) permission to set revive channel.",
                    ok=False,
                )
                return

            parsed_channel_id = _parse_channel_id(channel_ref)
            if parsed_channel_id is None:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="Revive Channel Update Failed",
                    text="Use a channel ID like 123456789012345678 or a mention like <#123456789012345678>.",
                    ok=False,
                )
                return

            try:
                target_channel = bot.get_channel(int(parsed_channel_id)) or await bot.fetch_channel(int(parsed_channel_id))
            except Exception:
                target_channel = None

            if target_channel is None:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="Revive Channel Update Failed",
                    text="Invalid channel ID or channel is not accessible by the bot.",
                    ok=False,
                )
                return

            revive_store.set_setting("revive_channel_id", str(int(parsed_channel_id)))
            await send_embed_chunks(
                interaction.followup.send,
                title="Revive Channel Updated",
                text=f"Active revive requests will now post in <#{int(parsed_channel_id)}>.",
                ok=True,
            )
            return

        current = resolve_revive_channel_id(interaction.channel_id)
        if current:
            await send_embed_chunks(
                interaction.followup.send,
                title="Revive Channel",
                text=f"Current revive channel: <#{current}>",
                ok=True,
            )
        else:
            await send_embed_chunks(
                interaction.followup.send,
                title="Revive Channel",
                text="No explicit revive channel set. Requests post in the command channel.",
                ok=True,
            )

    @bot.tree.command(name="ti_report", description="Structured report command with autocomplete")
    @app_commands.describe(
        module="CLI report module",
        report_type="Report type",
        chain_id="Chain ID when needed",
        war_id="War ID when needed",
        total_payout="Required for war_payout report type",
        xanax_cost="Optional payout deduction",
        faction_cut="Optional faction cut percent",
        bounty_cost="Optional bounty deduction",
        per_assist="Optional assist bonus",
        pay_outside_hits="Set true to pay hits outside war",
        hit_number="Hit number for chain_hit",
        player="Player filter when needed",
        item="Item filter when needed (revives requests_list uses target-name)",
        category="Category filter when needed (revives requests_list uses status)",
        top_n="Top N rows for leaderboard-style reports",
        limit="Row limit for list reports",
        view_summary="For war_payout: show summary embed",
        view_top="For war_payout: show top players embed",
        view_full="For war_payout: show full payout table",
        export_csv="For war_payout: attach CSV export",
        export_image="For war_payout: attach PNG table image",
        top_rows="For war_payout: rows for top/image views",
        background="Run in background mode",
    )
    @app_commands.choices(
        module=[
            app_commands.Choice(name="attacks", value="attacks"),
            app_commands.Choice(name="chains", value="chains"),
            app_commands.Choice(name="rankedwars", value="rankedwars"),
            app_commands.Choice(name="armoury", value="armoury"),
            app_commands.Choice(name="crimes", value="crimes"),
            app_commands.Choice(name="revives", value="revives"),
        ]
    )
    @app_commands.autocomplete(report_type=report_type_autocomplete, war_id=war_id_autocomplete, chain_id=chain_id_autocomplete, item=item_autocomplete, category=category_autocomplete)
    async def ti_report_slash(
        interaction: discord.Interaction,
        module: str,
        report_type: str,
        chain_id: int | None = None,
        war_id: int | None = None,
        total_payout: float | None = None,
        xanax_cost: float = 0.0,
        faction_cut: float = 0.0,
        bounty_cost: float = 0.0,
        per_assist: float = 0.0,
        pay_outside_hits: bool = False,
        hit_number: int | None = None,
        player: str | None = None,
        item: str | None = None,
        category: str | None = None,
        top_n: int = 10,
        limit: int = 50,
        view_summary: bool = True,
        view_top: bool = True,
        view_full: bool = False,
        export_csv: bool = False,
        export_image: bool = False,
        top_rows: int = 20,
        background: bool = False,
    ):
        await interaction.response.defer(thinking=True)

        if module == "revives" and report_type != "requests_list":
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel Command Error",
                text="For revives, use /ti_revives for revive history search or /ti_report with report_type=requests_list.",
                ok=False,
            )
            return

        if report_type == "war_payout" and (war_id is None or total_payout is None):
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel Command Error",
                text="war_payout requires war_id and total_payout. Consider using /ti_war_payout for a guided flow.",
                ok=False,
            )
            return

        if module == "rankedwars" and report_type == "war_payout":
            if total_payout is None or total_payout <= 0:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="TornIntel Command Error",
                    text="total_payout must be greater than 0.",
                    ok=False,
                )
                return

            if faction_cut < 0 or faction_cut > 100:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="TornIntel Command Error",
                    text="faction_cut must be between 0 and 100.",
                    ok=False,
                )
                return

            if xanax_cost < 0 or bounty_cost < 0 or per_assist < 0:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="TornIntel Command Error",
                    text="xanax_cost, bounty_cost, and per_assist must be non-negative.",
                    ok=False,
                )
                return

            if top_rows < 1 or top_rows > 50:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="TornIntel Command Error",
                    text="top_rows must be between 1 and 50.",
                    ok=False,
                )
                return

            if not (view_summary or view_top or view_full or export_csv or export_image):
                await send_embed_chunks(
                    interaction.followup.send,
                    title="TornIntel Command Error",
                    text="Enable at least one output view: summary, top, full, csv, or image.",
                    ok=False,
                )
                return

        command_text = _build_report_command(
            module=module,
            report_type=report_type,
            chain_id=chain_id,
            war_id=war_id,
            total_payout=total_payout,
            xanax_cost=xanax_cost,
            faction_cut=faction_cut,
            bounty_cost=bounty_cost,
            per_assist=per_assist,
            pay_outside_hits=1 if pay_outside_hits else 0,
            hit_number=hit_number,
            player=player,
            item=item,
            category=category,
            top_n=top_n,
            limit=limit,
        )

        async def send_followup(**kwargs):
            await interaction.followup.send(**kwargs)

        if module == "rankedwars" and report_type == "war_payout":
            if background:
                await run_and_respond(send_followup, command_text=command_text, background=True, timeout_override=timeout_seconds)
                return

            result = bridge.run_foreground(command_text, timeout_seconds=timeout_seconds)
            if not result.get("ok"):
                await send_embed_chunks(
                    interaction.followup.send,
                    title="TornIntel War Payout Failed",
                    text=f"$ {command_text}\n\n{result.get('output') or '(no output)'}",
                    ok=False,
                )
                return

            calculated_at, rows = load_latest_war_payout_rows(war_id=int(war_id))
            if not rows:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="TornIntel War Payout Result",
                    text=f"Calculation command succeeded, but no payout rows were found for war {war_id}.\n\n{result.get('output') or '(no output)'}",
                    ok=False,
                )
                return

            if view_summary:
                await send_war_payout_rich_summary(
                    interaction,
                    war_id=war_id,
                    total_payout=total_payout,
                    xanax_cost=xanax_cost,
                    faction_cut=faction_cut,
                    bounty_cost=bounty_cost,
                    per_assist=per_assist,
                    pay_outside_hits=pay_outside_hits,
                    rows=rows,
                    calculated_at=calculated_at,
                )

            if view_top:
                await send_war_payout_rich_top(
                    interaction,
                    war_id=int(war_id),
                    rows=rows,
                    limit=top_rows,
                )

            if view_full:
                full_text = build_war_payout_full_ansi_text(rows)
                await send_embed_chunks(
                    interaction.followup.send,
                    title=f"War Payout Full Table - War {int(war_id)}",
                    text=full_text,
                    ok=True,
                )

            if export_csv:
                csv_bytes = build_war_payout_csv_bytes(rows)
                csv_name = f"war_payout_{int(war_id)}_{int(calculated_at or 0)}.csv"
                await interaction.followup.send(
                    content=f"CSV export for war {int(war_id)}.",
                    file=discord.File(io.BytesIO(csv_bytes), filename=csv_name),
                    allowed_mentions=discord.AllowedMentions.none(),
                )

            if export_image:
                image_bytes, image_error = build_war_payout_image_bytes(rows, war_id=int(war_id), limit=len(rows))
                if image_bytes:
                    image_name = f"war_payout_top_{int(war_id)}_{int(calculated_at or 0)}.png"
                    await interaction.followup.send(
                        content=f"Image export for war {int(war_id)}.",
                        file=discord.File(io.BytesIO(image_bytes), filename=image_name),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await send_embed_chunks(
                        interaction.followup.send,
                        title="War Payout Image Export",
                        text=image_error or "Could not build image export.",
                        ok=False,
                    )
            return

        await run_and_respond(send_followup, command_text=command_text, background=background, timeout_override=timeout_seconds)

    @bot.tree.command(name="ti_war_payout", description="Guided ranked war payout calculator")
    @app_commands.describe(
        war_id="War ID",
        total_payout="Total payout pool",
        xanax_cost="Xanax deduction",
        faction_cut="Faction cut percentage",
        bounty_cost="Bounty deduction",
        per_assist="Pay per assist",
        pay_outside_hits="Pay hits outside war",
        view_summary="Show summary embed",
        view_top="Show top players embed",
        view_full="Show full payout table (all players)",
        export_csv="Attach CSV export",
        export_image="Attach PNG table image",
        top_rows="Rows shown in top embed view",
        background="Run in background mode",
    )
    @app_commands.autocomplete(war_id=war_id_autocomplete)
    async def ti_war_payout_slash(
        interaction: discord.Interaction,
        war_id: int,
        total_payout: float,
        xanax_cost: float = 0.0,
        faction_cut: float = 0.0,
        bounty_cost: float = 0.0,
        per_assist: float = 0.0,
        pay_outside_hits: bool = False,
        view_summary: bool = True,
        view_top: bool = True,
        view_full: bool = False,
        export_csv: bool = False,
        export_image: bool = False,
        top_rows: int = 20,
        background: bool = False,
    ):
        await interaction.response.defer(thinking=True)

        if total_payout <= 0:
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel Command Error",
                text="total_payout must be greater than 0.",
                ok=False,
            )
            return

        if faction_cut < 0 or faction_cut > 100:
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel Command Error",
                text="faction_cut must be between 0 and 100.",
                ok=False,
            )
            return

        if xanax_cost < 0 or bounty_cost < 0 or per_assist < 0:
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel Command Error",
                text="xanax_cost, bounty_cost, and per_assist must be non-negative.",
                ok=False,
            )
            return

        if top_rows < 1 or top_rows > 50:
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel Command Error",
                text="top_rows must be between 1 and 50.",
                ok=False,
            )
            return

        if not (view_summary or view_top or view_full or export_csv or export_image):
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel Command Error",
                text="Enable at least one output view: summary, top, full, csv, or image.",
                ok=False,
            )
            return

        command_text = _build_war_payout_command(
            war_id=war_id,
            total_payout=total_payout,
            xanax_cost=xanax_cost,
            faction_cut=faction_cut,
            bounty_cost=bounty_cost,
            per_assist=per_assist,
            pay_outside_hits=1 if pay_outside_hits else 0,
        )

        if background:
            async def send_followup(**kwargs):
                await interaction.followup.send(**kwargs)
            await run_and_respond(send_followup, command_text=command_text, background=True, timeout_override=timeout_seconds)
            return

        result = bridge.run_foreground(command_text, timeout_seconds=timeout_seconds)
        if not result.get("ok"):
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel War Payout Failed",
                text=f"$ {command_text}\n\n{result.get('output') or '(no output)'}",
                ok=False,
            )
            return

        calculated_at, rows = load_latest_war_payout_rows(war_id=int(war_id))
        if not rows:
            await send_embed_chunks(
                interaction.followup.send,
                title="TornIntel War Payout Result",
                text=f"Calculation command succeeded, but no payout rows were found for war {war_id}.\n\n{result.get('output') or '(no output)'}",
                ok=False,
            )
            return

        if view_summary:
            await send_war_payout_rich_summary(
                interaction,
                war_id=war_id,
                total_payout=total_payout,
                xanax_cost=xanax_cost,
                faction_cut=faction_cut,
                bounty_cost=bounty_cost,
                per_assist=per_assist,
                pay_outside_hits=pay_outside_hits,
                rows=rows,
                calculated_at=calculated_at,
            )

        if view_top:
            await send_war_payout_rich_top(
                interaction,
                war_id=int(war_id),
                rows=rows,
                limit=top_rows,
            )

        if view_full:
            full_text = build_war_payout_full_ansi_text(rows)
            await send_embed_chunks(
                interaction.followup.send,
                title=f"War Payout Full Table - War {int(war_id)}",
                text=full_text,
                ok=True,
            )

        if export_csv:
            csv_bytes = build_war_payout_csv_bytes(rows)
            csv_name = f"war_payout_{int(war_id)}_{int(calculated_at or 0)}.csv"
            await interaction.followup.send(
                content=f"CSV export for war {int(war_id)}.",
                file=discord.File(io.BytesIO(csv_bytes), filename=csv_name),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        if export_image:
            image_bytes, image_error = build_war_payout_image_bytes(rows, war_id=int(war_id), limit=len(rows))
            if image_bytes:
                image_name = f"war_payout_top_{int(war_id)}_{int(calculated_at or 0)}.png"
                await interaction.followup.send(
                    content=f"Image export for war {int(war_id)}.",
                    file=discord.File(io.BytesIO(image_bytes), filename=image_name),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await send_embed_chunks(
                    interaction.followup.send,
                    title="War Payout Image Export",
                    text=image_error or "Could not build image export.",
                    ok=False,
                )

    @bot.tree.command(name="ti_revives", description="Guided revives search from local DB")
    @app_commands.describe(
        reviver="Reviver name contains",
        target="Target name contains",
        result="Result filter (success, fail, etc.)",
        limit="Max rows",
        oldest="Oldest first",
        background="Run in background mode",
    )
    async def ti_revives_slash(
        interaction: discord.Interaction,
        reviver: str | None = None,
        target: str | None = None,
        result: str | None = None,
        limit: int = 25,
        oldest: bool = False,
        background: bool = False,
    ):
        await interaction.response.defer(thinking=True)
        command_text = _build_revives_search_command(
            reviver=reviver,
            target=target,
            result=result,
            limit=limit,
            oldest=oldest,
        )

        async def send_followup(**kwargs):
            await interaction.followup.send(**kwargs)

        await run_and_respond(send_followup, command_text=command_text, background=background, timeout_override=timeout_seconds)

    @bot.tree.command(name="ti_jobs", description="List TornIntel Discord background jobs")
    async def ti_jobs_slash(interaction: discord.Interaction):
        await interaction.response.defer(thinking=False)
        rows = bridge.list_jobs()
        await send_embed_chunks(interaction.followup.send, title="TornIntel Jobs", text=_render_job_rows(rows), ok=True)

    @bot.tree.command(name="ti_job_stop", description="Stop a TornIntel Discord background job")
    @app_commands.describe(job_id="Job ID shown by ti_jobs")
    async def ti_job_stop_slash(interaction: discord.Interaction, job_id: str):
        await interaction.response.defer(thinking=False)
        ok, text = bridge.stop_job(job_id)
        await send_embed_chunks(interaction.followup.send, title="TornIntel Job Stop", text=text, ok=ok)

    @bot.tree.command(name="ti_job_output", description="Tail output from a TornIntel Discord background job")
    @app_commands.describe(job_id="Job ID shown by ti_jobs", tail_lines="How many trailing lines to show")
    async def ti_job_output_slash(interaction: discord.Interaction, job_id: str, tail_lines: int = DEFAULT_TAIL_LINES):
        await interaction.response.defer(thinking=False)
        ok, text = bridge.get_job_output(job_id, tail_lines=tail_lines)
        await send_embed_chunks(interaction.followup.send, title="TornIntel Job Output", text=text, ok=ok)

    if logger:
        if not settings.discord_enable_message_content_intent:
            logger.warning(
                "Discord message-content intent is disabled. Slash commands will work; prefix commands may not. "
                "Set TORN_DISCORD_ENABLE_MESSAGE_CONTENT_INTENT=1 and enable Message Content Intent in Discord Developer Portal to use !ti commands."
            )
        logger.info(
            f"Starting Discord bot bridge with prefix {prefix}. "
            "Use /ti_report for structured reports, and /ti for raw CLI parity."
        )

    bot.run(token)
