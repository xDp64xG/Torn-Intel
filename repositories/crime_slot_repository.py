"""
Repository for OC slot and CPR stats persistence.
"""

import time


class CrimeSlotRepository:

    FLYING_STATES = {"traveling", "abroad"}
    HOSPITAL_STATES = {"hospital"}
    ABROAD_COUNTRIES = (
        "mexico", "cayman", "canada", "hawaii", "united kingdom", "uk",
        "argentina", "switzerland", "japan", "china", "uae", "south africa"
    )

    def __init__(self, database):
        self.db = database

    ##########################################################

    def replace_active_slots(self, slots, faction_tag=None, faction_id=None):
        """
        Replace current active OC slot snapshot with latest API snapshot.
        If faction_tag/faction_id is provided, only replaces that faction's slots.
        """
        if faction_tag:
            self.db.execute("DELETE FROM crime_slots WHERE faction_tag = ? OR faction_tag IS NULL", (faction_tag,))
        elif faction_id:
            self.db.execute("DELETE FROM crime_slots WHERE faction_id = ? OR faction_id IS NULL", (int(faction_id),))
        else:
            self.db.execute("DELETE FROM crime_slots")

        if slots:
            sql = """
                INSERT OR REPLACE INTO crime_slots (
                    slot_key,
                    crime_id,
                    faction_id,
                    faction_tag,
                    crime_name,
                    status,
                    difficulty,
                    slot_position,
                    user_id,
                    user_name,
                    checkpoint_pass_rate,
                    required_item_id,
                    required_item_name,
                    item_is_available,
                    item_is_reusable,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            rows = [
                (
                    slot["slot_key"],
                    slot["crime_id"],
                    slot.get("faction_id") or faction_id,
                    slot.get("faction_tag") or faction_tag,
                    slot["crime_name"],
                    slot["status"],
                    slot["difficulty"],
                    slot["slot_position"],
                    slot["user_id"],
                    slot["user_name"],
                    slot["checkpoint_pass_rate"],
                    slot["required_item_id"],
                    slot["required_item_name"],
                    slot["item_is_available"],
                    slot["item_is_reusable"],
                    slot["updated_at"],
                )
                for slot in slots
            ]
            self.db.executemany(sql, rows)

        self.db.commit()

    ##########################################################

    def insert_history_slots(self, slots, faction_tag=None, faction_id=None):
        """
        Append unique slot snapshots for historical player-position search.
        """
        if not slots:
            return

        sql = """
            INSERT OR IGNORE INTO crime_slot_history (
                history_key,
                crime_id,
                faction_id,
                faction_tag,
                crime_name,
                status,
                difficulty,
                slot_position,
                user_id,
                user_name,
                checkpoint_pass_rate,
                required_item_id,
                required_item_name,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        rows = [
            (
                slot.get("history_key") or slot.get("slot_key"),
                slot["crime_id"],
                slot.get("faction_id") or faction_id,
                slot.get("faction_tag") or faction_tag,
                slot["crime_name"],
                slot["status"],
                slot["difficulty"],
                slot["slot_position"],
                slot["user_id"],
                slot["user_name"],
                slot["checkpoint_pass_rate"],
                slot.get("required_item_id", 0),
                slot.get("required_item_name", "-"),
                slot["updated_at"],
            )
            for slot in slots
        ]

        self.db.executemany(sql, rows)
        self.db.commit()

    ##########################################################

    def upsert_cpr_stats(self, rows, faction_tag=None, faction_id=None):

        for row in rows:
            existing = self.db.select(
                "SELECT best_cpr FROM crime_cpr_stats WHERE cpr_key = ?",
                (row["cpr_key"],),
            )

            best = row["cpr"]
            if existing:
                best = max(int(existing[0]["best_cpr"] or 0), int(row["cpr"] or 0))

            f_id = row.get("faction_id") or faction_id
            f_tag = row.get("faction_tag") or faction_tag

            self.db.execute(
                """
                INSERT INTO crime_cpr_stats (
                    cpr_key,
                    user_id,
                    faction_id,
                    faction_tag,
                    user_name,
                    crime_level,
                    position,
                    cpr,
                    best_cpr,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cpr_key) DO UPDATE SET
                    user_name = excluded.user_name,
                    faction_id = COALESCE(excluded.faction_id, crime_cpr_stats.faction_id),
                    faction_tag = COALESCE(excluded.faction_tag, crime_cpr_stats.faction_tag),
                    cpr = excluded.cpr,
                    best_cpr = excluded.best_cpr,
                    updated_at = excluded.updated_at
                """,
                (
                    row["cpr_key"],
                    row["user_id"],
                    f_id,
                    f_tag,
                    row["user_name"],
                    row["crime_level"],
                    row["position"],
                    row["cpr"],
                    best,
                    row["updated_at"],
                ),
            )

        self.db.commit()

    ##########################################################

    def active_slots(self, faction_tag=None, faction_id=None):
        if faction_tag:
            return self.db.select(
                """
                SELECT *
                FROM crime_slots
                WHERE faction_tag = ?
                ORDER BY crime_id ASC, slot_position ASC, user_name ASC
                """,
                (faction_tag,),
            )
        if faction_id:
            return self.db.select(
                """
                SELECT *
                FROM crime_slots
                WHERE faction_id = ?
                ORDER BY crime_id ASC, slot_position ASC, user_name ASC
                """,
                (int(faction_id),),
            )
        return self.db.select(
            """
            SELECT *
            FROM crime_slots
            ORDER BY crime_id ASC, slot_position ASC, user_name ASC
            """
        )

    ##########################################################

    def cpr_stats(self, min_cpr=None, faction_tag=None, faction_id=None):
        sql = "SELECT * FROM crime_cpr_stats WHERE 1=1"
        params = []

        if min_cpr is not None:
            sql += " AND cpr >= ?"
            params.append(int(min_cpr))

        if faction_tag:
            sql += " AND faction_tag = ?"
            params.append(faction_tag)
        elif faction_id:
            sql += " AND faction_id = ?"
            params.append(int(faction_id))

        sql += " ORDER BY crime_level DESC, position ASC, best_cpr DESC, user_name ASC"

        return self.db.select(sql, tuple(params))

    ##########################################################

    def replace_members(self, members, faction_tag=None, faction_id=None):
        """
        Keep roster table aligned with current faction membership.
        """
        if faction_tag:
            self.db.execute("DELETE FROM crime_members WHERE faction_tag = ? OR faction_tag IS NULL", (faction_tag,))
        elif faction_id:
            self.db.execute("DELETE FROM crime_members WHERE faction_id = ? OR faction_id IS NULL", (int(faction_id),))
        else:
            self.db.execute("DELETE FROM crime_members")

        if members:
            sql = """
                INSERT OR REPLACE INTO crime_members (
                    user_id,
                    faction_id,
                    faction_tag,
                    user_name,
                    position,
                    is_in_oc,
                    status_state,
                    status_description,
                    last_action,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            rows = [
                (
                    int(member["user_id"]),
                    member.get("faction_id") or faction_id,
                    member.get("faction_tag") or faction_tag,
                    member["user_name"],
                    member.get("position", ""),
                    member.get("is_in_oc"),
                    member.get("status_state", ""),
                    member.get("status_description", ""),
                    int(member.get("last_action") or 0),
                    int(member["updated_at"]),
                )
                for member in members
            ]
            self.db.executemany(sql, rows)

        self.db.commit()

    ##########################################################

    def members_outside_crimes(self, faction_tag=None, faction_id=None):
        sql = """
            SELECT
                m.user_id,
                m.faction_id,
                m.faction_tag,
                m.user_name,
                m.position,
                m.is_in_oc,
                m.last_action,
                m.updated_at
            FROM crime_members m
            LEFT JOIN (
                SELECT DISTINCT user_id, faction_tag
                FROM crime_slots
            ) s ON s.user_id = m.user_id AND (s.faction_tag = m.faction_tag OR m.faction_tag IS NULL)
            WHERE
                (m.is_in_oc = 0
                OR (m.is_in_oc IS NULL AND s.user_id IS NULL))
        """
        params = []
        if faction_tag:
            sql += " AND m.faction_tag = ?"
            params.append(faction_tag)
        elif faction_id:
            sql += " AND m.faction_id = ?"
            params.append(int(faction_id))

        sql += " ORDER BY m.user_name ASC"
        return self.db.select(sql, tuple(params))

    ##########################################################

    def members(self, faction_tag=None, faction_id=None):
        if faction_tag:
            return self.db.select(
                """
                SELECT user_id, faction_id, faction_tag, user_name, position, is_in_oc, status_state, status_description, last_action, updated_at
                FROM crime_members
                WHERE faction_tag = ?
                ORDER BY user_name ASC
                """,
                (faction_tag,),
            )
        if faction_id:
            return self.db.select(
                """
                SELECT user_id, faction_id, faction_tag, user_name, position, is_in_oc, status_state, status_description, last_action, updated_at
                FROM crime_members
                WHERE faction_id = ?
                ORDER BY user_name ASC
                """,
                (int(faction_id),),
            )
        return self.db.select(
            """
            SELECT user_id, faction_id, faction_tag, user_name, position, is_in_oc, status_state, status_description, last_action, updated_at
            FROM crime_members
            ORDER BY user_name ASC
            """
        )

    ##########################################################

    def active_delay_events(self, limit=50, faction_tag=None):
        if faction_tag:
            return self.db.select(
                """
                SELECT *
                FROM crime_delay_events
                WHERE resolved_at IS NULL AND faction_tag = ?
                ORDER BY started_at ASC, crime_id ASC
                LIMIT ?
                """,
                (faction_tag, int(limit)),
            )
        return self.db.select(
            """
            SELECT *
            FROM crime_delay_events
            WHERE resolved_at IS NULL
            ORDER BY started_at ASC, crime_id ASC
            LIMIT ?
            """,
            (int(limit),),
        )

    ##########################################################

    def resolved_delay_events(self, limit=50, faction_tag=None):
        if faction_tag:
            return self.db.select(
                """
                SELECT *
                FROM crime_delay_events
                WHERE resolved_at IS NOT NULL AND faction_tag = ?
                ORDER BY resolved_at DESC, started_at DESC, crime_id DESC
                LIMIT ?
                """,
                (faction_tag, int(limit)),
            )
        return self.db.select(
            """
            SELECT *
            FROM crime_delay_events
            WHERE resolved_at IS NOT NULL
            ORDER BY resolved_at DESC, started_at DESC, crime_id DESC
            LIMIT ?
            """,
            (int(limit),),
        )

    ##########################################################

    def list_unposted_delay_notifications(self, limit=50, faction_tag=None):
        if faction_tag:
            return self.db.select(
                """
                SELECT *
                FROM crime_delay_notifications
                WHERE COALESCE(discord_posted_at, 0) = 0 AND faction_tag = ?
                ORDER BY created_at ASC, notification_id ASC
                LIMIT ?
                """,
                (faction_tag, int(limit)),
            )
        return self.db.select(
            """
            SELECT *
            FROM crime_delay_notifications
            WHERE COALESCE(discord_posted_at, 0) = 0
            ORDER BY created_at ASC, notification_id ASC
            LIMIT ?
            """,
            (int(limit),),
        )

    ##########################################################

    def mark_delay_notification_discord_posted(self, notification_id):
        self.db.execute(
            """
            UPDATE crime_delay_notifications
            SET discord_posted_at = ?
            WHERE notification_id = ?
            """,
            (int(time.time()), int(notification_id)),
        )
        self.db.commit()

    ##########################################################

    def track_flying_delays(self, slots, members, crime_status_rows=None, observed_at=None, faction_id=None, faction_tag=None):
        observed_at = int(observed_at or time.time())
        crime_status_rows = crime_status_rows or []

        # If members list or crime status list is empty, snapshot is invalid or partial.
        # Avoid resolving active delays or creating spurious new ones.
        if not members or not crime_status_rows:
            return {
                "active": len(self.active_delay_events(limit=500, faction_tag=faction_tag)),
                "started": 0,
                "resolved": 0,
            }

        members_by_id = {
            int(member.get("user_id") or 0): dict(member)
            for member in (members or [])
            if int(member.get("user_id") or 0) > 0
        }

        crime_meta_by_id = {
            int(row.get("crime_id") or 0): dict(row)
            for row in crime_status_rows
            if int(row.get("crime_id") or 0) > 0
        }

        delayed_crimes = {}
        for slot in slots or []:
            crime_id = int(slot.get("crime_id") or 0)
            if crime_id <= 0:
                continue

            crime_meta = crime_meta_by_id.get(crime_id, {})
            delay_start_at = self._eligible_delay_start_at(crime_meta, observed_at)
            if delay_start_at is None:
                continue

            user_id = int(slot.get("user_id") or 0)
            member = members_by_id.get(user_id)
            if not self._member_blocks_crime(member):
                continue

            f_id = slot.get("faction_id") or faction_id
            f_tag = slot.get("faction_tag") or faction_tag

            entry = delayed_crimes.setdefault(
                crime_id,
                {
                    "crime_id": crime_id,
                    "faction_id": f_id,
                    "faction_tag": f_tag,
                    "crime_name": slot.get("crime_name") or "Unknown",
                    "difficulty": int(slot.get("difficulty") or 0),
                    "status": slot.get("status") or "planning",
                    "delay_start_at": delay_start_at,
                    "delaying_members": [],
                },
            )
            entry["delaying_members"].append(member)

        if faction_tag:
            open_rows = self.db.select(
                """
                SELECT *
                FROM crime_delay_events
                WHERE resolved_at IS NULL AND faction_tag = ?
                ORDER BY delay_id ASC
                """,
                (faction_tag,),
            )
        elif faction_id:
            open_rows = self.db.select(
                """
                SELECT *
                FROM crime_delay_events
                WHERE resolved_at IS NULL AND faction_id = ?
                ORDER BY delay_id ASC
                """,
                (int(faction_id),),
            )
        else:
            open_rows = self.db.select(
                """
                SELECT *
                FROM crime_delay_events
                WHERE resolved_at IS NULL
                ORDER BY delay_id ASC
                """
            )

        open_by_crime = {int(row["crime_id"] or 0): dict(row) for row in open_rows}
        status_by_crime = {
            int(row.get("crime_id") or 0): str(row.get("status") or "").strip().lower()
            for row in crime_status_rows
            if int(row.get("crime_id") or 0) > 0
        }

        started = 0
        resolved = 0

        for crime_id, entry in delayed_crimes.items():
            delaying_members = entry["delaying_members"]
            delaying_user_ids = self._join_unique_text(str(int(member.get("user_id") or 0)) for member in delaying_members)
            delaying_user_names = self._join_unique_text(member.get("user_name") or "Unknown" for member in delaying_members)
            delaying_states = self._join_unique_text(
                member.get("status_description") or member.get("status_state") or "Traveling"
                for member in delaying_members
            )

            existing = open_by_crime.get(crime_id)
            if existing:
                duration_seconds = max(0, observed_at - int(existing.get("started_at") or observed_at))
                self.db.execute(
                    """
                    UPDATE crime_delay_events
                    SET crime_name = ?,
                        difficulty = ?,
                        status = ?,
                        last_seen_at = ?,
                        duration_seconds = ?,
                        delaying_user_ids = ?,
                        delaying_user_names = ?,
                        delaying_states = ?
                    WHERE delay_id = ?
                    """,
                    (
                        entry["crime_name"],
                        entry["difficulty"],
                        entry["status"],
                        observed_at,
                        duration_seconds,
                        delaying_user_ids,
                        delaying_user_names,
                        delaying_states,
                        int(existing["delay_id"]),
                    ),
                )
                continue

            cursor = self.db.execute(
                """
                INSERT INTO crime_delay_events (
                    crime_id,
                    faction_id,
                    faction_tag,
                    crime_name,
                    difficulty,
                    status,
                    started_at,
                    last_seen_at,
                    resolved_at,
                    duration_seconds,
                    resolution,
                    delaying_user_ids,
                    delaying_user_names,
                    delaying_states
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?, ?, ?)
                """,
                (
                    entry["crime_id"],
                    entry.get("faction_id") or faction_id,
                    entry.get("faction_tag") or faction_tag,
                    entry["crime_name"],
                    entry["difficulty"],
                    entry["status"],
                    int(entry["delay_start_at"]),
                    observed_at,
                    delaying_user_ids,
                    delaying_user_names,
                    delaying_states,
                ),
            )
            delay_id = int(cursor.lastrowid)
            starting_duration = max(0, observed_at - int(entry["delay_start_at"]))
            if starting_duration > 0:
                self.db.execute(
                    "UPDATE crime_delay_events SET duration_seconds = ? WHERE delay_id = ?",
                    (starting_duration, delay_id),
                )
            self._insert_delay_notification(
                event_type="crime_delay_started",
                delay_id=delay_id,
                crime_id=entry["crime_id"],
                faction_id=entry.get("faction_id") or faction_id,
                faction_tag=entry.get("faction_tag") or faction_tag,
                crime_name=entry["crime_name"],
                difficulty=entry["difficulty"],
                started_at=int(entry["delay_start_at"]),
                resolved_at=None,
                duration_seconds=starting_duration,
                delaying_user_ids=delaying_user_ids,
                delaying_user_names=delaying_user_names,
                delaying_states=delaying_states,
                resolution=None,
                created_at=observed_at,
            )
            started += 1

        for crime_id, existing in open_by_crime.items():
            if crime_id in delayed_crimes:
                continue

            crime_status = status_by_crime.get(crime_id)

            # If the crime is still in planning, verify that we actually have slot and member data
            # in the snapshot before concluding that the flying delay cleared.
            if crime_status == "planning":
                assigned_slots = [
                    s for s in (slots or [])
                    if int(s.get("crime_id") or 0) == crime_id and int(s.get("user_id") or 0) > 0
                ]
                # If we don't have slots for this crime in the snapshot, keep the delay open
                if not assigned_slots:
                    continue
                # If any assigned member is missing from the roster snapshot, keep the delay open
                if any(int(s.get("user_id") or 0) not in members_by_id for s in assigned_slots):
                    continue

            resolved_at = observed_at
            duration_seconds = max(0, resolved_at - int(existing.get("started_at") or resolved_at))
            resolution = self._resolve_delay_resolution(crime_status)

            self.db.execute(
                """
                UPDATE crime_delay_events
                SET last_seen_at = ?,
                    resolved_at = ?,
                    duration_seconds = ?,
                    resolution = ?
                WHERE delay_id = ?
                """,
                (
                    resolved_at,
                    resolved_at,
                    duration_seconds,
                    resolution,
                    int(existing["delay_id"]),
                ),
            )
            self._insert_delay_notification(
                event_type="crime_delay_resolved",
                delay_id=int(existing["delay_id"]),
                crime_id=int(existing.get("crime_id") or 0),
                faction_id=existing.get("faction_id") or faction_id,
                faction_tag=existing.get("faction_tag") or faction_tag,
                crime_name=existing.get("crime_name") or "Unknown",
                difficulty=int(existing.get("difficulty") or 0),
                started_at=int(existing.get("started_at") or 0),
                resolved_at=resolved_at,
                duration_seconds=duration_seconds,
                delaying_user_ids=existing.get("delaying_user_ids") or "",
                delaying_user_names=existing.get("delaying_user_names") or "",
                delaying_states=existing.get("delaying_states") or "",
                resolution=resolution,
                created_at=resolved_at,
            )
            resolved += 1

        self.db.commit()
        return {
            "active": len(delayed_crimes),
            "started": started,
            "resolved": resolved,
        }

    ##########################################################

    def _insert_delay_notification(
        self,
        *,
        event_type,
        delay_id,
        crime_id,
        faction_id=None,
        faction_tag=None,
        crime_name,
        difficulty,
        started_at,
        resolved_at,
        duration_seconds,
        delaying_user_ids,
        delaying_user_names,
        delaying_states,
        resolution,
        created_at,
    ):
        self.db.execute(
            """
            INSERT INTO crime_delay_notifications (
                event_type,
                delay_id,
                crime_id,
                faction_id,
                faction_tag,
                crime_name,
                difficulty,
                started_at,
                resolved_at,
                duration_seconds,
                delaying_user_ids,
                delaying_user_names,
                delaying_states,
                resolution,
                created_at,
                discord_posted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                str(event_type),
                int(delay_id),
                int(crime_id),
                int(faction_id) if faction_id else None,
                str(faction_tag) if faction_tag else None,
                str(crime_name or "Unknown"),
                int(difficulty or 0),
                int(started_at or 0),
                int(resolved_at) if resolved_at is not None else None,
                int(duration_seconds or 0),
                str(delaying_user_ids or ""),
                str(delaying_user_names or ""),
                str(delaying_states or ""),
                str(resolution) if resolution else None,
                int(created_at or 0),
            ),
        )

    ##########################################################

    def _member_is_flying(self, member):
        if not member:
            return False
        state = str(member.get("status_state") or "").strip().lower()
        if state in self.FLYING_STATES:
            return True
        desc = str(member.get("status_description") or "").strip().lower()
        if "traveling" in desc or "abroad" in desc:
            return True
        if any(country in desc for country in self.ABROAD_COUNTRIES):
            return True
        return False

    ##########################################################

    def _member_is_hospitalized(self, member):
        if not member:
            return False
        state = str(member.get("status_state") or "").strip().lower()
        if state in self.HOSPITAL_STATES:
            return True
        desc = str(member.get("status_description") or "").strip().lower()
        return "hospital" in desc

    def _member_blocks_crime(self, member):
        return self._member_is_flying(member) or self._member_is_hospitalized(member)

    ##########################################################

    def _eligible_delay_start_at(self, crime_meta, observed_at):
        status = str((crime_meta or {}).get("status") or "").strip().lower()
        if status != "planning":
            return None

        ready_at = crime_meta.get("ready_at")
        if ready_at is None:
            return None

        ready_at = int(ready_at or 0)
        if ready_at <= 0:
            return None

        if int(observed_at or 0) < ready_at:
            return None

        return ready_at

    ##########################################################

    def _resolve_delay_resolution(self, status):
        normalized = str(status or "").strip().lower()
        if normalized == "completed":
            return "completed"
        if normalized in {"planning", "recruiting", "available"}:
            return "cleared"
        if normalized:
            return normalized
        return "inactive"

    ##########################################################

    def _join_unique_text(self, values):
        seen = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.append(text)
        return ", ".join(seen)

    ##########################################################

    def player_history(self, player_name, limit=100):
        return self.db.select(
            """
            SELECT
                h.*,
                COALESCE(
                    (
                        SELECT MAX(s.best_cpr)
                        FROM crime_cpr_stats s
                        WHERE s.user_id = h.user_id
                          AND s.crime_level = h.difficulty
                          AND LOWER(s.position) = LOWER(h.slot_position)
                    ),
                    h.checkpoint_pass_rate
                ) AS best_cpr
            FROM crime_slot_history h
            WHERE LOWER(h.user_name) LIKE LOWER(?)
            ORDER BY h.updated_at DESC, h.crime_id DESC
            LIMIT ?
            """,
            (f"%{player_name}%", int(limit)),
        )
