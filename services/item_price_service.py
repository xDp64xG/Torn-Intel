"""
services/item_price_service.py

Fetch and update item market prices from Torn API.
Stores prices in item_prices table for use in armoury reports and cost analysis.
"""

import time
import os
import csv
from modules.armoury.parser import ArmouryParser


class ItemPriceService:
    """Fetch and store item market prices"""
    
    def __init__(self, gateway, database, logger, market_gateway=None):
        """Initialize with gateways for API access and database for storage"""
        self.gateway = gateway
        self.market_gateway = market_gateway
        self.database = database
        self.logger = logger

    def _build_items_to_process(self):
        """Build canonical item list from existing prices and armoury usage."""
        items_to_process = {}

        price_rows = self.database.select(
            "SELECT item_id, item_name, item_category FROM item_prices WHERE item_id > 0"
        )
        for row in price_rows:
            items_to_process[row["item_id"]] = {
                "item_name": row["item_name"],
                "item_category": row["item_category"],
            }

        armoury_rows = self.database.select(
            "SELECT DISTINCT item_id, item_name, item_category FROM armoury_news WHERE item_id > 0"
        )
        for row in armoury_rows:
            items_to_process.setdefault(
                row["item_id"],
                {
                    "item_name": row["item_name"],
                    "item_category": row["item_category"],
                },
            )

        return items_to_process
    
    def update_market_prices(self):
        """
        Fetch current market prices from Torn API and store in database.
        Uses the market/itemmarket selection for each known item.
        
        Returns:
            Dict with update summary: {updated_count, error_count, timestamp}
        """
        try:
            self.logger.info("Fetching market prices from API...")

            # Build the list of items to refresh from current prices and synced armoury usage.
            items_to_process = self._build_items_to_process()

            if not items_to_process:
                self.logger.warning("No item IDs found to update")
                return {"updated_count": 0, "error_count": 0}
            
            # Track statistics
            updated = 0
            errors = 0
            current_time = int(time.time())
            
            # Process each item
            for item_id, item_data in items_to_process.items():
                try:
                    item_id = int(item_id)
                    # Primary source: v2 torn/{id}/items -> value.market_price
                    market_data = self.gateway.get_item_value_market_price(item_id)

                    # Fallback to v2 market endpoint if item-value endpoint is unavailable.
                    if not market_data:
                        market_data = self.gateway.get_item_market_price(item_id)

                    if not market_data:
                        errors += 1
                        continue

                    if isinstance(market_data, dict) and "error" in market_data:
                        error = market_data.get("error", {})
                        error_code = error.get("code") if isinstance(error, dict) else None
                        error_text = error.get("error", "Unknown error") if isinstance(error, dict) else str(error)

                        if error_code == 16:
                            self.logger.warning(f"API key lacks permissions for market data: {error_text}")
                            return {
                                "updated_count": 0,
                                "error_count": 0,
                                "message": "Market price endpoint not available with current API key permissions"
                            }

                        self.logger.error(f"Market API error for item {item_id}: {error_text}")
                        errors += 1
                        continue

                    expected_name = (item_data.get("item_name") or "").strip()
                    market_name = (market_data.get("name") or "").strip() if isinstance(market_data, dict) else ""
                    avg_price = market_data.get("average_price", 0) if isinstance(market_data, dict) else 0

                    # Keep armoury identity as source of truth when market name disagrees.
                    # This avoids corrupting rows where market endpoint item IDs differ from armoury IDs.
                    names_match = bool(expected_name) and bool(market_name) and expected_name.lower() == market_name.lower()
                    item_name = expected_name or market_name or f"Item {item_id}"

                    # If names do not match, keep existing price for this item_id unless we already have a trusted value.
                    if market_name and expected_name and not names_match:
                        existing = self.database.select(
                            "SELECT market_average FROM item_prices WHERE item_id = ?",
                            (item_id,),
                        )
                        if existing and existing[0]["market_average"]:
                            avg_price = existing[0]["market_average"]

                    # Determine category from stable item name (fallback, can be overridden)
                    category = self._guess_category(item_name)
                    
                    # Insert or update in database
                    price_source = market_data.get("source") if isinstance(market_data, dict) else None
                    self.database.execute(
                        """
                        INSERT INTO item_prices 
                        (item_id, item_name, item_category, market_average, last_updated, market_source)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(item_id) DO UPDATE SET
                            item_name = excluded.item_name,
                            item_category = excluded.item_category,
                            market_average = excluded.market_average,
                            last_updated = excluded.last_updated,
                            market_source = excluded.market_source
                        """,
                        (item_id, item_name, category, avg_price, current_time, price_source or "torn_v2_api")
                    )
                    updated += 1
                
                except Exception as e:
                    self.logger.error(f"Failed to update item {item_id}: {e}")
                    errors += 1
            
            self.database.commit()
            
            self.logger.info(f"Updated {updated} item prices ({errors} errors)")
            return {
                "updated_count": updated,
                "error_count": errors,
                "timestamp": current_time
            }
        
        except Exception as e:
            self.logger.error(f"Market price update failed: {e}")
            return {"updated_count": 0, "error_count": 1}

    def update_market_prices_bulk(self):
        """
        Fetch market prices for all known IDs using per-item requests.
        Primary source is v2 torn/{id}/items value.market_price.

        Returns:
            Dict with update summary.
        """
        return self.update_market_prices()
    
    def _guess_category(self, item_name):
        """Guess item category from name"""
        return ArmouryParser.get_item_category(item_name)
    
    def get_item_price(self, item_id):
        """Get current price for an item"""
        row = self.database.query_one(
            "SELECT item_id, item_name, market_average, manual_override FROM item_prices WHERE item_id = ?",
            (item_id,)
        )
        
        if not row:
            return None
        
        # Return manual override if set, otherwise market average
        price = row["manual_override"] if row["manual_override"] else row["market_average"]
        return {
            "item_id": row["item_id"],
            "item_name": row["item_name"],
            "price": price,
            "source": "manual" if row["manual_override"] else "market"
        }
    
    def set_manual_price(self, item_id, price):
        """Set a manual override price for an item"""
        # Look up item name from database using item_id
        self.database.execute(
            "SELECT DISTINCT item_name FROM armoury_news WHERE item_id = ? LIMIT 1",
            (item_id,)
        )
        row = self.database.fetchone()
        item_name = row["item_name"] if row else f"Item {item_id}"
        
        # Determine category
        category = ArmouryParser.get_item_category(item_name)
        
        # Insert or replace to ensure the item exists
        current_time = int(time.time())
        self.database.execute(
            """
            INSERT OR REPLACE INTO item_prices 
            (item_id, item_name, item_category, manual_override, last_updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item_id, item_name, category, price, current_time)
        )
        self.database.commit()
        self.logger.info(f"Set manual price for item {item_id} ({item_name}): ${price:,.2f}")

    def missing_prices(self, limit=25, min_uses=5, event_type="used"):
        """Return high-usage armoury items that have no effective price."""
        normalized_event_type = (event_type or "").strip().lower()
        event_filter = normalized_event_type if normalized_event_type else None

        rows = self.database.select(
            """
            SELECT
                n.item_id,
                MAX(n.item_name) AS item_name,
                MAX(n.item_category) AS item_category,
                COUNT(*) AS usage_count,
                SUM(COALESCE(n.quantity, 1)) AS total_quantity,
                MAX(n.timestamp) AS last_seen,
                MAX(COALESCE(p.manual_override, p.market_average, 0)) AS effective_price
            FROM armoury_news n
            LEFT JOIN item_prices p ON p.item_id = n.item_id
            WHERE
                n.item_id > 0
                AND (? IS NULL OR LOWER(n.event_type) = ?)
            GROUP BY n.item_id
            HAVING
                MAX(COALESCE(p.manual_override, p.market_average, 0)) <= 0
                AND COUNT(*) >= ?
            ORDER BY usage_count DESC, total_quantity DESC, item_name ASC
            LIMIT ?
            """,
            (event_filter, event_filter, min_uses, limit),
        )

        return rows

    def export_manual_prices(self, output_path="data/manual_price_overrides.csv"):
        """Export manual item price overrides to CSV."""
        rows = self.database.select(
            """
            SELECT
                item_id,
                item_name,
                item_category,
                manual_override,
                market_average,
                market_source,
                last_updated
            FROM item_prices
            WHERE manual_override IS NOT NULL
            ORDER BY item_category ASC, item_name ASC
            """
        )

        directory = os.path.dirname(output_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(
                csvfile,
                fieldnames=[
                    "item_id",
                    "item_name",
                    "item_category",
                    "manual_override",
                    "market_average",
                    "market_source",
                    "last_updated",
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "item_id": row["item_id"],
                        "item_name": row["item_name"],
                        "item_category": row["item_category"],
                        "manual_override": row["manual_override"],
                        "market_average": row["market_average"],
                        "market_source": row["market_source"],
                        "last_updated": row["last_updated"],
                    }
                )

        return {"path": output_path, "count": len(rows)}
