"""
modules/rankedwars/queries.py

Read-only queries for ranked wars.
No API calls, only local database queries.
"""


class RankedWarsQueries:
    """
    Query interface for ranked wars.
    """
    
    def __init__(self, repository=None, logger=None, database=None):
        self.repo = repository
        self.logger = logger
        self.database = database
    
    def search(self, war_id=None, opponent_faction_id=None, from_timestamp=None, 
               to_timestamp=None, limit=None, order="DESC"):
        """
        Flexible search across ranked wars.
        Filters are ANDed together.
        
        Args:
            war_id: Specific war ID to find
            opponent_faction_id: Wars against a specific faction
            from_timestamp: Lower bound (war_start)
            to_timestamp: Upper bound (war_start)
            limit: Max results
            order: "DESC" (newest first, default) or "ASC" (oldest first)
        
        Returns:
            List of war records (as dicts/rows from database)
        """
        
        where_clauses = []
        where_args = []
        
        if war_id is not None:
            where_clauses.append("war_id = ?")
            where_args.append(war_id)
        
        if opponent_faction_id is not None:
            where_clauses.append("opponent_faction_id = ?")
            where_args.append(opponent_faction_id)
        
        if from_timestamp is not None:
            where_clauses.append("war_start >= ?")
            where_args.append(from_timestamp)
        
        if to_timestamp is not None:
            where_clauses.append("war_start <= ?")
            where_args.append(to_timestamp)
        
        order_str = "war_start DESC" if order == "DESC" else "war_start ASC"
        
        where_clause = " AND ".join(where_clauses) if where_clauses else None
        
        # Use repo if available, otherwise use database directly
        db = self.repo.database if self.repo else self.database
        
        rows = db.select(
            RankedWar.table_name,
            ["*"],
            where=where_clause,
            where_args=where_args,
            order_by=order_str,
            limit=limit,
        )
        
        return rows or []
    
    def all_wars(self):
        """Get all wars, newest first."""
        return self.search()
    
    def wars_against(self, faction_id):
        """Get all wars against a specific opponent faction."""
        return self.search(opponent_faction_id=faction_id)
    
    def wars_in_range(self, from_ts, to_ts):
        """Get all wars in a timestamp range."""
        return self.search(from_timestamp=from_ts, to_timestamp=to_ts)
