"""
modules/chains/queries.py

Read-only lookups against synced chain data.
"""

from repositories.chain_repository import ChainRepository


class ChainQueries:

    def __init__(self, database):
        self.repo = ChainRepository(database)

    #######################################################

    def by_chain_number(self, chain_number):
        """Get chain data by chain number (e.g., 5000)"""
        return self.repo.by_chain_number(chain_number)

    #######################################################

    def in_timestamp_range(self, start_ts, end_ts):
        """
        Find chains active during a timestamp range.
        Useful for correlating attacks to chains.
        """
        return self.repo.chains_in_timestamp_range(start_ts, end_ts)

    #######################################################

    def by_attack_timestamp(self, attack_timestamp):
        """
        Find the chain that contains an attack by its timestamp.
        Returns the chain if found, None otherwise.
        """
        chains = self.in_timestamp_range(attack_timestamp, attack_timestamp)
        if chains:
            # Return the first (most recent) chain that covers this timestamp
            return chains[0]
        return None

    #######################################################

    def all_chains(self):
        """Get all synced chains"""
        return self.repo.all()
