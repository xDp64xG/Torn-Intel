"""
models/rankedwar.py

RankedWar model — one row per ranked war.
Stores war metadata: participating factions, their chains, scores, timestamps, winner.
"""

from core.model import Model
from core.field import Integer, Text


class RankedWar(Model):
    """
    Represents a single ranked war between two factions.
    
    Fields:
    - war_id: Torn's internal war ID
    - our_faction_id: The faction we're tracking (typically from TORN_FACTION_ID)
    - our_faction_name: Name of our faction
    - opponent_faction_id: The other faction
    - opponent_faction_name: Name of opponent faction
    - our_score: Score earned by our faction
    - opponent_score: Score earned by opponent faction
    - our_chain: Chain number active for our faction during this war
    - opponent_chain: Chain number active for opponent during this war
    - war_start: Unix timestamp when war started
    - war_end: Unix timestamp when war ended
    - war_target: Target respect for this war (war size)
    - war_winner_id: Faction ID of the winning faction
    - chain_ids: Comma-separated chain IDs linked to this war (auto-detected by timestamp)
    - synced_at: When this record was last synced (unix timestamp)
    """

    table_name = "rankedwars"

    war_id = Integer(primary=True)
    
    our_faction_id = Integer()
    our_faction_name = Text()
    
    opponent_faction_id = Integer()
    opponent_faction_name = Text()
    
    our_score = Integer()
    opponent_score = Integer()
    
    our_chain = Integer()
    opponent_chain = Integer()
    
    war_start = Integer()
    war_end = Integer()
    war_target = Integer()
    war_winner_id = Integer()
    
    chain_ids = Text()
    
    synced_at = Integer()

    def __init__(self, **kwargs):
        for field in self.column_names():
            setattr(self, field, kwargs.get(field))
