"""
modules/rankedwars/payout.py

War payout calculation engine.
Calculates fair payouts based on war hits, assists, and parameters.
"""

import time
from models.payout import Payout

# Torn bonus milestones - these chain positions award extra respect
BONUS_MILESTONES = {10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000}


class WarPayoutCalculator:
    """Calculate war payouts for all participants."""
    
    def __init__(self, database, logger, settings=None):
        self.database = database
        self.logger = logger
        self.settings = settings
    
    def calculate_payouts(self, war_id, total_payout, xanax_cost, faction_cut_pct, 
                         bounty_cost=0, per_assist=0, pay_outside_hits=0):
        """
        Calculate payouts for all players in a war.
        
        Args:
            war_id: The ranked war ID
            total_payout: Total payout pool in dollars
            xanax_cost: Xanax cost to deduct
            faction_cut_pct: Faction cut percentage (0-100)
            bounty_cost: Bounty cost to deduct (flat)
            per_assist: Payment per assist (only on opposing faction)
            pay_outside_hits: Whether to pay for hits outside war (0=no, 1=yes)
        
        Returns:
            Dict with summary and payouts for display
        """
        
        # Get war info
        from models.rankedwar import RankedWar
        war_rows = self.database.select(f"""
            SELECT * FROM {RankedWar.table_name}
            WHERE war_id = ?
        """, (war_id,))
        
        if not war_rows:
            return None
        
        war = war_rows[0]
        war_start = war["war_start"]
        war_end = war["war_end"]
        our_faction_id = war["our_faction_id"]
        opponent_faction_id = war["opponent_faction_id"]
        
        # Get all chains that fall within war window
        chains = self.database.select("""
            SELECT chain_id, chain_number FROM chains
            WHERE timestamp_start >= ? AND timestamp_end <= ?
            ORDER BY chain_number ASC
        """, (war_start, war_end))
        
        chain_ids = [c["chain_id"] for c in chains] if chains else []
        
        # STEP 1: Query all attacks within war window against OPPONENT FACTION ONLY
        # Use is_ranked_war=1 flag to ensure only actual war hits are counted
        # (Excludes fights with 0 respect or outside official war scope)
        attacks = self.database.select("""
            SELECT 
                attacker_id,
                attacker_name,
                defender_faction_id,
                respect_gain,
                chain,
                is_ranked_war,
                result
            FROM attacks
            WHERE attacker_faction_id = ?
            AND timestamp_started >= ? 
            AND timestamp_started <= ?
            AND defender_faction_id = ?
            AND is_ranked_war = 1
            AND result != 'Assist'
            ORDER BY attacker_id ASC
        """, (our_faction_id, war_start, war_end, opponent_faction_id))
        
        if not attacks:
            return []
        
        # Calculate official_war_respect from actual database attacks
        # (NOT from war["our_score"] which may assume more attacks than we have synced)
        official_war_respect = sum(a["respect_gain"] or 0 for a in attacks)
        
        # STEP 2: Group attacks by player
        # We've already filtered to only opponent faction and excluded assists
        # So all attacks here are valid war hits (regardless of is_ranked_war flag)
        player_stats = {}
        player_hits = {}  # Track individual hit values per player
        
        for attack in attacks:
            player_id = attack["attacker_id"]
            player_name = attack["attacker_name"]
            respect = attack["respect_gain"] if attack["respect_gain"] else 0
            chain_pos = attack["chain"] if attack["chain"] else 0
            
            if player_id not in player_stats:
                player_stats[player_id] = {
                    "name": player_name,
                    "war_hits": 0,
                }
                player_hits[player_id] = {
                    "war_hits": [],  # Collect all war hit values with chain positions
                }
            
            # All attacks here are valid war hits (already filtered)
            player_stats[player_id]["war_hits"] += 1
            player_hits[player_id]["war_hits"].append({"value": respect, "chain": chain_pos})
        
        # STEP 3: Apply bonus milestone averaging
        # Bonus hits (at milestones: 10, 25, 50, 100, 250, 500, etc.) are averaged
        # with non-bonus hits to prevent overpayment
        
        player_war_respect = {}
        player_bonus_hits = {}  # Track bonus hit count per player
        total_war_attacks = sum(stats["war_hits"] for stats in player_stats.values())
        
        for player_id, hits_data in player_hits.items():
            war_hits = hits_data["war_hits"]
            
            # Separate bonus and non-bonus hits
            bonus_hits = [h for h in war_hits if h["chain"] in BONUS_MILESTONES]
            non_bonus_hits = [h for h in war_hits if h["chain"] not in BONUS_MILESTONES]
            
            # Store bonus hit count for this player
            player_bonus_hits[player_id] = len(bonus_hits)
            
            # Calculate fair value from non-bonus hits
            if len(non_bonus_hits) > 0:
                non_bonus_respect_total = sum(h["value"] for h in non_bonus_hits)
                fair_value_per_hit = non_bonus_respect_total / len(non_bonus_hits)
                
                # Replace each bonus hit with fair average value
                adjusted_total = non_bonus_respect_total + (len(bonus_hits) * fair_value_per_hit)
                player_war_respect[player_id] = adjusted_total
            else:
                # All hits are bonuses (rare case)
                # Use sum of bonus hits as-is
                player_war_respect[player_id] = sum(h["value"] for h in bonus_hits)
        
        if total_war_attacks > 0:
            true_average_per_hit = official_war_respect / total_war_attacks
        else:
            true_average_per_hit = 0
        
        self.logger.info(f"War {war_id}: Total respect={official_war_respect}, Total attacks={total_war_attacks}, Avg={true_average_per_hit:.4f}")
        
        # STEP 4: Query assists and calculate payouts using bonus-adjusted respect values
        assists_query = self.database.select("""
            SELECT attacker_id, attacker_name, COUNT(*) as assist_count
            FROM attacks
            WHERE attacker_faction_id = ?
            AND timestamp_started >= ?
            AND timestamp_started <= ?
            AND defender_faction_id = ?
            AND result = 'Assist'
            GROUP BY attacker_id
        """, (our_faction_id, war_start, war_end, opponent_faction_id))
        
        assists_by_player = {}
        if assists_query:
            for row in assists_query:
                assists_by_player[row["attacker_id"]] = row["assist_count"]
        
        player_payouts = []
        total_assist_cost = 0
        
        for player_id, stats in player_stats.items():
            num_war_hits = stats["war_hits"]
            num_assists = assists_by_player.get(player_id, 0)
            num_bonus_hits = player_bonus_hits.get(player_id, 0)
            
            # Use actual database respect (no normalization or calibration)
            war_respect = player_war_respect.get(player_id, 0)
            
            # Assist cost
            assist_cost = num_assists * per_assist
            total_assist_cost += assist_cost
            
            player_payouts.append({
                "player_id": player_id,
                "player_name": stats["name"],
                "num_hits": num_war_hits,
                "num_war_hits": num_war_hits,
                "num_assists": num_assists,
                "num_bonus_hits": num_bonus_hits,
                "war_respect": war_respect,
                "total_respect": war_respect,
            })
        
        # Calculate payout pool
        # Faction cut applies to the FULL payout first, then costs are deducted
        faction_cut_amount = total_payout * (faction_cut_pct / 100.0)
        pool_after_faction_cut = total_payout - faction_cut_amount
        payout_pool = pool_after_faction_cut - xanax_cost - bounty_cost - total_assist_cost
        payout_after_costs = payout_pool
        
        # Use bonus-adjusted respect as total for distribution
        # Sum all players' adjusted respect values (from bonus milestone averaging)
        total_war_respect = sum(player_war_respect.values()) if player_war_respect else official_war_respect
        
        # Calculate $ per respect for payouts
        dollar_per_respect = payout_pool / total_war_respect if total_war_respect > 0 else 0
        
        # Build final payouts with all details
        payouts = []
        for player_payout in player_payouts:
            if player_payout["total_respect"] == 0 and player_payout["num_assists"] == 0:
                continue  # Skip players with no contribution
            
            respect_pct = (player_payout["total_respect"] / total_war_respect) * 100 if total_war_respect > 0 else 0
            respect_share = (respect_pct / 100.0) * payout_pool if respect_pct > 0 else 0
            
            # Assist payout (flat per assist)
            assist_payout = player_payout["num_assists"] * per_assist
            
            # Total player share
            player_share = respect_share + assist_payout
            
            payout_obj = {
                "player_id": player_payout["player_id"],
                "player_name": player_payout["player_name"],
                "num_hits": player_payout["num_hits"],
                "num_war_hits": player_payout["num_war_hits"],
                "num_assists": player_payout["num_assists"],
                "num_bonus_hits": player_payout["num_bonus_hits"],
                "num_outside": 0,
                "war_respect": player_payout["war_respect"],
                "outside_respect": 0,
                "total_respect": player_payout["total_respect"],
                "respect_pct": respect_pct,
                "respect_share": respect_share,
                "assist_payout": assist_payout,
                "outside_payout": 0,
                "player_share": player_share,
            }
            payouts.append(payout_obj)
        
        # Sort by player_share descending
        payouts.sort(key=lambda x: x["player_share"], reverse=True)
        
        # Store in database
        calculated_at = int(time.time())
        for payout_obj in payouts:
            payout_record = Payout(
                war_id=war_id,
                player_id=payout_obj["player_id"],
                player_name=payout_obj["player_name"],
                war_hits=payout_obj["num_war_hits"],
                war_respect=payout_obj["war_respect"],
                assist_count=payout_obj["num_assists"],
                num_bonus_hits=payout_obj["num_bonus_hits"],
                assist_payout=payout_obj["assist_payout"],
                outside_hits=0,
                outside_respect=0,
                outside_payout=0,
                total_respect=payout_obj["total_respect"],
                regular_respect=0,
                chain_bonus_respect=0,
                avg_respect_per_hit=true_average_per_hit,
                num_hits=payout_obj["num_hits"],
                num_chains_participated=0,
                total_payout_pool=total_payout,
                xanax_cost=xanax_cost,
                bounty_cost=bounty_cost,
                faction_cut_pct=faction_cut_pct,
                respect_percentage=payout_obj["respect_pct"],
                payout_after_costs=payout_after_costs,
                player_share=payout_obj["player_share"],
                assist_pay_per=per_assist,
                pay_outside_hits=pay_outside_hits,
                calculated_at=calculated_at,
            )
            self.database.insert(Payout.table_name, payout_record.to_dict())
        
        # Return summary data for printing
        return {
            "war_id": war_id,
            "total_payout": total_payout,
            "xanax_cost": xanax_cost,
            "bounty_cost": bounty_cost,
            "faction_cut_pct": faction_cut_pct,
            "total_assist_cost": total_assist_cost,
            "payout_after_costs": payout_after_costs,
            "total_war_respect": total_war_respect,
            "dollar_per_respect": dollar_per_respect,
            "per_assist": per_assist,
            "pay_outside_hits": pay_outside_hits,
            "payouts": payouts,
        }
