"""
modules/armoury/queries.py

Query armoury news from database.
"""

from repositories.armoury_news_repository import ArmouryNewsRepository
from repositories.item_price_repository import ItemPriceRepository
from collections import defaultdict, deque


class ArmouryQueries:
    """Query and aggregate armoury data"""
    
    def __init__(self, database, logger):
        """Initialize with database and logger"""
        self.database = database
        self.logger = logger
        self.repo = ArmouryNewsRepository(database)
        self.item_repo = ItemPriceRepository(database)
    
    def player_usage(self, player_id, limit=100):
        """Get all armoury items used by a player"""
        return self.repo.by_player(player_id, limit)
    
    def item_usage(self, item_id, limit=100):
        """Get all usage of a specific item"""
        return self.repo.by_item(item_id, limit)
    
    def usage_by_type(self, event_type, limit=100):
        """Get usage by event type (used, deposited, filled, etc.)"""
        return self.repo.by_type(event_type, limit)
    
    def usage_by_category(self, item_category, limit=100):
        """Get usage by item category (Medical, Utility, etc.)"""
        return self.repo.by_category(item_category, limit)
    
    def usage_in_period(self, from_timestamp, to_timestamp, limit=1000):
        """Get all usage within a timeframe (e.g., during a war)"""
        return self.repo.by_timerange(from_timestamp, to_timestamp, limit)
    
    def cost_by_type(self, event_type, from_timestamp=None, to_timestamp=None):
        """Get total cost for event type within optional timeframe"""
        return self.repo.total_cost_by_type(event_type, from_timestamp, to_timestamp)
    
    def cost_by_category(self, item_category, from_timestamp=None, to_timestamp=None):
        """Get total cost for item category within optional timeframe"""
        return self.repo.total_cost_by_category(item_category, from_timestamp, to_timestamp)
    
    def search(self, player_name=None, item_name=None, category=None, event_type=None, limit=25, order="DESC"):
        """
        Search armoury events with flexible filtering.
        
        Args:
            player_name: Filter by player name (case-insensitive)
            item_name: Filter by item name (case-insensitive)
            category: Filter by item category (Medical, Drug, etc.)
            event_type: Filter by event type (used, deposited, filled, etc.)
            limit: Max results to return
            order: ASC or DESC for sort order
        
        Returns:
            List of matching armoury events
        """
        filters = []
        params = []
        
        if player_name:
            filters.append("LOWER(n.player_name) LIKE LOWER(?)")
            params.append(f"%{player_name}%")
        
        if item_name:
            filters.append("LOWER(n.item_name) LIKE LOWER(?)")
            params.append(f"%{item_name}%")
        
        if category:
            filters.append("LOWER(n.item_category) LIKE LOWER(?)")
            params.append(f"%{category}%")
        
        if event_type:
            filters.append("LOWER(n.event_type) LIKE LOWER(?)")
            params.append(f"%{event_type}%")
        
        where_clause = " AND ".join(filters) if filters else "1=1"
        sql = f"""
            SELECT
                n.*,
                COALESCE(p.manual_override, p.market_average, n.item_price, 0) AS effective_price
            FROM armoury_news n
            LEFT JOIN item_prices p ON p.item_id = n.item_id
            WHERE {where_clause}
            ORDER BY n.timestamp {order}
            LIMIT ?
        """
        params.append(limit)
        
        return self.database.select(sql, tuple(params))
    
    def medical_usage(self, from_timestamp=None, to_timestamp=None):
        """Get total medical item usage and cost"""
        return self.cost_by_category("Medical", from_timestamp, to_timestamp)
    
    def drug_usage(self, from_timestamp=None, to_timestamp=None):
        """Get total drug item usage and cost"""
        return self.cost_by_category("Drug", from_timestamp, to_timestamp)
    
    def utility_usage(self, from_timestamp=None, to_timestamp=None):
        """Get total utility item usage and cost"""
        return self.cost_by_category("Utility", from_timestamp, to_timestamp)
    
    def xanax_usage(self, from_timestamp=None, to_timestamp=None):
        """Get xanax usage statistics"""
        sql = """
            SELECT 
                COUNT(*) as times_used,
                SUM(quantity) as total_quantity,
                COUNT(DISTINCT player_id) as unique_players,
                SUM(quantity * item_price) as total_cost
            FROM armoury_news
            WHERE item_name LIKE '%Xanax%' OR item_name LIKE '%xanax%'
        """
        
        if from_timestamp and to_timestamp:
            sql += f" AND timestamp BETWEEN {from_timestamp} AND {to_timestamp}"
        
        result = self.database.select(sql)
        if result:
            return dict(result[0])
        return {"times_used": 0, "total_quantity": 0, "unique_players": 0, "total_cost": 0}
    
    def blood_bag_usage(self, from_timestamp=None, to_timestamp=None):
        """Get blood bag usage statistics"""
        sql = """
            SELECT 
                COUNT(*) as times_filled,
                COUNT(DISTINCT player_id) as unique_players,
                SUM(quantity * item_price) as total_cost
            FROM armoury_news
            WHERE item_name LIKE '%Blood Bag%' AND event_type = 'filled'
        """
        
        if from_timestamp and to_timestamp:
            sql += f" AND timestamp BETWEEN {from_timestamp} AND {to_timestamp}"
        
        result = self.database.select(sql)
        if result:
            return dict(result[0])
        return {"times_filled": 0, "unique_players": 0, "total_cost": 0}
    
    def morphine_usage(self, from_timestamp=None, to_timestamp=None):
        """Get morphine usage statistics"""
        sql = """
            SELECT 
                COUNT(*) as times_used,
                SUM(quantity) as total_quantity,
                COUNT(DISTINCT player_id) as unique_players,
                SUM(quantity * item_price) as total_cost
            FROM armoury_news
            WHERE item_name LIKE '%Morphine%' OR item_name LIKE '%morphine%'
        """
        
        if from_timestamp and to_timestamp:
            sql += f" AND timestamp BETWEEN {from_timestamp} AND {to_timestamp}"
        
        result = self.database.select(sql)
        if result:
            return dict(result[0])
        return {"times_used": 0, "total_quantity": 0, "unique_players": 0, "total_cost": 0}
    
    def all_costs_in_period(self, from_timestamp, to_timestamp):
        """Get breakdown of all costs during a timeframe"""
        costs = {}
        
        # By category
        for category in ["Medical", "Drug", "Consumable", "Utility", "Temporary", "Booster", "Weapon", "Armor"]:
            data = self.cost_by_category(category, from_timestamp, to_timestamp)
            if data["event_count"] > 0:
                costs[category] = data
        
        # By type
        for event_type in ["used", "deposited", "filled", "loaned", "received"]:
            data = self.cost_by_type(event_type, from_timestamp, to_timestamp)
            if data["event_count"] > 0:
                costs[f"type_{event_type}"] = data
        
        return costs

    def loan_timers(self, player_name=None, item_name=None, limit=50):
        """
        Build rough loan duration estimates from loaned/received armoury events.

        Matching logic is FIFO per (player_id, item_name):
        - loaned adds quantity to outstanding queue
        - received consumes oldest outstanding quantity
        """
        filters = ["event_type IN ('loaned', 'received')"]
        params = []

        if player_name:
            filters.append("LOWER(player_name) LIKE LOWER(?)")
            params.append(f"%{player_name}%")

        if item_name:
            filters.append("LOWER(item_name) LIKE LOWER(?)")
            params.append(f"%{item_name}%")

        where_clause = " AND ".join(filters)
        rows = self.database.select(
            f"""
            SELECT timestamp, player_id, player_name, item_name, quantity, event_type
            FROM armoury_news
            WHERE {where_clause}
            ORDER BY timestamp ASC
            """,
            tuple(params),
        )

        queues = defaultdict(deque)
        completed = defaultdict(lambda: {"seconds_total": 0, "qty_returned": 0})

        for row in rows:
            key = (row["player_id"], (row["item_name"] or "").lower())
            qty = int(row["quantity"] or 0)
            if qty <= 0:
                continue

            if row["event_type"] == "loaned":
                queues[key].append({
                    "timestamp": int(row["timestamp"] or 0),
                    "quantity": qty,
                    "player_name": row["player_name"],
                    "item_name": row["item_name"],
                })
            elif row["event_type"] == "received":
                remaining = qty
                while remaining > 0 and queues[key]:
                    oldest = queues[key][0]
                    consume = min(remaining, oldest["quantity"])
                    duration = max(0, int(row["timestamp"] or 0) - oldest["timestamp"])
                    completed[key]["seconds_total"] += duration * consume
                    completed[key]["qty_returned"] += consume

                    oldest["quantity"] -= consume
                    remaining -= consume
                    if oldest["quantity"] <= 0:
                        queues[key].popleft()

        outstanding = []
        now_rows = self.database.select("SELECT strftime('%s','now') AS now_ts")
        now_ts = int(now_rows[0]["now_ts"]) if now_rows else 0

        for key, pending in queues.items():
            stats = completed.get(key, {"seconds_total": 0, "qty_returned": 0})
            avg_seconds = 0
            if stats["qty_returned"] > 0:
                avg_seconds = int(stats["seconds_total"] / stats["qty_returned"])

            for loan in pending:
                age_seconds = max(0, now_ts - loan["timestamp"])
                eta_seconds = None
                if avg_seconds > 0:
                    eta_seconds = max(0, avg_seconds - age_seconds)

                outstanding.append({
                    "player_id": key[0],
                    "player_name": loan["player_name"],
                    "item_name": loan["item_name"],
                    "quantity_out": loan["quantity"],
                    "loaned_timestamp": loan["timestamp"],
                    "age_seconds": age_seconds,
                    "avg_return_seconds": avg_seconds,
                    "eta_seconds": eta_seconds,
                    "returned_samples_qty": stats["qty_returned"],
                })

        outstanding.sort(key=lambda x: (x["age_seconds"], x["quantity_out"]), reverse=True)
        return outstanding[:limit]
