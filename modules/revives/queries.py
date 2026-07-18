"""
Read-only revive lookups plus revive request listing.
"""

from repositories.revive_repository import ReviveRepository
from repositories.revive_request_repository import ReviveRequestRepository


class ReviveQueries:

    def __init__(self, database):
        self.db = database
        self.repo = ReviveRepository(database)
        self.request_repo = ReviveRequestRepository(database)

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
        filters = []
        params = []

        if attacker_id is not None:
            filters.append("reviver_id = ?")
            params.append(int(attacker_id))

        if attacker_name:
            filters.append("LOWER(reviver_name) LIKE LOWER(?)")
            params.append(f"%{attacker_name}%")

        if defender_id is not None:
            filters.append("target_id = ?")
            params.append(int(defender_id))

        if defender_name:
            filters.append("LOWER(target_name) LIKE LOWER(?)")
            params.append(f"%{defender_name}%")

        if result:
            filters.append("LOWER(result) LIKE LOWER(?)")
            params.append(f"%{result}%")

        where_clause = " AND ".join(filters) if filters else "1=1"
        params.append(int(limit))

        rows = self.db.select(
            f"""
            SELECT *
            FROM revives
            WHERE {where_clause}
            ORDER BY timestamp {order}, revive_id {order}
            LIMIT ?
            """,
            tuple(params),
        )

        return [dict(r) for r in rows]

    #######################################################

    def revive_requests(self, status="pending", target_name=None, limit=50):
        return [
            dict(r)
            for r in self.request_repo.list_requests(
                status=status,
                target_name=target_name,
                limit=limit,
            )
        ]