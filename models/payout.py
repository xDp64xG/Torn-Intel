"""
models/payout.py

Payout model — stores calculated war payouts for audit trail.
One row per player per war, with detailed payout breakdown.
"""

from core.model import Model
from core.field import Integer, Real, Text


class Payout(Model):
    """
    Represents a calculated payout for a player in a war.
    
    Fields:
    - id: Auto-increment primary key
    - war_id: The ranked war ID
    - player_id: Player's Torn ID
    - player_name: Player's name
    - war_hits: Number of hits marked as is_ranked_war=1
    - war_respect: Respect from war hits only
    - assist_count: Number of assists (hits on opposing faction)
    - num_bonus_hits: Number of hits at bonus milestones (10, 25, 50, 100, 250, 500, 1000, etc.)
    - assist_payout: Total payout from assists
    - outside_hits: Hits not marked as war hits
    - outside_respect: Respect from outside hits
    - outside_payout: Payout from outside hits (if enabled)
    - total_respect: Total respect earned
    - regular_respect: Respect from normal attacks (not bonuses)
    - chain_bonus_respect: Respect from chain bonuses (capped at avg/hit)
    - avg_respect_per_hit: Player's average respect per hit
    - num_hits: Total number of hits in this war
    - num_chains_participated: How many different chains they hit
    - total_payout_pool: The total payout amount (parameter)
    - xanax_cost: Xanax cost (parameter)
    - bounty_cost: Bounty cost (parameter)
    - faction_cut_pct: Faction cut percentage (parameter)
    - respect_percentage: Their share of total respect (%)
    - payout_after_costs: (total - xanax - bounty) * (1 - faction_cut_pct)
    - player_share: Their calculated payout amount
    - assist_pay_per: $/assist parameter used
    - pay_outside_hits: Whether outside hits were paid (0=no, 1=yes)
    - calculated_at: Unix timestamp when calculated
    """

    table_name = "payouts"

    id = Integer(primary=True)
    
    war_id = Integer()
    player_id = Integer()
    player_name = Text()
    
    war_hits = Integer()
    war_respect = Real()
    assist_count = Integer()
    num_bonus_hits = Integer()
    assist_payout = Real()
    outside_hits = Integer()
    outside_respect = Real()
    outside_payout = Real()
    
    total_respect = Real()
    regular_respect = Real()
    chain_bonus_respect = Real()
    avg_respect_per_hit = Real()
    num_hits = Integer()
    num_chains_participated = Integer()
    
    total_payout_pool = Real()
    xanax_cost = Real()
    bounty_cost = Real()
    faction_cut_pct = Real()
    respect_percentage = Real()
    payout_after_costs = Real()
    player_share = Real()
    assist_pay_per = Real()
    pay_outside_hits = Integer()
    
    calculated_at = Integer()

    def __init__(self, **kwargs):
        for field in self.column_names():
            setattr(self, field, kwargs.get(field))
