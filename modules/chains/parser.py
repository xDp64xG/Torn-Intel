"""
modules/chains/parser.py

Parse raw chain data from API into Chain objects.
"""

import time
from models.chain import Chain


class ChainParser:

    @staticmethod
    def parse(chain_id: str, data: dict) -> Chain:
        """
        Parse a chain from API response.
        
        Args:
            chain_id: The unique chain ID from the API response
            data: The chain data object from the API
        """
        return Chain(
            chain_id=int(chain_id),
            chain_number=int(data.get("chain", 0)),
            respect=float(data.get("respect", 0)),
            timestamp_start=int(data.get("start", 0)),
            timestamp_end=int(data.get("end", 0)),
            synced_at=int(time.time()),
        )
