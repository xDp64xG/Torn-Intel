"""
Update item_ids in existing armoury_news records based on item names.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.container import ServiceContainer
from modules.armoury.parser import ArmouryParser

def backfill_item_ids():
    services = ServiceContainer()
    db = services.database
    logger = services.logger
    
    # Get all unique items with item_id=0
    db.execute(
        "SELECT DISTINCT item_name, COUNT(*) as cnt FROM armoury_news WHERE item_id = 0 GROUP BY item_name"
    )
    items = db.fetchall()
    
    logger.info(f"Backfilling item_ids for {len(items)} unique items...")
    
    total_updated = 0
    
    for row in items:
        item_name = row["item_name"]
        cnt = row["cnt"]
        
        # Get item_id and category
        item_id = ArmouryParser.get_item_id(item_name)
        item_category = ArmouryParser.get_item_category(item_name)
        
        # Update all records for this item
        db.execute(
            "UPDATE armoury_news SET item_id = ?, item_category = ? WHERE item_name = ? AND item_id = 0",
            (item_id, item_category, item_name)
        )
        updated = db.cursor.rowcount
        total_updated += updated
        logger.info(f"  {item_name:<30} -> id={item_id:<4} category={item_category:<10} ({updated} records)")
    
    db.commit()
    logger.info(f"Total records updated: {total_updated}")
    return total_updated

if __name__ == "__main__":
    backfill_item_ids()
