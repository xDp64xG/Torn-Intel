"""
Repository for Better Faction Chat reactions.

Torn chat has no native reactions, so the BFC userscript stores them here keyed by
Torn's chat message id and polls them back in small batches.
"""

import re
import time


CHAT_REACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS chat_reactions (
    message_key TEXT NOT NULL,
    emoji TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    user_name TEXT,
    author_id INTEGER,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (message_key, emoji, user_id)
)
"""

CHAT_REACTIONS_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_chat_reactions_created ON chat_reactions (created_at)"

MESSAGE_KEY_RE = re.compile(r"^[A-Za-z0-9:_\-]{1,80}$")
MAX_QUERY_KEYS = 120
MAX_EMOJI_PER_USER = 8
RETENTION_SECONDS = 30 * 86400
PRUNE_EVERY_SECONDS = 3600


def clean_message_key(value):
    key = str(value or "").strip()
    if not MESSAGE_KEY_RE.match(key):
        raise ValueError("invalid_message_key")
    return key


def clean_emoji(value):
    emoji = str(value or "").strip()
    if not emoji or len(emoji) > 16 or not any(ord(ch) > 0x2000 for ch in emoji) or any(ch in "<>&\"'" for ch in emoji):
        raise ValueError("invalid_emoji")
    return emoji


def clean_user_id(value, error="user_id_required"):
    try:
        user_id = int(value)
    except (TypeError, ValueError):
        raise ValueError(error)
    if user_id <= 0:
        raise ValueError(error)
    return user_id


class ChatReactionRepository:

    def __init__(self, database):
        self.db = database
        self.db.create_table(CHAT_REACTIONS_DDL)
        self.db.create_table(CHAT_REACTIONS_INDEX_DDL)
        self._last_prune = 0

    def toggle(self, message_key, emoji, user_id, user_name=None, author_id=None, active=None):
        """Adds or removes one user's emoji on a message. Returns True when the reaction is now present."""
        message_key = clean_message_key(message_key)
        emoji = clean_emoji(emoji)
        user_id = clean_user_id(user_id)
        user_name = str(user_name or "").strip()[:40] or None
        try:
            author_id = int(author_id) if author_id not in (None, "") else None
        except (TypeError, ValueError):
            author_id = None

        existing = self.db.select(
            "SELECT 1 FROM chat_reactions WHERE message_key = ? AND emoji = ? AND user_id = ?",
            (message_key, emoji, user_id),
        )
        want = (not existing) if active is None else bool(active)

        if want and not existing:
            count = self.db.select(
                "SELECT COUNT(*) AS n FROM chat_reactions WHERE message_key = ? AND user_id = ?",
                (message_key, user_id),
            )[0]["n"]
            if count >= MAX_EMOJI_PER_USER:
                raise ValueError("too_many_reactions")
            self.db.execute(
                "INSERT INTO chat_reactions (message_key, emoji, user_id, user_name, author_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (message_key, emoji, user_id, user_name, author_id, int(time.time())),
            )
            self.db.commit()
        elif not want and existing:
            self.db.execute(
                "DELETE FROM chat_reactions WHERE message_key = ? AND emoji = ? AND user_id = ?",
                (message_key, emoji, user_id),
            )
            self.db.commit()

        self._maybe_prune()
        return want

    def for_messages(self, keys):
        """Returns {message_key: [{emoji, count, users: [{id, name}]}]} for the given keys."""
        clean = []
        for key in list(keys or [])[:MAX_QUERY_KEYS]:
            try:
                key = clean_message_key(key)
            except ValueError:
                continue
            if key not in clean:
                clean.append(key)
        if not clean:
            return {}

        placeholders = ",".join("?" for _ in clean)
        rows = self.db.select(
            f"SELECT message_key, emoji, user_id, user_name FROM chat_reactions "
            f"WHERE message_key IN ({placeholders}) ORDER BY created_at, rowid",
            tuple(clean),
        )
        out = {}
        for row in rows:
            groups = out.setdefault(row["message_key"], [])
            group = next((g for g in groups if g["emoji"] == row["emoji"]), None)
            if group is None:
                group = {"emoji": row["emoji"], "count": 0, "users": []}
                groups.append(group)
            group["count"] += 1
            group["users"].append({"id": row["user_id"], "name": row["user_name"]})
        return out

    def _maybe_prune(self):
        now = time.time()
        if now - self._last_prune < PRUNE_EVERY_SECONDS:
            return
        self._last_prune = now
        self.db.execute("DELETE FROM chat_reactions WHERE created_at < ?", (int(now - RETENTION_SECONDS),))
        self.db.commit()
