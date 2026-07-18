"""
Repository for Revive model.
"""

from repositories.base_repository import Repository
from models.revive import Revive


class ReviveRepository(Repository):

    def __init__(self, database):
        super().__init__(database, Revive)

    ##########################################################

    def exists(self, revive_id: int) -> bool:

        return (
            self.query()
            .where("revive_id", revive_id)
            .first()
            is not None
        )

    ##########################################################

    def latest_revive(self):

        rows = self.db.select(
            """
            SELECT revive_id
            FROM revives
            ORDER BY revive_id DESC
            LIMIT 1
            """
        )

        if rows:
            return rows[0]["revive_id"]

        return None

    ##########################################################

    def latest_timestamp(self):

        rows = self.db.select(
            """
            SELECT timestamp
            FROM revives
            ORDER BY timestamp DESC, revive_id DESC
            LIMIT 1
            """
        )

        if rows:
            return rows[0]["timestamp"]

        return None