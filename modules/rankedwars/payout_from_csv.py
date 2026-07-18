"""
modules/rankedwars/payout_from_csv.py

War payout calculation using official site data from CSV exports.
Reads member respect values directly from Torn's war report CSV.
"""

import csv
import time
from models.payout import Payout


class CSVWarPayoutCalculator:
    """Calculate war payouts using official CSV data from Torn site."""
    
    def __init__(self, database, logger, settings=None):
        self.database = database
        self.logger = logger
        self.settings = settings
    
    def parse_csv(self, csv_path):
        """
        Parse Torn war report CSV.
        
        Format:
        "Faction Name"
        "Members";"Level";"Attacks";"Score"
        "PlayerName [ID]";"level";"attacks";"score"
        ...
        
        Returns:
            Dict with faction_name and members list
        """
        members = []
        faction_name = None
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=';')
            
            for row in reader:
                # Skip empty rows
                if not row or not row[0]:
                    continue
                
                # First non-empty, non-header row is faction name (unquoted then quoted for next faction)
                if row[0].strip().strip('"') and row[0].count('[') == 0 and 'Members' not in row[0]:
                    faction_name = row[0].strip().strip('"')
                    # Reset members for this faction
                    if faction_name in ["Glory to Saints", "49431"]:
                        # We found our faction, skip opponent and prepare for our members
                        members = []
                    continue
                
                # Skip header row
                if "Members" in row[0] or "Level" in row[0]:
                    continue
                
                # Parse member row: "Name [ID]";"Level";"Attacks";"Score"
                if len(row) >= 4 and '[' in row[0]:
                    name_with_id = row[0].strip().strip('"')
                    level = row[1].strip().strip('"') if len(row) > 1 else "0"
                    attacks = row[2].strip().strip('"') if len(row) > 2 else "0"
                    score = row[3].strip().strip('"') if len(row) > 3 else "0.00"
                    
                    # Extract name and ID
                    if '[' in name_with_id and ']' in name_with_id:
                        name = name_with_id[:name_with_id.rfind('[')].strip()
                        player_id = name_with_id[name_with_id.rfind('[')+1:name_with_id.rfind(']')].strip()
                        
                        try:
                            attacks = int(attacks)
                            score = float(score)
                            player_id = int(player_id)
                            
                            members.append({
                                "name": name,
                                "player_id": player_id,
                                "level": int(level),
                                "attacks": attacks,
                                "respect": score,
                            })
                        except ValueError:
                            continue
        
        return {
            "faction_name": faction_name,
            "members": members,
        }
    
    def calculate_payouts_from_csv(self, war_id, csv_path, total_payout, xanax_cost, 
                                   faction_cut_pct, bounty_cost=0, per_assist=0, pay_outside_hits=0):
        """
        Calculate payouts using official CSV data.
        
        Args:
            war_id: The ranked war ID
            csv_path: Path to the CSV export from Torn
            total_payout: Total payout pool in dollars
            xanax_cost: Xanax cost to deduct
            faction_cut_pct: Faction cut percentage (0-100)
            bounty_cost: Bounty cost to deduct (flat)
            per_assist: Payment per assist (from database)
            pay_outside_hits: Whether to pay for hits outside war
        
        Returns:
            Dict with summary and payouts for display
        """
        
        # Parse CSV
        csv_data = self.parse_csv(csv_path)
        members = csv_data["members"]
        
        if not members:
            self.logger.error(f"No members found in CSV: {csv_path}")
            return None
        
        self.logger.info(f"Parsed {len(members)} members from CSV: {csv_data['faction_name']}")
        
        # Get war info for timestamps and assist counting
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
        official_war_respect = war["our_score"]
        
        # Calculate total respect from CSV
        total_csv_respect = sum(m["respect"] for m in members if m["respect"] > 0)
        
        self.logger.info(f"War {war_id}: Official respect from CSV = {total_csv_respect}, Site total = {official_war_respect}")
        
        # Build member lookup by name for assist count matching
        member_by_name = {m["name"]: m for m in members}
        
        # Query assists from database (these are still accurate)
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
        
        assists_by_name = {}
        if assists_query:
            for row in assists_query:
                assists_by_name[row["attacker_name"]] = row["assist_count"]
        
        # Build payouts using CSV respect + database assists
        player_payouts = []
        total_assist_cost = 0
        
        for member in members:
            name = member["name"]
            player_id = member["player_id"]
            war_respect = member["respect"]
            attacks = member["attacks"]
            
            # Get assist count from database (matched by name)
            assist_count = assists_by_name.get(name, 0)
            assist_cost = assist_count * per_assist
            total_assist_cost += assist_cost
            
            player_payouts.append({
                "player_id": player_id,
                "player_name": name,
                "num_hits": attacks,
                "num_war_hits": attacks,
                "num_assists": assist_count,
                "num_outside": 0,
                "war_respect": war_respect,
                "outside_respect": 0,
                "total_respect": war_respect,
            })
        
        # Calculate payout pool
        faction_cut_amount = total_payout * (faction_cut_pct / 100.0)
        pool_after_faction_cut = total_payout - faction_cut_amount
        payout_pool = pool_after_faction_cut - xanax_cost - bounty_cost - total_assist_cost
        payout_after_costs = payout_pool
        
        # Calculate $ per respect
        dollar_per_respect = payout_pool / total_csv_respect if total_csv_respect > 0 else 0
        
        # Build final payouts
        payouts = []
        for player_payout in player_payouts:
            if player_payout["total_respect"] == 0 and player_payout["num_assists"] == 0:
                continue  # Skip players with no contribution
            
            respect_pct = (player_payout["total_respect"] / total_csv_respect) * 100 if total_csv_respect > 0 else 0
            respect_share = (respect_pct / 100.0) * payout_pool if respect_pct > 0 else 0
            
            # Assist payout
            assist_payout = player_payout["num_assists"] * per_assist
            
            # Total player share
            player_share = respect_share + assist_payout
            
            payout_obj = {
                "player_id": player_payout["player_id"],
                "player_name": player_payout["player_name"],
                "num_hits": player_payout["num_hits"],
                "num_war_hits": player_payout["num_war_hits"],
                "num_assists": player_payout["num_assists"],
                "num_outside": player_payout["num_outside"],
                "war_respect": player_payout["war_respect"],
                "outside_respect": player_payout["outside_respect"],
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
                assist_payout=payout_obj["assist_payout"],
                outside_hits=payout_obj["num_outside"],
                outside_respect=payout_obj["outside_respect"],
                outside_payout=0,
                total_respect=payout_obj["total_respect"],
                regular_respect=0,
                chain_bonus_respect=0,
                avg_respect_per_hit=0,
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
        
        # Return summary
        return {
            "war_id": war_id,
            "source": "CSV",
            "total_payout": total_payout,
            "xanax_cost": xanax_cost,
            "bounty_cost": bounty_cost,
            "faction_cut_pct": faction_cut_pct,
            "total_assist_cost": total_assist_cost,
            "payout_after_costs": payout_after_costs,
            "total_war_respect": total_csv_respect,
            "dollar_per_respect": dollar_per_respect,
            "per_assist": per_assist,
            "pay_outside_hits": pay_outside_hits,
            "payouts": payouts,
        }
