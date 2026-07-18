"""
modules/crimes/queries.py

Read-only lookups against synced OC slots and CPR stats.
"""

from repositories.crime_slot_repository import CrimeSlotRepository


class CrimeQueries:

    def __init__(self, database):
        self.repo = CrimeSlotRepository(database)
        self.db = database

    #######################################################

    def active_slots(self):
        return [dict(r) for r in self.repo.active_slots()]

    #######################################################

    def search(
        self,
        attacker_id=None,
        attacker_name=None,
        defender_id=None,
        defender_name=None,
        result=None,
        chain=None,
        limit=25,
        order="DESC",
    ):
        """
        Compatibility shim for engine.search().
        Returns active slots filtered by player name or item text when possible.
        When filtering by player, also includes historical positions inferred
        from CPR history.
        """
        slots = self.active_slots()

        filtered = slots
        if attacker_name:
            name = str(attacker_name).lower()
            filtered = [s for s in filtered if name in str(s.get("user_name", "")).lower()]

        if result:
            text = str(result).lower()
            filtered = [
                s
                for s in filtered
                if text in str(s.get("required_item_name", "")).lower()
                or text in str(s.get("crime_name", "")).lower()
            ]

        # Include previous known positions for a player from CPR history.
        if attacker_name:
            historical = self._historical_positions_for_player(attacker_name, limit=max(int(limit), 25))
            active_keys = {
                (
                    int(row.get("user_id") or 0),
                    int(row.get("difficulty") or 0),
                    str(row.get("slot_position") or "").strip().lower(),
                )
                for row in filtered
            }

            for row in historical:
                key = (
                    int(row.get("user_id") or 0),
                    int(row.get("difficulty") or 0),
                    str(row.get("slot_position") or "").strip().lower(),
                )
                if key in active_keys:
                    continue
                filtered.append(row)

        reverse = str(order).upper() == "DESC"
        filtered = sorted(filtered, key=lambda s: int(s.get("updated_at", 0)), reverse=reverse)
        return filtered[: int(limit)]

    #######################################################

    def cpr_stats(self, min_cpr=None):
        return [dict(r) for r in self.repo.cpr_stats(min_cpr=min_cpr)]

    #######################################################

    def outstanding_loans(self):
        """
        Outstanding qty per player/item from armoury loaned/received history.
        """
        rows = self.db.select(
            """
            WITH agg AS (
                SELECT
                    player_id,
                    player_name,
                    item_id,
                    item_name,
                    SUM(CASE WHEN event_type = 'loaned' THEN quantity ELSE 0 END) AS loaned_qty,
                    SUM(CASE WHEN event_type = 'received' THEN quantity ELSE 0 END) AS received_qty
                FROM armoury_news
                WHERE item_id IS NOT NULL AND item_id > 0
                  AND event_type IN ('loaned', 'received')
                GROUP BY player_id, player_name, item_id, item_name
            )
            SELECT
                player_id,
                player_name,
                item_id,
                item_name,
                (loaned_qty - received_qty) AS quantity_out
            FROM agg
            WHERE (loaned_qty - received_qty) > 0
            ORDER BY quantity_out DESC, player_name ASC
            """
        )
        return [dict(r) for r in rows]

    #######################################################

    def members_outside_crimes(self):
        return [dict(r) for r in self.repo.members_outside_crimes()]

    #######################################################

    def members(self):
        return [dict(r) for r in self.repo.members()]

    #######################################################

    def faction_item_stock(self, item_ids=None):
        """
        Estimated current on-hand faction armoury stock by item_id.
        Formula: deposited + received - loaned - used.
        """
        if item_ids:
            cleaned = sorted({int(i) for i in item_ids if int(i) > 0})
            if not cleaned:
                return {}
            placeholders = ",".join(["?"] * len(cleaned))
            rows = self.db.select(
                f"""
                SELECT
                    item_id,
                    SUM(CASE WHEN event_type IN ('deposited', 'received') THEN quantity ELSE 0 END)
                    -
                    SUM(CASE WHEN event_type IN ('loaned', 'used') THEN quantity ELSE 0 END) AS qty_in_armoury
                FROM armoury_news
                WHERE item_id IN ({placeholders})
                GROUP BY item_id
                """,
                tuple(cleaned),
            )
        else:
            rows = self.db.select(
                """
                SELECT
                    item_id,
                    SUM(CASE WHEN event_type IN ('deposited', 'received') THEN quantity ELSE 0 END)
                    -
                    SUM(CASE WHEN event_type IN ('loaned', 'used') THEN quantity ELSE 0 END) AS qty_in_armoury
                FROM armoury_news
                WHERE item_id IS NOT NULL AND item_id > 0
                GROUP BY item_id
                """
            )

        stock = {}
        for row in rows:
            item_id = int(row["item_id"] or 0)
            qty = int(row["qty_in_armoury"] or 0)
            stock[item_id] = max(0, qty)

        return stock

    #######################################################

    def armoury_item_ids_by_name(self, item_names):
        """
        Resolve known armoury item IDs grouped by lower-cased item name.
        """
        names = sorted({str(name).strip().lower() for name in (item_names or []) if str(name).strip()})
        if not names:
            return {}

        placeholders = ",".join(["?"] * len(names))
        rows = self.db.select(
            f"""
            SELECT LOWER(item_name) AS name_key, item_id
            FROM armoury_news
            WHERE LOWER(item_name) IN ({placeholders})
              AND item_id IS NOT NULL
              AND item_id > 0
            GROUP BY LOWER(item_name), item_id
            """,
            tuple(names),
        )

        result = {name: set() for name in names}
        for row in rows:
            name_key = str(row["name_key"])
            item_id = int(row["item_id"] or 0)
            if item_id > 0:
                result.setdefault(name_key, set()).add(item_id)

        return result

    #######################################################

    def faction_item_deposited_totals(self, item_ids=None):
        """
        Total deposited quantity seen in armoury history by item_id.
        """
        if item_ids:
            cleaned = sorted({int(i) for i in item_ids if int(i) > 0})
            if not cleaned:
                return {}
            placeholders = ",".join(["?"] * len(cleaned))
            rows = self.db.select(
                f"""
                SELECT item_id, SUM(quantity) AS deposited_qty
                FROM armoury_news
                WHERE event_type = 'deposited'
                  AND item_id IN ({placeholders})
                GROUP BY item_id
                """,
                tuple(cleaned),
            )
        else:
            rows = self.db.select(
                """
                SELECT item_id, SUM(quantity) AS deposited_qty
                FROM armoury_news
                WHERE event_type = 'deposited'
                  AND item_id IS NOT NULL
                  AND item_id > 0
                GROUP BY item_id
                """
            )

        return {
            int(row["item_id"] or 0): int(row["deposited_qty"] or 0)
            for row in rows
            if int(row["item_id"] or 0) > 0
        }

    #######################################################

    def _historical_positions_for_player(self, player_name, limit=50):
        rows = self.repo.player_history(player_name=player_name, limit=limit)

        result = []
        for row in rows:
            result.append(
                {
                    "slot_key": f"history:{row['history_key']}",
                    "crime_id": int(row["crime_id"] or 0),
                    "crime_name": row["crime_name"] or "Unknown Crime",
                    "status": row["status"] or "completed",
                    "difficulty": int(row["difficulty"] or 0),
                    "slot_position": row["slot_position"],
                    "user_id": int(row["user_id"] or 0),
                    "user_name": row["user_name"],
                    "checkpoint_pass_rate": int(row["checkpoint_pass_rate"] or 0),
                    "required_item_id": int(row["required_item_id"] or 0),
                    "required_item_name": row["required_item_name"] or "-",
                    "item_is_available": 0,
                    "item_is_reusable": 0,
                    "best_cpr": int(row["best_cpr"] or 0),
                    "updated_at": int(row["updated_at"] or 0),
                    "is_historical": 1,
                }
            )

        return result
