"""
modules/rankedwars/report.py

Report generation for ranked wars.
Generates stats about specific wars, including attacks from the active chains.
"""


class RankedWarsReport:
    """
    Generate reports about ranked wars.
    """
    
    def __init__(self, database, logger, settings):
        self.database = database
        self.logger = logger
        self.settings = settings
    
    def war_stats(self, war_id, faction_filter=None):
        """
        Get overall stats for a war.
        
        Args:
            war_id: The war ID to report on
            faction_filter: Optional faction_id to filter attacks to (default: our faction)
        
        Returns:
            Dict with war info, score, winner, chain stats, and top attackers.
        """
        
        # Get the war itself
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
        our_faction_name = war["our_faction_name"]
        opponent_faction_id = war["opponent_faction_id"]
        opponent_faction_name = war["opponent_faction_name"]
        our_score = war["our_score"]
        opponent_score = war["opponent_score"]
        our_chain = war["our_chain"]
        opponent_chain = war["opponent_chain"]
        winner_id = war["war_winner_id"]
        war_target = war["war_target"]
        
        filter_faction = faction_filter or our_faction_id
        
        # Get attacks from our faction during war window (all hits are part of the war)
        our_chain_attacks = self.database.select(f"""
            SELECT * FROM attacks
            WHERE attacker_faction_id = ?
            AND timestamp_started BETWEEN ? AND ?
        """, (filter_faction, war_start, war_end))
        
        our_chain_attacks = our_chain_attacks or []
        
        # Get attacks from opponent faction during war window
        opponent_chain_attacks = self.database.select(f"""
            SELECT * FROM attacks
            WHERE attacker_faction_id = ?
            AND timestamp_started BETWEEN ? AND ?
        """, (opponent_faction_id, war_start, war_end))
        
        opponent_chain_attacks = opponent_chain_attacks or []
        
        # Calculate stats
        our_hits = len(our_chain_attacks)
        opponent_hits = len(opponent_chain_attacks)
        
        our_total_respect = sum(a["respect_gain"] if a["respect_gain"] else 0 for a in our_chain_attacks)
        opponent_total_respect = sum(a["respect_gain"] if a["respect_gain"] else 0 for a in opponent_chain_attacks)
        
        our_avg_respect = our_total_respect / our_hits if our_hits > 0 else 0
        opponent_avg_respect = opponent_total_respect / opponent_hits if opponent_hits > 0 else 0
        
        # Result breakdown (track both hits and respect per result)
        our_result_breakdown = {}
        opponent_result_breakdown = {}
        
        for attack in our_chain_attacks:
            result = attack["result"] if attack["result"] else "Unknown"
            if result not in our_result_breakdown:
                our_result_breakdown[result] = {"hits": 0, "respect": 0}
            our_result_breakdown[result]["hits"] += 1
            our_result_breakdown[result]["respect"] += attack["respect_gain"] if attack["respect_gain"] else 0
        
        for attack in opponent_chain_attacks:
            result = attack["result"] if attack["result"] else "Unknown"
            if result not in opponent_result_breakdown:
                opponent_result_breakdown[result] = {"hits": 0, "respect": 0}
            opponent_result_breakdown[result]["hits"] += 1
            opponent_result_breakdown[result]["respect"] += attack["respect_gain"] if attack["respect_gain"] else 0
        
        # Success rate (attacked/mugged vs other results)
        our_successful = our_result_breakdown.get("Attacked", {}).get("hits", 0) + our_result_breakdown.get("Mugged", {}).get("hits", 0)
        our_success_rate = (our_successful / our_hits * 100) if our_hits > 0 else 0
        
        opponent_successful = opponent_result_breakdown.get("Attacked", {}).get("hits", 0) + opponent_result_breakdown.get("Mugged", {}).get("hits", 0)
        opponent_success_rate = (opponent_successful / opponent_hits * 100) if opponent_hits > 0 else 0
        
        # Top attackers in our chain
        attacker_stats = {}
        
        for attack in our_chain_attacks:
            attacker_id = attack["attacker_id"]
            attacker_name = attack["attacker_name"] if attack["attacker_name"] else "Unknown"
            
            if attacker_id not in attacker_stats:
                attacker_stats[attacker_id] = {
                    "name": attacker_name,
                    "hits": 0,
                    "respect": 0,
                    "first_hit": None,
                    "last_hit": None,
                    "successful": 0,
                }
            
            stats = attacker_stats[attacker_id]
            stats["hits"] += 1
            stats["respect"] += attack["respect_gain"] if attack["respect_gain"] else 0
            
            result = attack["result"] if attack["result"] else ""
            if result in ("Attacked", "Mugged"):
                stats["successful"] += 1
            
            chain_hit = attack["chain"] if attack["chain"] else 0
            if stats["first_hit"] is None or chain_hit < stats["first_hit"]:
                stats["first_hit"] = chain_hit
            if stats["last_hit"] is None or chain_hit > stats["last_hit"]:
                stats["last_hit"] = chain_hit
        
        # Sort by hits descending
        top_attackers = sorted(
            attacker_stats.values(),
            key=lambda x: x["hits"],
            reverse=True,
        )
        
        # Calculate avg_respect and success_rate for each attacker
        for attacker in top_attackers:
            attacker['avg_respect'] = attacker['respect'] / attacker['hits'] if attacker['hits'] > 0 else 0
            attacker['success_rate'] = (attacker['successful'] / attacker['hits'] * 100) if attacker['hits'] > 0 else 0
        
        # Get timestamp (for duration calculation)
        war_duration_sec = war_end - war_start
        war_duration_min = war_duration_sec // 60
        war_duration_hour = war_duration_min // 60
        war_duration_str = f"{war_duration_hour}h {war_duration_min % 60}m"
        
        return {
            "war_id": war_id,
            "our_faction_id": our_faction_id,
            "our_faction_name": our_faction_name,
            "opponent_faction_id": opponent_faction_id,
            "opponent_faction_name": opponent_faction_name,
            "war_start": war_start,
            "war_end": war_end,
            "war_duration_seconds": war_duration_sec,
            "war_duration_str": war_duration_str,
            "war_target": war_target,
            "winner_id": winner_id,
            "winner_name": our_faction_name if winner_id == our_faction_id else opponent_faction_name,
            "our_score": our_score,
            "opponent_score": opponent_score,
            "our_chain": our_chain,
            "opponent_chain": opponent_chain,
            "our_hits": our_hits,
            "opponent_hits": opponent_hits,
            "our_total_respect": our_total_respect,
            "opponent_total_respect": opponent_total_respect,
            "our_avg_respect": our_avg_respect,
            "opponent_avg_respect": opponent_avg_respect,
            "our_success_rate": our_success_rate,
            "opponent_success_rate": opponent_success_rate,
            "our_result_breakdown": our_result_breakdown,
            "opponent_result_breakdown": opponent_result_breakdown,
            "top_attackers": top_attackers,
        }
    
    def war_leaderboard(self, war_id, top_n=10):
        """
        Get top attackers in a war, ranked by various metrics.
        
        Args:
            war_id: The war ID
            top_n: How many to include
        
        Returns:
            List of dicts with rank, name, hits, respect, success rate.
        """
        
        stats = self.war_stats(war_id)
        if not stats:
            return []
        
        top_attackers = stats["top_attackers"][:top_n]
        
        leaderboard = []
        for rank, attacker in enumerate(top_attackers, 1):
            avg_respect = attacker["respect"] / attacker["hits"] if attacker["hits"] > 0 else 0
            success_rate = (attacker["successful"] / attacker["hits"] * 100) if attacker["hits"] > 0 else 0
            
            leaderboard.append({
                "rank": rank,
                "name": attacker["name"],
                "hits": attacker["hits"],
                "respect": attacker["respect"],
                "avg_respect": avg_respect,
                "success_rate": success_rate,
                "hit_range": f"#{attacker['first_hit']}-{attacker['last_hit']}",
            })
        
        return leaderboard
    
    def war_player(self, war_id, player_name):
        """
        Get all attacks by a player within a specific war.
        
        Args:
            war_id: The war ID
            player_name: The player's name (case-insensitive lookup)
        
        Returns:
            Dict with player summary and list of attacks.
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
        our_chain = war["our_chain"]
        opponent_faction_id = war["opponent_faction_id"]
        opponent_chain = war["opponent_chain"]
        
        # Find player by name (case-insensitive) in either chain
        player_attacks = self.database.select(f"""
            SELECT * FROM attacks
            WHERE LOWER(attacker_name) = LOWER(?)
            AND timestamp_started BETWEEN ? AND ?
            AND (
                (attacker_faction_id = ? AND chain = ?)
                OR
                (attacker_faction_id = ? AND chain = ?)
            )
            ORDER BY timestamp_started DESC
        """, (
            player_name,
            war_start,
            war_end,
            our_faction_id,
            our_chain,
            opponent_faction_id,
            opponent_chain,
        ))
        
        player_attacks = player_attacks or []
        
        if not player_attacks:
            return {
                "war_id": war_id,
                "player_name": player_name,
                "hits": 0,
                "total_respect": 0,
                "avg_respect": 0,
                "success_rate": 0,
                "attacks": [],
            }
        
        # Get player info from first attack
        player_id = player_attacks[0]["attacker_id"]
        player_faction_id = player_attacks[0]["attacker_faction_id"]
        
        total_respect = sum(a["respect_gain"] if a["respect_gain"] else 0 for a in player_attacks)
        avg_respect = total_respect / len(player_attacks) if player_attacks else 0
        
        successful = sum(
            1 for a in player_attacks
            if a["result"] in ("Attacked", "Mugged")
        )
        success_rate = (successful / len(player_attacks) * 100) if player_attacks else 0
        
        # Format attack list
        attacks = []
        for attack in player_attacks:
            attacks.append({
                "chain_hit": attack["chain"],
                "timestamp": attack["timestamp_started"],
                "result": attack["result"],
                "respect": attack["respect_gain"],
                "defender": attack["defender_name"],
            })
        
        return {
            "war_id": war_id,
            "player_id": player_id,
            "player_name": player_name,
            "player_faction_id": player_faction_id,
            "hits": len(player_attacks),
            "total_respect": total_respect,
            "avg_respect": avg_respect,
            "success_rate": success_rate,
            "attacks": attacks,
        }
