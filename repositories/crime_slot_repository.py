"""
Repository for OC slot and CPR stats persistence.
"""


class CrimeSlotRepository:

    def __init__(self, database):
        self.db = database

    ##########################################################

    def replace_active_slots(self, slots):
        """
        Replace current active OC slot snapshot with latest API snapshot.
        """
        self.db.execute("DELETE FROM crime_slots")

        if slots:
            sql = """
                INSERT INTO crime_slots (
                    slot_key,
                    crime_id,
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            rows = [
                (
                    slot["slot_key"],
                    slot["crime_id"],
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

    def insert_history_slots(self, slots):
        """
        Append unique slot snapshots for historical player-position search.
        """
        if not slots:
            return

        sql = """
            INSERT OR IGNORE INTO crime_slot_history (
                history_key,
                crime_id,
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        rows = [
            (
                slot.get("history_key") or slot.get("slot_key"),
                slot["crime_id"],
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

    def upsert_cpr_stats(self, rows):

        for row in rows:
            existing = self.db.select(
                "SELECT best_cpr FROM crime_cpr_stats WHERE cpr_key = ?",
                (row["cpr_key"],),
            )

            best = row["cpr"]
            if existing:
                best = max(int(existing[0]["best_cpr"] or 0), int(row["cpr"] or 0))

            self.db.execute(
                """
                INSERT INTO crime_cpr_stats (
                    cpr_key,
                    user_id,
                    user_name,
                    crime_level,
                    position,
                    cpr,
                    best_cpr,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cpr_key) DO UPDATE SET
                    user_name = excluded.user_name,
                    cpr = excluded.cpr,
                    best_cpr = excluded.best_cpr,
                    updated_at = excluded.updated_at
                """,
                (
                    row["cpr_key"],
                    row["user_id"],
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

    def active_slots(self):

        return self.db.select(
            """
            SELECT *
            FROM crime_slots
            ORDER BY crime_id ASC, slot_position ASC, user_name ASC
            """
        )

    ##########################################################

    def cpr_stats(self, min_cpr=None):
        sql = """
            SELECT *
            FROM crime_cpr_stats
        """
        params = []

        if min_cpr is not None:
            sql += " WHERE cpr >= ?"
            params.append(int(min_cpr))

        sql += " ORDER BY crime_level DESC, position ASC, best_cpr DESC, user_name ASC"

        return self.db.select(sql, tuple(params))

    ##########################################################

    def replace_members(self, members):
        """
        Keep roster table aligned with current faction membership.
        Members no longer in faction are removed automatically.
        """
        self.db.execute("DELETE FROM crime_members")

        if members:
            sql = """
                INSERT INTO crime_members (
                    user_id,
                    user_name,
                    position,
                    is_in_oc,
                    last_action,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """
            rows = [
                (
                    int(member["user_id"]),
                    member["user_name"],
                    member.get("position", ""),
                    member.get("is_in_oc"),
                    int(member.get("last_action") or 0),
                    int(member["updated_at"]),
                )
                for member in members
            ]
            self.db.executemany(sql, rows)

        self.db.commit()

    ##########################################################

    def members_outside_crimes(self):
        return self.db.select(
            """
            SELECT
                m.user_id,
                m.user_name,
                m.position,
                m.is_in_oc,
                m.last_action,
                m.updated_at
            FROM crime_members m
            LEFT JOIN (
                SELECT DISTINCT user_id
                FROM crime_slots
            ) s ON s.user_id = m.user_id
            WHERE
                m.is_in_oc = 0
                OR (m.is_in_oc IS NULL AND s.user_id IS NULL)
            ORDER BY m.user_name ASC
            """
        )

    ##########################################################

    def members(self):
        return self.db.select(
            """
            SELECT user_id, user_name, position, is_in_oc, last_action, updated_at
            FROM crime_members
            ORDER BY user_name ASC
            """
        )

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
