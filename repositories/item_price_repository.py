"""
repositories/item_price_repository.py

Data access layer for item pricing.
"""

from repositories.base_repository import Repository
from models.armoury_news import ItemPrice


class ItemPriceRepository(Repository):
    """Query and store item prices"""
    
    def __init__(self, database):
        super().__init__(database, ItemPrice)
    
    def by_category(self, item_category):
        """Get all prices for items in a category"""
        sql = """
            SELECT * FROM item_prices
            WHERE item_category = ?
            ORDER BY item_name
        """
        return self.db.select(sql, (item_category,))
    
    def get_price(self, item_id):
        """Get effective price for an item (override if set, else market average)"""
        sql = """
            SELECT 
                item_id,
                item_name,
                COALESCE(manual_override, market_average) as effective_price,
                manual_override,
                market_average,
                market_source
            FROM item_prices
            WHERE item_id = ?
        """
        result = self.db.select(sql, (item_id,))
        if result:
            return dict(result[0])
        return None
    
    def get_prices_by_ids(self, item_ids):
        """Get prices for multiple items"""
        if not item_ids:
            return []
        
        placeholders = ",".join("?" * len(item_ids))
        sql = f"""
            SELECT 
                item_id,
                item_name,
                COALESCE(manual_override, market_average) as effective_price,
                manual_override,
                market_average
            FROM item_prices
            WHERE item_id IN ({placeholders})
        """
        return self.db.select(sql, item_ids)
    
    def set_manual_override(self, item_id, price):
        """Set manual price override for an item"""
        sql = """
            UPDATE item_prices
            SET manual_override = ?, price_source = 'manual'
            WHERE item_id = ?
        """
        self.db.execute(sql, (price, item_id))
        self.db.commit()
    
    def clear_override(self, item_id):
        """Clear manual override, use market price"""
        sql = """
            UPDATE item_prices
            SET manual_override = NULL, price_source = 'torn_v2_api'
            WHERE item_id = ?
        """
        self.db.execute(sql, (item_id,))
        self.db.commit()
    
    def update_market_price(self, item_id, item_name, item_category, average_price):
        """Update market average price from API"""
        # Check if exists
        sql_check = "SELECT item_id FROM item_prices WHERE item_id = ?"
        exists = self.db.select(sql_check, (item_id,))
        
        if exists:
            sql = """
                UPDATE item_prices
                SET market_average = ?, last_updated = ?, price_source = 'torn_v2_api'
                WHERE item_id = ?
            """
            import time
            self.db.execute(sql, (average_price, int(time.time()), item_id))
        else:
            sql = """
                INSERT INTO item_prices 
                (item_id, item_name, item_category, market_average, last_updated, price_source)
                VALUES (?, ?, ?, ?, ?, 'torn_v2_api')
            """
            import time
            self.db.execute(sql, (item_id, item_name, item_category, average_price, int(time.time())))
        
        self.db.commit()
    
    def medical_items(self):
        """Get all medical items"""
        return self.by_category("Medical")
    
    def utility_items(self):
        """Get all utility items"""
        return self.by_category("Utility")
    
    def drug_items(self):
        """Get all drug items"""
        return self.by_category("Drug")
