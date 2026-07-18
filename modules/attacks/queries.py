"""
modules/attacks/queries.py

Read-only lookups against already-synced attack data.
Does not touch the Torn API - use AttackSync for that.
"""


class AttackQueries:

    def __init__(self, database):
        self.db = database

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
        Flexible attack search with optional combined filters.

        All filters are ANDed together. Returns up to `limit` rows,
        newest first by default (order="DESC"), oldest first with order="ASC".
        """
        conditions = []
        params = []

        if attacker_id is not None:
            conditions.append("attacker_id = ?")
            params.append(attacker_id)

        if attacker_name is not None:
            conditions.append("LOWER(attacker_name) = LOWER(?)")
            params.append(attacker_name)

        if defender_id is not None:
            conditions.append("defender_id = ?")
            params.append(defender_id)

        if defender_name is not None:
            conditions.append("LOWER(defender_name) = LOWER(?)")
            params.append(defender_name)

        if result is not None:
            conditions.append("LOWER(result) = LOWER(?)")
            params.append(result)

        if chain is not None:
            conditions.append("chain = ?")
            params.append(chain)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        sql = f"""
            SELECT
                attack_id,
                timestamp_started,
                attacker_name,
                attacker_faction_name,
                defender_name,
                defender_faction_name,
                result,
                respect_gain,
                respect_loss,
                chain
            FROM attacks
            {where}
            ORDER BY timestamp_started {order}
            LIMIT ?
        """

        return [dict(r) for r in self.db.select(sql, params)]