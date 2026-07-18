"""
repositories/rankedwar_repository.py

Database access layer for ranked wars.
"""

from repositories.base_repository import Repository
from models.rankedwar import RankedWar


class RankedWarRepository(Repository):
    """
    Repository for RankedWar model.
    """
    
    def __init__(self, database):
        super().__init__(database, RankedWar)
    
    def by_id(self, war_id):
        """Get a single war by war_id."""
        rows = self.db.select(f"""
            SELECT * FROM {RankedWar.table_name}
            WHERE war_id = ?
        """, (war_id,))
        if rows:
            return rows[0]
        return None
    
    def by_opponent(self, faction_id):
        """Get all wars against a specific opponent faction."""
        return self.db.select(f"""
            SELECT * FROM {RankedWar.table_name}
            WHERE opponent_faction_id = ?
            ORDER BY war_start DESC
        """, (faction_id,))
    
    def by_date_range(self, from_timestamp, to_timestamp):
        """Get all wars in a date range."""
        return self.db.select(f"""
            SELECT * FROM {RankedWar.table_name}
            WHERE war_start >= ? AND war_start <= ?
            ORDER BY war_start DESC
        """, (from_timestamp, to_timestamp))
    
    def by_winner(self, faction_id):
        """Get all wars won by a faction."""
        return self.db.select(f"""
            SELECT * FROM {RankedWar.table_name}
            WHERE war_winner_id = ?
            ORDER BY war_start DESC
        """, (faction_id,))
    
    def all_wars(self, limit=None):
        """Get all wars."""
        query = f"""
            SELECT * FROM {RankedWar.table_name}
            ORDER BY war_start DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        
        return self.db.select(query)
