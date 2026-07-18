"""
Repository for ReviveRequest model and fulfillment matching.
"""

import json
import time

from repositories.base_repository import Repository
from models.revive import ReviveRequest


class ReviveRequestRepository(Repository):

    def __init__(self, database):
        super().__init__(database, ReviveRequest)
        self._ensure_columns()
        self._ensure_notification_columns()
        self._backfill_revived_timestamps()

    ##########################################################

    def list_requests(self, status=None, target_name=None, limit=50):

        filters = []
        params = []

        if status and status != "all":
            filters.append("status = ?")
            params.append(status)

        if target_name:
            filters.append("LOWER(target_name) LIKE LOWER(?)")
            params.append(f"%{target_name}%")

        where_clause = " AND ".join(filters) if filters else "1=1"

        params.append(int(limit))

        return self.db.select(
            f"""
            SELECT *
            FROM revive_requests
            WHERE {where_clause}
            ORDER BY requested_timestamp DESC, created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )

    ##########################################################

    def delete_requests(self, status="pending", request_id=None, requester_id=None, requester_name=None, target_id=None, target_name=None, source=None):

        filters = []
        params = []

        if status and status != "all":
            filters.append("status = ?")
            params.append(status)

        if request_id:
            filters.append("request_id = ?")
            params.append(str(request_id))

        if requester_id is not None:
            filters.append("requester_id = ?")
            params.append(int(requester_id))

        if requester_name:
            filters.append("LOWER(requester_name) = LOWER(?)")
            params.append(str(requester_name))

        if target_id is not None:
            filters.append("target_id = ?")
            params.append(int(target_id))

        if target_name:
            filters.append("LOWER(target_name) = LOWER(?)")
            params.append(str(target_name))

        if source:
            filters.append("source = ?")
            params.append(str(source))

        where_clause = " AND ".join(filters) if filters else "1=1"

        rows = self.db.select(
            f"""
            SELECT COUNT(*) AS total
            FROM revive_requests
            WHERE {where_clause}
            """,
            tuple(params),
        )
        total = int(rows[0]["total"] or 0) if rows else 0

        self.db.execute(
            f"DELETE FROM revive_requests WHERE {where_clause}",
            tuple(params),
        )
        self.db.commit()
        return total

    ##########################################################

    def queue_notification(self, event_type, request, payload=None):

        self._ensure_notification_columns()

        def read(field, default=None):
            if isinstance(request, dict):
                return request.get(field, default)
            try:
                return request[field]
            except Exception:
                return getattr(request, field, default)

        request_id = str(read("request_id") or "")
        if not request_id:
            return None

        payload_dict = payload if isinstance(payload, dict) else {}
        created_at = int(payload_dict.get("created_at") or time.time())
        self.db.execute(
            """
            INSERT OR IGNORE INTO revive_request_notifications (
                event_type,
                request_id,
                requester_id,
                requester_name,
                target_id,
                target_name,
                source,
                status,
                revived_timestamp,
                fulfilled_by_id,
                fulfilled_by_name,
                notes,
                payload,
                created_at,
                notified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                str(event_type or "event"),
                request_id,
                int(read("requester_id") or 0) if read("requester_id") is not None else None,
                read("requester_name"),
                int(read("target_id") or 0) if read("target_id") is not None else None,
                read("target_name"),
                read("source"),
                read("status"),
                int(read("revived_timestamp") or 0) if read("revived_timestamp") is not None else None,
                int(read("fulfilled_by_id") or 0) if read("fulfilled_by_id") is not None else None,
                read("fulfilled_by_name"),
                read("notes"),
                json.dumps(payload_dict) if payload_dict else None,
                created_at,
            ),
        )
        self.db.commit()
        rows = self.db.select(
            """
            SELECT *
            FROM revive_request_notifications
            WHERE request_id = ? AND event_type = ?
            ORDER BY created_at DESC, notification_id DESC
            LIMIT 1
            """,
            (request_id, str(event_type or "event")),
        )
        return rows[0] if rows else None

    ##########################################################

    def get_notifications(self, requester_id=None, requester_name=None, limit=10):

        filters = ["notified_at IS NULL"]
        params = []

        if requester_id is not None:
            filters.append("requester_id = ?")
            params.append(int(requester_id))
        elif requester_name:
            filters.append("LOWER(requester_name) = LOWER(?)")
            params.append(str(requester_name))

        where_clause = " AND ".join(filters)
        params.append(int(limit))

        return self.db.select(
            f"""
            SELECT *
            FROM revive_request_notifications
            WHERE {where_clause}
            ORDER BY created_at ASC, notification_id ASC
            LIMIT ?
            """,
            tuple(params),
        )

    ##########################################################

    def mark_notifications_notified(self, notification_ids):

        ids = [int(nid) for nid in notification_ids if nid is not None]
        if not ids:
            return 0

        placeholders = ",".join(["?"] * len(ids))
        self.db.execute(
            f"UPDATE revive_request_notifications SET notified_at = ? WHERE notification_id IN ({placeholders})",
            (int(time.time()), *ids),
        )
        self.db.commit()
        return len(ids)

    ##########################################################

    def create_request(self, values):

        existing = self.find_recent_duplicate(
            target_id=values.get("target_id"),
            target_name=values.get("target_name"),
            source=values.get("source"),
            requested_timestamp=values.get("requested_timestamp"),
        )
        if existing:
            return existing["request_id"]

        raw_payload = values.get("raw_payload")
        if raw_payload is not None and not isinstance(raw_payload, str):
            values = dict(values)
            values["raw_payload"] = json.dumps(raw_payload)

        self.db.insert(self.table, values)
        return values.get("request_id")

    ##########################################################

    def get(self, request_id):

        rows = self.db.select(
            "SELECT * FROM revive_requests WHERE request_id = ? LIMIT 1",
            (str(request_id),),
        )
        return rows[0] if rows else None

    ##########################################################

    def get_unnotified_fulfilled(self, requester_id=None, requester_name=None, limit=10):

        filters = ["status = 'fulfilled'", "(notified_at IS NULL OR notified_at = 0)"]
        params = []

        if requester_id is not None:
            filters.append("requester_id = ?")
            params.append(int(requester_id))
        elif requester_name:
            filters.append("LOWER(requester_name) = LOWER(?)")
            params.append(str(requester_name))

        where_clause = " AND ".join(filters)
        params.append(int(limit))

        return self.db.select(
            f"""
            SELECT *
            FROM revive_requests
            WHERE {where_clause}
            ORDER BY matched_at ASC, requested_timestamp ASC
            LIMIT ?
            """,
            tuple(params),
        )

    ##########################################################

    def mark_notified(self, request_ids):

        ids = [str(rid) for rid in request_ids if rid]
        if not ids:
            return 0

        placeholders = ",".join(["?"] * len(ids))
        self.db.execute(
            f"UPDATE revive_requests SET notified_at = ? WHERE request_id IN ({placeholders})",
            (int(time.time()), *ids),
        )
        self.db.commit()
        return len(ids)

    ##########################################################

    def find_recent_duplicate(self, target_id=None, target_name=None, source=None, requested_timestamp=None, window_seconds=120):

        requested_timestamp = int(requested_timestamp or 0)
        lower = requested_timestamp - int(window_seconds)
        upper = requested_timestamp + int(window_seconds)

        if target_id is not None:
            rows = self.db.select(
                """
                SELECT *
                FROM revive_requests
                WHERE target_id = ?
                  AND source = ?
                  AND requested_timestamp BETWEEN ? AND ?
                ORDER BY requested_timestamp DESC, created_at DESC
                LIMIT 1
                """,
                (int(target_id), str(source or "external"), lower, upper),
            )
            if rows:
                return rows[0]

        if target_name:
            rows = self.db.select(
                """
                SELECT *
                FROM revive_requests
                WHERE LOWER(target_name) = LOWER(?)
                  AND source = ?
                  AND requested_timestamp BETWEEN ? AND ?
                ORDER BY requested_timestamp DESC, created_at DESC
                LIMIT 1
                """,
                (str(target_name), str(source or "external"), lower, upper),
            )
            if rows:
                return rows[0]

        return None

    ##########################################################

    def pending_count(self):

        rows = self.db.select(
            """
            SELECT COUNT(*) AS total
            FROM revive_requests
            WHERE status = 'pending'
            """
        )

        return int(rows[0]["total"] or 0) if rows else 0

    ##########################################################

    def match_revive(self, revive, window_seconds=21600):

        if str(getattr(revive, "result", "")).strip().lower() != "success":
            return None

        matched = self._find_matching_request(revive, window_seconds=window_seconds)
        if not matched:
            return None

        return self._fulfill_request(matched["request_id"], revive)

    ##########################################################

    def reconcile_against_database(self, window_seconds=21600, limit=500, return_rows=False):

        pending = self.db.select(
            """
            SELECT *
            FROM revive_requests
            WHERE status = 'pending'
            ORDER BY requested_timestamp DESC, created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        )

        matched = 0
        fulfilled_rows = []

        for request in pending:
            revive = self._find_matching_revive_for_request(request, window_seconds=window_seconds)
            if revive:
                fulfilled = self._fulfill_request(request["request_id"], revive)
                if fulfilled:
                    fulfilled_rows.append(fulfilled)
                matched += 1

        if return_rows:
            return fulfilled_rows

        return matched

    ##########################################################

    def _find_matching_request(self, revive, window_seconds=21600):

        cutoff = int(revive.timestamp or 0) - int(window_seconds)

        if int(getattr(revive, "target_id", 0) or 0) > 0:
            rows = self.db.select(
                """
                SELECT *
                FROM revive_requests
                WHERE status = 'pending'
                  AND target_id = ?
                  AND requested_timestamp <= ?
                  AND requested_timestamp >= ?
                ORDER BY requested_timestamp DESC, created_at DESC
                LIMIT 1
                """,
                (int(revive.target_id), int(revive.timestamp), cutoff),
            )
            if rows:
                return rows[0]

        target_name = str(getattr(revive, "target_name", "") or "").strip()
        if target_name:
            rows = self.db.select(
                """
                SELECT *
                FROM revive_requests
                WHERE status = 'pending'
                  AND LOWER(target_name) = LOWER(?)
                  AND requested_timestamp <= ?
                  AND requested_timestamp >= ?
                ORDER BY requested_timestamp DESC, created_at DESC
                LIMIT 1
                """,
                (target_name, int(revive.timestamp), cutoff),
            )
            if rows:
                return rows[0]

        return None

    ##########################################################

    def _find_matching_revive_for_request(self, request, window_seconds=21600):

        upper = int(request["requested_timestamp"] or 0) + int(window_seconds)

        if int(request["target_id"] or 0) > 0:
            rows = self.db.select(
                """
                SELECT *
                FROM revives
                WHERE LOWER(result) = 'success'
                  AND target_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                                ORDER BY timestamp DESC, revive_id DESC
                LIMIT 1
                """,
                (int(request["target_id"]), int(request["requested_timestamp"]), upper),
            )
            if rows:
                return rows[0]

        target_name = str(request["target_name"] or "").strip()
        if target_name:
            rows = self.db.select(
                """
                SELECT *
                FROM revives
                WHERE LOWER(result) = 'success'
                  AND LOWER(target_name) = LOWER(?)
                  AND timestamp >= ?
                  AND timestamp <= ?
                                ORDER BY timestamp DESC, revive_id DESC
                LIMIT 1
                """,
                (target_name, int(request["requested_timestamp"]), upper),
            )
            if rows:
                return rows[0]

        return None

    ##########################################################

    def _fulfill_request(self, request_id, revive):

        def read(field):
            if isinstance(revive, dict):
                return revive[field]
            try:
                return revive[field]
            except Exception:
                return getattr(revive, field)

        self.db.execute(
            """
            UPDATE revive_requests
            SET status = 'fulfilled',
                fulfilled_revive_id = ?,
                revived_timestamp = ?,
                fulfilled_at = ?,
                fulfilled_by_id = ?,
                fulfilled_by_name = ?,
                matched_at = ?
            WHERE request_id = ?
            """,
            (
                int(read("revive_id") or 0),
                int(read("timestamp") or 0),
                int(read("timestamp") or 0),
                int(read("reviver_id") or 0),
                str(read("reviver_name") or ""),
                int(time.time()),
                str(request_id),
            ),
        )
        self.db.commit()

        return self.get(request_id)

    ##########################################################

    def _ensure_columns(self):

        if not self.db.table_exists(self.table):
            return

        columns = self.db.select(f"PRAGMA table_info({self.table})")
        names = {str(col["name"]).lower() for col in columns}

        if "revived_timestamp" not in names:
            self.db.execute("ALTER TABLE revive_requests ADD COLUMN revived_timestamp INTEGER")
            self.db.commit()

        if "notified_at" not in names:
            self.db.execute("ALTER TABLE revive_requests ADD COLUMN notified_at INTEGER")
            self.db.commit()

    ##########################################################

    def _ensure_notification_columns(self):

        if not self.db.table_exists("revive_request_notifications"):
            self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS revive_request_notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    requester_id INTEGER,
                    requester_name TEXT,
                    target_id INTEGER,
                    target_name TEXT,
                    source TEXT,
                    status TEXT,
                    revived_timestamp INTEGER,
                    fulfilled_by_id INTEGER,
                    fulfilled_by_name TEXT,
                    notes TEXT,
                    payload TEXT,
                    created_at INTEGER NOT NULL,
                    notified_at INTEGER,
                    UNIQUE(request_id, event_type)
                )
                """
            )
            self.db.commit()
            return

        columns = self.db.select("PRAGMA table_info(revive_request_notifications)")
        names = {str(col["name"]).lower() for col in columns}

        if "payload" not in names:
            self.db.execute("ALTER TABLE revive_request_notifications ADD COLUMN payload TEXT")
            self.db.commit()


    ##########################################################

    def _backfill_revived_timestamps(self):

        if not self.db.table_exists(self.table) or not self.db.table_exists("revives"):
            return

        self.db.execute(
            """
            UPDATE revive_requests
            SET revived_timestamp = (
                SELECT r.timestamp
                FROM revives r
                WHERE r.revive_id = revive_requests.fulfilled_revive_id
            )
            WHERE fulfilled_revive_id IS NOT NULL
              AND (revived_timestamp IS NULL OR revived_timestamp = 0)
            """
        )
        self.db.commit()