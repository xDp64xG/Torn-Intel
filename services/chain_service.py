"""
services/chain_service.py

Turns raw Torn chain data into parsed Chain objects.
"""

from modules.chains.parser import ChainParser


class ChainService:

    def __init__(self, gateway, logger):
        self.gateway = gateway
        self.logger = logger

    #######################################################

    def iter_pages(self):
        """
        Yield parsed chains from the API.
        Chains endpoint returns all chains in one response,
        but we follow the pattern for consistency.
        """
        response = self.gateway.faction_chains()

        chains = self._parse_all(response)

        if chains:
            yield chains

    #######################################################

    def _parse_all(self, response):
        """Parse all chains from API response"""
        raw_chains = response.get("chains", {})

        return [
            ChainParser.parse(chain_id, chain)
            for chain_id, chain in raw_chains.items()
        ]
