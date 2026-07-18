"""
repositories/armoury_news_repository.py

Data access layer for armoury news events.
"""

from repositories.base_repository import Repository
from models.armoury_news import ArmouryNews


class ArmouryNewsRepository(Repository):
    """Query and store armoury news events"""
    
    def __init__(self, database):
        super().__init__(database, ArmouryNews)
    
    def by_player(self, player_id, limit=100):
        """Get all armoury events for a player"""
        sql = """
            SELECT * FROM armoury_news
            WHERE player_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        return self.db.select(sql, (player_id, limit))
    
    def by_item(self, item_id, limit=100):
        """Get all usage events for an item"""
        sql = """
            SELECT * FROM armoury_news
            WHERE item_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        return self.db.select(sql, (item_id, limit))
    
    def by_type(self, event_type, limit=100):
        """Get events by type (used, deposited, filled, loaned, received)"""
        sql = """
            SELECT * FROM armoury_news
            WHERE event_type = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        return self.db.select(sql, (event_type, limit))
    
    def by_category(self, item_category, limit=100):
        """Get events by item category (Medical, Utility, Drug, etc.)"""
        sql = """
            SELECT * FROM armoury_news
            WHERE item_category = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        return self.db.select(sql, (item_category, limit))
    
    def by_timerange(self, from_timestamp, to_timestamp, limit=1000):
        """Get events within a timestamp range"""
        sql = """
            SELECT * FROM armoury_news
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        return self.db.select(sql, (from_timestamp, to_timestamp, limit))
    
    def total_cost_by_type(self, event_type, from_timestamp=None, to_timestamp=None):
        """Calculate total cost for event type (used, deposited, etc.)"""
        if from_timestamp and to_timestamp:
            sql = """
                SELECT SUM(n.quantity * COALESCE(p.manual_override, p.market_average, n.item_price, 0)) as total_cost,
                       COUNT(*) as event_count,
                       COUNT(DISTINCT n.player_id) as player_count
                FROM armoury_news n
                LEFT JOIN item_prices p ON p.item_id = n.item_id
                WHERE n.event_type = ? AND n.timestamp BETWEEN ? AND ?
            """
            result = self.db.select(sql, (event_type, from_timestamp, to_timestamp))
        else:
            sql = """
                SELECT SUM(n.quantity * COALESCE(p.manual_override, p.market_average, n.item_price, 0)) as total_cost,
                       COUNT(*) as event_count,
                       COUNT(DISTINCT n.player_id) as player_count
                FROM armoury_news n
                LEFT JOIN item_prices p ON p.item_id = n.item_id
                WHERE n.event_type = ?
            """
            result = self.db.select(sql, (event_type,))
        
        if result:
            return dict(result[0])
        return {"total_cost": 0, "event_count": 0, "player_count": 0}
    
    def total_cost_by_category(self, item_category, from_timestamp=None, to_timestamp=None):
        """Calculate total cost for item category"""
        if from_timestamp and to_timestamp:
            sql = """
                SELECT SUM(n.quantity * COALESCE(p.manual_override, p.market_average, n.item_price, 0)) as total_cost,
                       COUNT(*) as event_count,
                       COUNT(DISTINCT n.item_id) as item_count,
                       COUNT(DISTINCT n.player_id) as player_count
                FROM armoury_news n
                LEFT JOIN item_prices p ON p.item_id = n.item_id
                WHERE n.item_category = ? AND n.timestamp BETWEEN ? AND ?
            """
            result = self.db.select(sql, (item_category, from_timestamp, to_timestamp))
        else:
            sql = """
                SELECT SUM(n.quantity * COALESCE(p.manual_override, p.market_average, n.item_price, 0)) as total_cost,
                       COUNT(*) as event_count,
                       COUNT(DISTINCT n.item_id) as item_count,
                       COUNT(DISTINCT n.player_id) as player_count
                FROM armoury_news n
                LEFT JOIN item_prices p ON p.item_id = n.item_id
                WHERE n.item_category = ?
            """
            result = self.db.select(sql, (item_category,))
        
        if result:
            return dict(result[0])
        return {"total_cost": 0, "event_count": 0, "item_count": 0, "player_count": 0}
    
    def latest_timestamp(self):
        """Get the most recent armoury news timestamp"""
        sql = "SELECT MAX(timestamp) as latest FROM armoury_news"
        result = self.db.select(sql)
        if result and result[0]["latest"]:
            return result[0]["latest"]
        return None
    
    def get_latest_event_id(self):
        """Get the highest event_id for live sync"""
        sql = "SELECT MAX(event_id) as max_id FROM armoury_news"
        result = self.db.select(sql)
        if result and result[0]["max_id"]:
            return result[0]["max_id"]
        return 0
    
    def exists(self, event_id: int) -> bool:
        """Check if an armoury event already exists"""
        sql = "SELECT 1 FROM armoury_news WHERE event_id = ? LIMIT 1"
        result = self.db.select(sql, (event_id,))
        return bool(result)
