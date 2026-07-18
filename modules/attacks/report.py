"""
modules/attacks/report.py

Chain analysis and reporting.
Find specific hits in chains, chain statistics, etc.
"""

from repositories.attack_repository import AttackRepository


class AttackReport:
    """Generate attack and chain reports"""

    def __init__(self, database):
        self.repo = AttackRepository(database)
        self.db = database

    #########################################################

    def _get_chain_window(self, chain_id):
        """Look up a chain's timestamp window by chain_id."""
        rows = self.db.select(
            "SELECT timestamp_start, timestamp_end FROM chains WHERE chain_id = ?",
            (chain_id,)
        )
        if not rows:
            return None, None
        return rows[0]["timestamp_start"], rows[0]["timestamp_end"]

    #########################################################

    def chain_hit(self, chain_id, hit_number):
        """
        Find the attacker who made the Nth hit in a chain.
        Uses the chain field (which stores the hit number within that chain)
        to find attacks belonging to the chain's time window.
        
        Args:
            chain_id: The chain ID from the chains table
            hit_number: Which hit number to find (matches the chain field value)
        
        Returns:
            dict with attack details or None if hit doesn't exist
        """
        ts_start, ts_end = self._get_chain_window(chain_id)
        if ts_start is None:
            return None

        sql = """
            SELECT 
                attack_id,
                attacker_id,
                attacker_name,
                attacker_level,
                attacker_faction_name,
                defender_id,
                defender_name,
                defender_level,
                result,
                respect_gain,
                respect_loss,
                timestamp_started,
                timestamp_ended,
                chain
            FROM attacks
            WHERE timestamp_started BETWEEN ? AND ?
              AND chain = ?
            ORDER BY timestamp_started ASC
            LIMIT 1
        """

        rows = self.db.select(sql, (ts_start, ts_end, hit_number))
        if rows:
            row = dict(rows[0])
            row["hit_position"] = hit_number
            return row
        return None

    #########################################################

    def chain_stats(self, chain_id, top_n=10, faction_id=None):
        """
        Get comprehensive statistics for a chain.

        Args:
            chain_id: Chain ID from the chains table
            top_n: How many top attackers to include (default 10)
            faction_id: If set, top attackers list is filtered to this faction
        """
        ts_start, ts_end = self._get_chain_window(chain_id)
        if ts_start is None:
            return None

        faction_filter = "AND attacker_faction_id = ?" if faction_id else ""
        faction_params = (faction_id,) if faction_id else ()

        # Overall stats (all attackers)
        overall_sql = """
            SELECT
                COUNT(*) as total_hits,
                COUNT(DISTINCT attacker_id) as unique_attackers,
                SUM(CASE WHEN respect_gain > 0 THEN 1 ELSE 0 END) * 100.0 /
                    COUNT(*) as success_rate_pct,
                SUM(respect_gain) as total_respect_gained,
                AVG(CASE WHEN respect_gain > 0 THEN respect_gain END) as avg_respect_per_hit,
                MAX(timestamp_ended) - MIN(timestamp_started) as duration_seconds,
                MIN(chain) as chain_start_num,
                MAX(chain) as chain_end_num
            FROM attacks
            WHERE timestamp_started BETWEEN ? AND ?
        """
        rows = self.db.select(overall_sql, (ts_start, ts_end))
        if not rows or rows[0]["total_hits"] == 0:
            return None

        stats = dict(rows[0])

        # Result breakdown
        result_sql = """
            SELECT result, COUNT(*) as count, SUM(respect_gain) as respect
            FROM attacks
            WHERE timestamp_started BETWEEN ? AND ?
            GROUP BY result
            ORDER BY count DESC
        """
        stats["result_breakdown"] = [
            dict(r) for r in self.db.select(result_sql, (ts_start, ts_end))
        ]

        # Top N attackers (faction-filtered if faction_id provided)
        top_sql = f"""
            SELECT
                attacker_id,
                attacker_name,
                attacker_faction_name,
                COUNT(*) as hits,
                SUM(respect_gain) as total_respect,
                AVG(CASE WHEN respect_gain > 0 THEN respect_gain END) as avg_respect,
                SUM(CASE WHEN respect_gain > 0 THEN 1 ELSE 0 END) as successful_hits,
                ROUND(
                    SUM(CASE WHEN respect_gain > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1
                ) as success_rate_pct,
                MIN(chain) as first_hit,
                MAX(chain) as last_hit
            FROM attacks
            WHERE timestamp_started BETWEEN ? AND ?
            {faction_filter}
            GROUP BY attacker_id
            ORDER BY hits DESC, total_respect DESC
            LIMIT ?
        """
        stats["top_attackers"] = [
            dict(r) for r in self.db.select(top_sql, (ts_start, ts_end) + faction_params + (top_n,))
        ]

        return stats

    #########################################################

    def chain_player(self, chain_id, player_name):
        """
        Get all attacks by a specific player within a chain's time window.

        Args:
            chain_id: Chain ID from the chains table
            player_name: Attacker name to look up (case-insensitive)

        Returns:
            dict with player summary and list of attacks, or None if not found
        """
        ts_start, ts_end = self._get_chain_window(chain_id)
        if ts_start is None:
            return None

        sql = """
            SELECT
                attack_id,
                attacker_name,
                attacker_faction_name,
                defender_name,
                defender_faction_name,
                result,
                respect_gain,
                respect_loss,
                chain,
                timestamp_started,
                modifier_fair_fight,
                modifier_chain
            FROM attacks
            WHERE timestamp_started BETWEEN ? AND ?
              AND LOWER(attacker_name) = LOWER(?)
            ORDER BY timestamp_started ASC
        """
        rows = self.db.select(sql, (ts_start, ts_end, player_name))
        if not rows:
            return None

        attacks = [dict(r) for r in rows]
        total_hits = len(attacks)
        successful = [a for a in attacks if a["respect_gain"] > 0]

        return {
            "player_name": attacks[0]["attacker_name"],
            "faction_name": attacks[0]["attacker_faction_name"],
            "total_hits": total_hits,
            "successful_hits": len(successful),
            "success_rate_pct": round(len(successful) * 100.0 / total_hits, 1),
            "total_respect": round(sum(a["respect_gain"] for a in attacks), 2),
            "avg_respect": round(sum(a["respect_gain"] for a in successful) / len(successful), 2) if successful else 0,
            "first_hit": attacks[0]["chain"],
            "last_hit": attacks[-1]["chain"],
            "attacks": attacks,
        }

    #########################################################

    def chain_timeline(self, chain_id):
        """Get chronological list of all attacks in a chain."""
        ts_start, ts_end = self._get_chain_window(chain_id)
        if ts_start is None:
            return []

        sql = """
            SELECT 
                attack_id,
                attacker_id,
                attacker_name,
                attacker_level,
                defender_id,
                defender_name,
                result,
                respect_gain,
                timestamp_started,
                chain
            FROM attacks
            WHERE timestamp_started BETWEEN ? AND ?
            ORDER BY timestamp_started ASC
        """

        rows = self.db.select(sql, (ts_start, ts_end))
        return [dict(row) for row in rows]

    #########################################################

    def chain_leaderboard(self, chain_id, faction_id=None):
        """Get ranked list of attackers in a chain, optionally filtered to one faction."""
        ts_start, ts_end = self._get_chain_window(chain_id)
        if ts_start is None:
            return []

        if faction_id is not None:
            sql = """
                SELECT 
                    attacker_id,
                    attacker_name,
                    attacker_level,
                    attacker_faction_name,
                    COUNT(*) as hits,
                    SUM(respect_gain) as total_respect,
                    AVG(respect_gain) as avg_respect,
                    SUM(CASE WHEN respect_gain > 0 THEN 1 ELSE 0 END) as successful_hits,
                    ROUND(
                        SUM(CASE WHEN respect_gain > 0 THEN 1 ELSE 0 END) * 100.0 / 
                        COUNT(*), 2
                    ) as success_rate_pct
                FROM attacks
                WHERE timestamp_started BETWEEN ? AND ?
                  AND attacker_faction_id = ?
                GROUP BY attacker_id
                ORDER BY hits DESC, total_respect DESC
            """
            rows = self.db.select(sql, (ts_start, ts_end, faction_id))
        else:
            sql = """
                SELECT 
                    attacker_id,
                    attacker_name,
                    attacker_level,
                    attacker_faction_name,
                    COUNT(*) as hits,
                    SUM(respect_gain) as total_respect,
                    AVG(respect_gain) as avg_respect,
                    SUM(CASE WHEN respect_gain > 0 THEN 1 ELSE 0 END) as successful_hits,
                    ROUND(
                        SUM(CASE WHEN respect_gain > 0 THEN 1 ELSE 0 END) * 100.0 / 
                        COUNT(*), 2
                    ) as success_rate_pct
                FROM attacks
                WHERE timestamp_started BETWEEN ? AND ?
                GROUP BY attacker_id
                ORDER BY hits DESC, total_respect DESC
            """
            rows = self.db.select(sql, (ts_start, ts_end))

        return [dict(row) for row in rows]

    #########################################################

    def attacks_with_chain_info(self, chain_number=None, limit=50):
        """
        Correlate synced attacks with chain metadata based on timestamps.
        Shows which official chain (from chains table) each attack belongs to.
        
        Args:
            chain_number: Optional filter by chain number (e.g., 5000)
            limit: Max results to return
        
        Returns:
            List of attacks with matching chain metadata
        """
        if chain_number is not None:
            sql = """
                SELECT 
                    a.attack_id,
                    a.attacker_name,
                    a.defender_name,
                    a.result,
                    a.respect_gain,
                    a.timestamp_started,
                    c.chain_number,
                    c.respect as chain_total_respect,
                    c.timestamp_start as chain_start,
                    c.timestamp_end as chain_end
                FROM attacks a
                LEFT JOIN chains c ON 
                    a.timestamp_started >= c.timestamp_start AND 
                    a.timestamp_started <= c.timestamp_end
                WHERE c.chain_number = ?
                ORDER BY a.timestamp_started ASC
                LIMIT ?
            """
            rows = self.db.select(sql, (chain_number, limit))
        else:
            sql = """
                SELECT 
                    a.attack_id,
                    a.attacker_name,
                    a.defender_name,
                    a.result,
                    a.respect_gain,
                    a.timestamp_started,
                    c.chain_number,
                    c.respect as chain_total_respect,
                    c.timestamp_start as chain_start,
                    c.timestamp_end as chain_end
                FROM attacks a
                LEFT JOIN chains c ON 
                    a.timestamp_started >= c.timestamp_start AND 
                    a.timestamp_started <= c.timestamp_end
                WHERE c.chain_number IS NOT NULL
                ORDER BY a.timestamp_started DESC
                LIMIT ?
            """
            rows = self.db.select(sql, (limit,))

        return [dict(row) for row in rows]
