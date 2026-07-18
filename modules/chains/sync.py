"""
modules/chains/sync.py

Keeps the local chains table up to date.
"""

from core.sync import BaseSync
from core.schema import SchemaBuilder
from models.chain import Chain
from repositories.chain_repository import ChainRepository


class ChainSync(BaseSync):

    name = "Chains"

    def __init__(self, services):

        super().__init__(services)

        self.chains = services.chains

        self.repo = ChainRepository(services.database)

        if not services.database.table_exists(Chain.table_name):

            SchemaBuilder(
                services.database,
                services.logger
            ).create(Chain)

    #######################################################

    def sync(self, mode="backfill", filters=None, **kwargs):

        if mode == "backfill":
            from_ts = kwargs.get("from_timestamp")
            to_ts = kwargs.get("to_timestamp")
            return self._backfill(filters, from_ts, to_ts)
        elif mode == "live":
            return self._live()

        raise ValueError(
            f"Unknown sync mode for chains: '{mode}'"
        )

    #######################################################

    def _backfill(self, filters, from_timestamp=None, to_timestamp=None):
        """
        Sync chains from the API, optionally filtered by timestamp range.
        
        Timestamp filtering is useful for finding all chains that occurred during
        a specific event (like a ranked war). Chains that start or end within the
        range are included.
        
        Args:
            filters: Not used for chains (kept for compatibility with BaseSync)
            from_timestamp: Unix timestamp lower bound (import chains starting after this)
            to_timestamp: Unix timestamp upper bound (import chains starting before this)
        """
        total = 0

        for page in self.chains.iter_pages():

            for chain in page:

                if self.repo.exists(chain.chain_id):
                    # Skip already synced chains
                    continue

                # Apply timestamp filtering if provided
                if from_timestamp is not None:
                    # Skip chains that ended before the start of the range
                    if chain.timestamp_end < from_timestamp:
                        continue
                
                if to_timestamp is not None:
                    # Skip chains that started after the end of the range
                    if chain.timestamp_start > to_timestamp:
                        continue

                self.repo.insert(chain)

                total += 1

        return total

    #######################################################

    def _live(self):
        """
        Sync new chains since last import.
        Finds the latest chain_id in the database and only imports
        chains with higher IDs (newer chains have higher IDs).
        """
        total = 0
        
        # Find the highest chain_id already in database
        latest_db_chain = self.repo.get_latest_chain_id()
        
        for page in self.chains.iter_pages():
            
            for chain in page:
                
                # Only import chains we don't have yet
                if self.repo.exists(chain.chain_id):
                    continue
                
                # Insert new chain
                self.repo.insert(chain)
                total += 1
        
        return total
