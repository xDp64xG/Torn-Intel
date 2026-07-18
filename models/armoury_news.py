"""
models/armoury_news.py

Armoury news event model - tracks faction armoury item usage, loans, and deposits.
"""

from core.field import Integer, Text, Real
from core.model import Model


class ArmouryNews(Model):
    """Faction armoury activity log"""
    
    table_name = "armoury_news"
    
    event_id = Text(primary=True)  # String UUID from Torn API
    timestamp = Integer()
    player_id = Integer()
    player_name = Text()
    event_type = Text()  # 'used', 'filled', 'deposited', 'loaned', 'received'
    item_id = Integer()
    item_name = Text()
    item_category = Text()  # 'Medical', 'Utility', 'Drug', 'Booster', 'Temporary', 'Weapon', 'Armor'
    quantity = Integer()
    description = Text()  # Full parsed event description
    raw_news = Text()  # Raw HTML from API
    item_price = Real()  # Price paid or market average
    price_source = Text()  # 'market_average', 'manual_override', 'unknown'
    
    def __init__(self, **kwargs):
        """Initialize armoury news record"""
        super().__init__(**kwargs)


class ItemPrice(Model):
    """Item market price tracking"""
    
    table_name = "item_prices"
    
    item_id = Integer(primary=True)
    item_name = Text()
    item_category = Text()
    market_average = Real()
    manual_override = Real()  # NULL if using market price
    last_updated = Integer()
    market_source = Text()  # 'torn_v2_api', 'manual'
    
    def __init__(self, **kwargs):
        """Initialize item price record"""
        super().__init__(**kwargs)
