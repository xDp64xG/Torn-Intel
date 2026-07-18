"""
models/chain.py

Chain model for faction chain data.
"""

from core.model import Model
from core.field import Integer
from core.field import Real


class Chain(Model):
    """Represents a faction chain"""

    table_name = "chains"

    chain_id = Integer(primary=True)
    chain_number = Integer()
    respect = Real()
    timestamp_start = Integer()
    timestamp_end = Integer()
    synced_at = Integer()

    def __init__(self, **kwargs):

        for field in self.column_names():

            setattr(
                self,
                field,
                kwargs.get(field)
            )

    #########################################################

    def to_dict(self):
        """Convert to dictionary for insertion"""
        return {
            "chain_id": self.chain_id,
            "chain_number": self.chain_number,
            "respect": self.respect,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "synced_at": self.synced_at,
        }
