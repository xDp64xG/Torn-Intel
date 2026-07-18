"""
repositories/chain_repository.py

Repository for Chain model.
"""

from repositories.base_repository import Repository
from models.chain import Chain


class ChainRepository(Repository):

    def __init__(self, database):
        super().__init__(database, Chain)

    ##########################################################

    def exists(self, chain_id: int) -> bool:
        """Check if a chain is already synced"""
        return (
            self.query()
            .where("chain_id", chain_id)
            .first()
            is not None
        )

    ##########################################################

    def by_chain_number(self, chain_number: int):
        """Get chain by chain number (e.g., get the 5000th chain)"""
        return (
            self.query()
            .where("chain_number", chain_number)
            .all()
        )

    ##########################################################

    def chains_in_timestamp_range(self, start_ts: int, end_ts: int):
        """
        Find chains that overlap with a timestamp range.
        Useful for matching attacks to chains.
        """
        sql = """
            SELECT * FROM chains
            WHERE timestamp_start <= ? AND timestamp_end >= ?
            ORDER BY timestamp_start DESC
        """
        return self.db.select(sql, (end_ts, start_ts))

    ##########################################################

    def get_latest_chain_id(self):
        """Get the highest (most recent) chain_id in database"""
        result = self.query().order_by("chain_id", "DESC").first()
        return result["chain_id"] if result else 0

    ##########################################################

    def latest_chain(self):
        """Get the most recently synced chain"""
        rows = self.db.select("""
            SELECT chain_id
            FROM chains
            ORDER BY synced_at DESC
            LIMIT 1
        """)

        if rows:
            return rows[0]["chain_id"]

        return None
