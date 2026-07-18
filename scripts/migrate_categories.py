"""
Migrate item categorization in existing armoury_news records.
Fixes drugs that were incorrectly categorized as Medical.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.container import ServiceContainer

def migrate_categories():
    services = ServiceContainer()
    db = services.database
    
    # Map incorrect -> correct categories for drugs
    drugs_to_fix = {
        "Xanax": "Drug",
        "Morphine": "Drug",
        "Tramadol": "Drug",
        "Vicodin": "Drug",
    }
    
    logger = services.logger
    total_updated = 0
    
    for item_name, correct_category in drugs_to_fix.items():
        # Update all records for this item
        updated = db.execute(
            "UPDATE armoury_news SET item_category = ? WHERE item_name = ? AND item_category = ?",
            (correct_category, item_name, "Medical")
        )
        count = db.cursor.rowcount
        if count > 0:
            logger.info(f"Updated {count} {item_name} records from Medical → {correct_category}")
            total_updated += count
    
    db.commit()
    logger.info(f"Total records updated: {total_updated}")
    return total_updated

if __name__ == "__main__":
    migrate_categories()
