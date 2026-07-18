"""
Reclassify stored armoury items based on parser rules with optional Torn API fallback.

Fallback behavior:
- If parser cannot resolve an item ID, use Torn item catalogue by exact name.
- If parser returns Unknown category, map Torn item type to local category.
"""

import argparse
import os
import sys
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.armoury.parser import ArmouryParser
from services.container import ServiceContainer


def _fetch_torn_items(api_key):
    response = requests.get(
        "https://api.torn.com/torn/",
        params={"selections": "items", "key": api_key},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Torn API error: {data['error']}")
    return data.get("items", {})


def reclassify_armoury_categories(use_api_fallback=False):
    services = ServiceContainer()
    db = services.database
    logger = services.logger

    api_lookup = {}
    if use_api_fallback:
        load_dotenv()
        keys = [k.strip() for k in os.getenv("TORN_API_KEYS", "").split(",") if k.strip()]
        if not keys:
            logger.warning("No TORN_API_KEYS configured; running parser-only reclassification")
        else:
            try:
                items = _fetch_torn_items(keys[0])
                api_lookup = {
                    info.get("name", "").lower(): (int(item_id), info.get("type", "Unknown"))
                    for item_id, info in items.items()
                    if info.get("name")
                }
                logger.info(f"Loaded {len(api_lookup)} Torn item metadata records for fallback reclassification")
            except Exception as exc:
                logger.warning(f"Failed to load Torn item metadata, continuing parser-only: {exc}")

    rows = db.select(
        """
        SELECT DISTINCT item_name
        FROM armoury_news
        WHERE item_name IS NOT NULL AND item_name != ''
        ORDER BY item_name
        """
    )

    event_updates = 0
    price_updates = 0
    id_updates = 0
    fallback_id_updates = 0
    fallback_category_updates = 0

    logger.info(f"Reclassifying {len(rows)} distinct armoury item names...")

    for row in rows:
        item_name = row["item_name"]
        category = ArmouryParser.get_item_category(item_name)
        item_id = ArmouryParser.get_item_id(item_name)

        if api_lookup:
            api_id, api_type = api_lookup.get(item_name.lower(), (0, "Unknown"))
            if item_id == 0 and api_id > 0:
                item_id = api_id
                fallback_id_updates += 1
            if category == "Unknown":
                api_category = ArmouryParser.get_category_from_api_type(api_type)
                if api_category != "Unknown":
                    category = api_category
                    fallback_category_updates += 1

        db.execute(
            "UPDATE armoury_news SET item_category = ? WHERE item_name = ? AND item_category != ?",
            (category, item_name, category),
        )
        event_updates += db.cursor.rowcount

        if item_id > 0:
            db.execute(
                "UPDATE armoury_news SET item_id = ? WHERE item_name = ? AND item_id = 0",
                (item_id, item_name),
            )
            id_updates += db.cursor.rowcount

        db.execute(
            "UPDATE item_prices SET item_category = ? WHERE item_name = ? AND item_category != ?",
            (category, item_name, category),
        )
        price_updates += db.cursor.rowcount

    db.commit()
    logger.info(
        "Reclassification complete. "
        f"category_updates={event_updates}, price_updates={price_updates}, id_updates={id_updates}, "
        f"fallback_id_matches={fallback_id_updates}, fallback_category_matches={fallback_category_updates}"
    )
    return {
        "category_updates": event_updates,
        "price_updates": price_updates,
        "id_updates": id_updates,
        "fallback_id_matches": fallback_id_updates,
        "fallback_category_matches": fallback_category_updates,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reclassify armoury items using parser rules with optional API fallback")
    parser.add_argument(
        "--use-api-fallback",
        action="store_true",
        help="Use torn/items metadata to fill unknown item IDs/categories",
    )
    args = parser.parse_args()
    reclassify_armoury_categories(use_api_fallback=args.use_api_fallback)