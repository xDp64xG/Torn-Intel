"""
modules/armoury/report.py

Generate reports on armoury usage and costs.
"""

from datetime import datetime

from utils.colors import header, info, divider, highlight, money, warning, success


class ArmouryReport:
    """Generate formatted armoury reports"""
    
    def __init__(self, queries, logger, database=None):
        """Initialize with queries and logger"""
        self.queries = queries
        self.logger = logger
        self.database = database
    
    def _get_price(self, event):
        """Get price for an event, checking item_prices table if available"""
        # First, check if database is available to look up from item_prices
        item_id = event.get("item_id") if hasattr(event, 'get') else event["item_id"]
        if self.database and item_id:
            try:
                self.database.execute(
                    "SELECT market_average, manual_override FROM item_prices WHERE item_id = ?",
                    (item_id,)
                )
                row = self.database.fetchone()
                if row:
                    # Return manual override if set, otherwise market average
                    return row["manual_override"] if row["manual_override"] else row["market_average"]
            except:
                pass
        
        # Fall back to item_price from event
        item_price = event.get("item_price") if hasattr(event, 'get') else event["item_price"]
        return item_price or 0
    
    def player_usage(self, player_name):
        """Report for a player's armoury usage"""
        results = self.queries.search(player_name=player_name, limit=1000)
        
        report = []
        report.append(f"\n{header(f'Player Armoury Usage: {player_name}')}")
        report.append(f"Total Events: {info(str(len(results)))}\n")
        
        if not results:
            report.append(warning("No armoury activity found"))
            return "\n".join(report)
        
        total_cost = 0
        category_totals = {}
        event_type_totals = {}
        
        # Header
        report.append(f"{'Type':<10} {'Item':<25} {'Qty':>4} {'Price':>10} {'Total':>12}")
        report.append(divider(65))
        
        for event in results:
            event_type = event["event_type"] or "?"
            item_name = (event["item_name"] or "?")[:24]
            qty = event["quantity"] or 0
            price = self._get_price(event)
            cost = qty * price
            
            total_cost += cost
            category = event["item_category"] or "Unknown"
            
            if category not in category_totals:
                category_totals[category] = 0
            category_totals[category] += cost
            
            if event_type not in event_type_totals:
                event_type_totals[event_type] = 0
            event_type_totals[event_type] += cost
            
            price_str = f"{price:,.0f}" if price else "0"
            cost_str = f"{cost:,.0f}" if cost else "0"
            report.append(f"{event_type:<10} {item_name:<25} {qty:>4} {price_str:>10} {cost_str:>12}")
        
        report.append(divider(65))
        report.append(f"\n{highlight('By Category:')}")
        for category, cost in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
            cost_str = f"{cost:,.0f}" if cost else "0"
            report.append(f"  {category:<20} {cost_str:>15}")
        
        report.append(f"\n{highlight('By Event Type:')}")
        for event_type, cost in sorted(event_type_totals.items(), key=lambda x: x[1], reverse=True):
            cost_str = f"{cost:,.0f}" if cost else "0"
            report.append(f"  {event_type:<20} {cost_str:>15}")
        
        report.append(divider(65))
        report.append(f"{highlight('Total Cost:')} {money(total_cost)}\n")
        
        return "\n".join(report)
    
    def category(self, item_category):
        """Report for item category usage"""
        results = self.queries.search(category=item_category, limit=1000)
        
        report = []
        report.append(f"\n{header(f'{item_category} Items Report')}")
        report.append(f"Total Events: {info(str(len(results)))}\n")
        
        if not results:
            report.append(warning("No items in this category found"))
            return "\n".join(report)
        
        # Group by item
        items = {}
        total_cost = 0
        
        for event in results:
            item = event["item_name"] or "?"
            if item not in items:
                items[item] = {"count": 0, "quantity": 0, "cost": 0, "players": set()}
            
            qty = event["quantity"] or 0
            price = self._get_price(event)
            cost = qty * price
            
            items[item]["count"] += 1
            items[item]["quantity"] += qty
            items[item]["cost"] += cost
            items[item]["players"].add(event["player_name"] or "?")
            total_cost += cost
        
        # Sort by cost and display
        report.append(f"{'Item':<25} {'Qty':>6} {'Players':>8} {'Events':>6} {'Total Cost':>15}")
        report.append(divider(70))
        
        for item_name in sorted(items.keys(), key=lambda x: items[x]["cost"], reverse=True):
            data = items[item_name]
            qty = data['quantity']
            players = len(data['players'])
            events = data['count']
            cost_str = f"{data['cost']:,.0f}" if data['cost'] else "0"
            report.append(f"{item_name:<25} {qty:>6} {players:>8} {events:>6} {cost_str:>15}")
        
        report.append(divider(70))
        report.append(f"{highlight('Total Cost:')} {money(total_cost)}\n")
        
        return "\n".join(report)
    
    def medical_summary(self):
        """Generate medical items summary"""
        medical_results = self.queries.search(category="Medical", limit=5000)
        
        report = []
        report.append(f"\n{header('Medical Items Summary')}")
        
        if not medical_results:
            report.append(warning("No medical item activity found"))
            return "\n".join(report)
        
        # Analyze medical items
        xanax_used = 0
        morphine_used = 0
        blood_bags_filled = 0
        total_cost = 0
        
        for event in medical_results:
            item_name = (event["item_name"] or "").lower()
            qty = event["quantity"] or 0
            event_type = (event["event_type"] or "").lower()
            price = self._get_price(event)
            cost = qty * price
            total_cost += cost
            
            if "xanax" in item_name and event_type == "used":
                xanax_used += qty
            elif "morphine" in item_name and event_type == "used":
                morphine_used += qty
            elif "blood" in item_name and event_type == "filled":
                blood_bags_filled += qty
        
        report.append(f"{'Item':<20} {'Usage':>12} {'Status':>15}")
        report.append(divider(50))
        report.append(f"{'Xanax Used':<20} {xanax_used:>12}")
        report.append(f"{'Morphine Used':<20} {morphine_used:>12}")
        report.append(f"{'Blood Bags Filled':<20} {blood_bags_filled:>12}")
        report.append(divider(50))
        report.append(f"{highlight('Total Medical Cost:')} {money(total_cost)}\n")
        
        return "\n".join(report)

    def war_costs(self, war_id, stacking_days=0, temp_return_days=2):
        """Report armoury costs during a ranked war window."""
        return self._period_cost_report(
            title=f"War Armoury Costs - War {war_id}",
            lookup_sql="SELECT war_start, war_end FROM rankedwars WHERE war_id = ?",
            lookup_args=(war_id,),
            stacking_days=stacking_days,
            temp_return_days=temp_return_days,
        )

    def chain_costs(self, chain_id, stacking_days=0, temp_return_days=2):
        """Report armoury costs during a chain window."""
        return self._period_cost_report(
            title=f"Chain Armoury Costs - Chain {chain_id}",
            lookup_sql="SELECT timestamp_start, timestamp_end FROM chains WHERE chain_id = ?",
            lookup_args=(chain_id,),
            stacking_days=stacking_days,
            temp_return_days=temp_return_days,
        )

    def loan_tracker(self, player_name=None, item_name=None, limit=50):
        """Show currently outstanding loans with rough return-time estimates."""
        rows = self.queries.loan_timers(player_name=player_name, item_name=item_name, limit=limit)

        title = "Outstanding Armoury Loans"
        if player_name:
            title += f" - {player_name}"
        if item_name:
            title += f" - item:{item_name}"

        report = []
        report.append(f"\n{header(title)}")
        report.append(f"Open Loans: {info(str(len(rows)))}")

        if not rows:
            report.append(warning("No outstanding loaned items found"))
            return "\n".join(report)

        report.append(
            f"{'Player':<18} {'Item':<28} {'Qty':>4} {'Loaned At':<16} {'Age':>10} {'Avg Return':>12} {'ETA':>12}"
        )
        report.append(divider(112))

        for row in rows:
            loaned_at = datetime.fromtimestamp(row["loaned_timestamp"]).strftime("%m-%d %H:%M")
            age_h = row["age_seconds"] / 3600 if row["age_seconds"] else 0
            avg_h = row["avg_return_seconds"] / 3600 if row["avg_return_seconds"] else 0

            if row["eta_seconds"] is None:
                eta_str = "n/a"
            else:
                eta_h = row["eta_seconds"] / 3600
                eta_str = f"{eta_h:,.1f}h"

            avg_str = f"{avg_h:,.1f}h" if avg_h > 0 else "n/a"

            report.append(
                f"{(row['player_name'] or '?')[:17]:<18} {(row['item_name'] or '?')[:27]:<28} "
                f"{row['quantity_out']:>4} {loaned_at:<16} {age_h:>9.1f}h {avg_str:>12} {eta_str:>12}"
            )

        report.append(divider(112))
        report.append("ETA is a rough estimate from historical loaned->received timings per player+item.")
        return "\n".join(report)

    def _period_cost_report(self, title, lookup_sql, lookup_args, stacking_days=0, temp_return_days=2):
        """Build a cost report for a timestamp-bounded event window."""
        rows = self.database.select(lookup_sql, lookup_args) if self.database else []
        if not rows:
            return warning("No matching war or chain window found")

        row = rows[0]
        row_keys = set(row.keys())
        from_timestamp = row["war_start"] if "war_start" in row_keys else row["timestamp_start"]
        to_timestamp = row["war_end"] if "war_end" in row_keys else row["timestamp_end"]

        if from_timestamp is None or to_timestamp is None:
            return warning("Selected war or chain does not have a usable timestamp window")

        stacking_days = max(0, int(stacking_days or 0))
        temp_return_days = max(0, int(temp_return_days or 0))
        stacking_start = from_timestamp - (stacking_days * 86400)
        return_cutoff = to_timestamp + (temp_return_days * 86400)

        totals = self.database.select(
            """
            SELECT COUNT(*) as event_count,
                     COUNT(DISTINCT n.item_id) as item_count,
                   SUM(n.quantity * COALESCE(p.manual_override, p.market_average, n.item_price, 0)) as total_cost
            FROM armoury_news n
            LEFT JOIN item_prices p ON p.item_id = n.item_id
            WHERE n.timestamp BETWEEN ? AND ?
            """,
            (from_timestamp, to_timestamp),
        )
        totals_row = totals[0] if totals else {"event_count": 0, "item_count": 0, "total_cost": 0}

        category_rows = []
        category_map = {}
        for category in ["Medical", "Drug", "Consumable", "Utility", "Temporary", "Booster", "Weapon", "Armor", "Unknown"]:
            data = self.queries.cost_by_category(category, from_timestamp, to_timestamp)
            if data and (data.get("event_count", 0) > 0 or category == "Temporary"):
                category_rows.append((category, data))
            category_map[category] = data

        # Recompute Temporary via robust matcher so temp-like items are included
        # even if historical rows were categorized inconsistently.
        temp_scope = self._temporary_scope_totals(from_timestamp, to_timestamp)
        category_map["Temporary"] = temp_scope
        category_rows = [(c, d) for (c, d) in category_rows if c != "Temporary"]
        category_rows.append(("Temporary", temp_scope))

        type_rows = []
        for event_type in ["used", "filled", "deposited", "loaned", "received"]:
            data = self.queries.cost_by_type(event_type, from_timestamp, to_timestamp)
            if data and data.get("event_count", 0) > 0:
                type_rows.append((event_type, data))

        xanax_stack = {"events": 0, "quantity": 0, "cost": 0}
        if stacking_days > 0:
            stack_rows = self.database.select(
                """
                SELECT
                    COUNT(*) AS events,
                    SUM(COALESCE(n.quantity, 0)) AS quantity,
                    SUM(COALESCE(n.quantity, 0) * COALESCE(p.manual_override, p.market_average, n.item_price, 0)) AS cost
                FROM armoury_news n
                LEFT JOIN item_prices p ON p.item_id = n.item_id
                WHERE
                    n.timestamp >= ?
                    AND n.timestamp < ?
                    AND LOWER(n.event_type) = 'used'
                    AND LOWER(n.item_name) LIKE '%xanax%'
                """,
                (stacking_start, from_timestamp),
            )
            if stack_rows:
                row_data = stack_rows[0]
                xanax_stack = {
                    "events": int(row_data["events"] or 0),
                    "quantity": int(row_data["quantity"] or 0),
                    "cost": float(row_data["cost"] or 0),
                }

        temp_reconcile = self._temporary_reconciliation(from_timestamp, to_timestamp, return_cutoff)
        temp_raw_cost = float((category_map.get("Temporary", {}) or {}).get("total_cost") or 0)
        adjusted_total = (totals_row["total_cost"] or 0) + xanax_stack["cost"] - temp_raw_cost + temp_reconcile["estimated_cost"]

        report = []
        report.append(f"\n{header(title)}")
        report.append(
            f"Window: {datetime.fromtimestamp(from_timestamp).strftime('%Y-%m-%d %H:%M:%S')} "
            f"to {datetime.fromtimestamp(to_timestamp).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        if stacking_days > 0:
            report.append(
                f"Stacking Window (Xanax): {datetime.fromtimestamp(stacking_start).strftime('%Y-%m-%d %H:%M:%S')} "
                f"to {datetime.fromtimestamp(from_timestamp).strftime('%Y-%m-%d %H:%M:%S')} ({stacking_days} day(s))"
            )
        report.append(
            f"Temporary Return Window: {datetime.fromtimestamp(to_timestamp).strftime('%Y-%m-%d %H:%M:%S')} "
            f"to {datetime.fromtimestamp(return_cutoff).strftime('%Y-%m-%d %H:%M:%S')} ({temp_return_days} day(s))"
        )
        report.append(
            f"Events: {info(str(totals_row['event_count']))}  "
            f"Items: {info(str(totals_row['item_count']))}  "
            f"Total Cost: {money(totals_row['total_cost'] or 0)}"
        )

        if not category_rows and not type_rows:
            report.append(warning("No armoury activity found in the selected period"))
            return "\n".join(report)

        if category_rows:
            report.append(f"\n{highlight('By Category:')}")
            report.append(f"{'Category':<16} {'Events':>8} {'Items':>8} {'Players':>8} {'Cost':>15}")
            report.append(divider(60))
            for category, data in sorted(category_rows, key=lambda row: row[1].get("total_cost", 0) or 0, reverse=True):
                report.append(
                    f"{category:<16} {data.get('event_count', 0):>8} {data.get('item_count', 0):>8} "
                    f"{data.get('player_count', 0):>8} {money(data.get('total_cost', 0) or 0):>15}"
                )

        if type_rows:
            report.append(f"\n{highlight('By Event Type:')}")
            report.append(f"{'Type':<16} {'Events':>8} {'Players':>8} {'Cost':>15}")
            report.append(divider(52))
            for event_type, data in sorted(type_rows, key=lambda row: row[1].get("total_cost", 0) or 0, reverse=True):
                report.append(
                    f"{event_type:<16} {data.get('event_count', 0):>8} {data.get('player_count', 0):>8} "
                    f"{money(data.get('total_cost', 0) or 0):>15}"
                )

        if stacking_days > 0:
            report.append(f"\n{highlight('Stacking Phase (Xanax Used Before Window):')}")
            report.append(
                f"Events: {xanax_stack['events']}  Quantity: {xanax_stack['quantity']}  "
                f"Cost Added: {money(xanax_stack['cost'])}"
            )

        report.append(f"\n{highlight('Temporary Reconciliation (Loaned vs Returned):')}")
        if temp_reconcile["rows"]:
            report.append(f"{'Item':<28} {'Loaned':>8} {'Returned':>10} {'Net Used':>9} {'Est. Cost':>14}")
            report.append(divider(74))
            for rec in temp_reconcile["rows"]:
                report.append(
                    f"{(rec['item_name'] or '?')[:27]:<28} {rec['loaned_qty']:>8} {rec['returned_qty']:>10} "
                    f"{rec['net_used_qty']:>9} {money(rec['estimated_cost']):>14}"
                )
            report.append(divider(74))
        else:
            report.append(warning("No temporary loan/return activity found for reconciliation in this window"))

        report.append(
            f"Estimated Temporary Cost (net used): {money(temp_reconcile['estimated_cost'])}"
        )
        report.append(
            f"Estimated Temporary Stock Delta (before->after): "
            f"{temp_reconcile['stock_before']} -> {temp_reconcile['stock_after']} "
            f"(used/consumed est: {temp_reconcile['stock_delta_used']})"
        )
        report.append(
            "Adjusted Total = Window Total + Xanax Stacking - Raw Temporary Cost + Reconciled Temporary Cost"
        )
        report.append(f"{highlight('Adjusted Total Cost:')} {money(adjusted_total)}")

        report.append(f"\n{highlight('Total Cost:')} {money(totals_row['total_cost'] or 0)}\n")
        return "\n".join(report)

    def _temporary_where_clause(self, alias="n"):
        """SQL condition for temporary-category or temporary-like item names."""
        prefix = f"{alias}." if alias else ""
        return (
            f"(LOWER({prefix}item_category) = 'temporary' "
            f"OR LOWER({prefix}item_name) LIKE '%heg%' "
            f"OR LOWER({prefix}item_name) LIKE '%flash grenade%' "
            f"OR LOWER({prefix}item_name) LIKE '%smoke grenade%' "
            f"OR LOWER({prefix}item_name) LIKE '%grenade%' "
            f"OR LOWER({prefix}item_name) LIKE '%pepper spray%' "
            f"OR LOWER({prefix}item_name) LIKE '%tear gas%' "
            f"OR LOWER({prefix}item_name) LIKE '%molotov%' "
            f"OR LOWER({prefix}item_name) LIKE '%claymore mine%')"
        )

    def _temporary_scope_totals(self, from_timestamp, to_timestamp):
        """Totals for Temporary-like activity in the selected window."""
        rows = self.database.select(
            f"""
            SELECT
                COUNT(*) AS event_count,
                COUNT(DISTINCT n.item_id) AS item_count,
                COUNT(DISTINCT n.player_id) AS player_count,
                SUM(COALESCE(n.quantity, 0) * COALESCE(p.manual_override, p.market_average, n.item_price, 0)) AS total_cost
            FROM armoury_news n
            LEFT JOIN item_prices p ON p.item_id = n.item_id
            WHERE n.timestamp BETWEEN ? AND ?
              AND {self._temporary_where_clause()}
            """,
            (from_timestamp, to_timestamp),
        )
        if not rows:
            return {"event_count": 0, "item_count": 0, "player_count": 0, "total_cost": 0}
        row = rows[0]
        return {
            "event_count": int(row["event_count"] or 0),
            "item_count": int(row["item_count"] or 0),
            "player_count": int(row["player_count"] or 0),
            "total_cost": float(row["total_cost"] or 0),
        }

    def _temporary_reconciliation(self, from_timestamp, to_timestamp, return_cutoff):
        """Estimate temporary usage from loan/return flow plus stock delta fallback."""
        temp_where = self._temporary_where_clause(alias="n")
        loaned_rows = self.database.select(
            f"""
            SELECT
                n.item_id,
                MAX(n.item_name) AS item_name,
                SUM(COALESCE(n.quantity, 0)) AS qty,
                MAX(COALESCE(p.manual_override, p.market_average, n.item_price, 0)) AS unit_price
            FROM armoury_news n
            LEFT JOIN item_prices p ON p.item_id = n.item_id
            WHERE
                n.timestamp BETWEEN ? AND ?
                AND {temp_where}
                AND LOWER(n.event_type) = 'loaned'
            GROUP BY n.item_id
            """,
            (from_timestamp, to_timestamp),
        )

        returned_rows = self.database.select(
            f"""
            SELECT
                n.item_id,
                SUM(COALESCE(n.quantity, 0)) AS qty
            FROM armoury_news n
            WHERE
                n.timestamp > ?
                AND n.timestamp <= ?
                AND {temp_where}
                AND LOWER(n.event_type) IN ('received', 'deposited')
            GROUP BY n.item_id
            """,
            (to_timestamp, return_cutoff),
        )

        returned_by_item = {
            int(r["item_id"]): int(r["qty"] or 0)
            for r in returned_rows
            if r["item_id"] is not None
        }

        rows = []
        estimated_cost = 0.0
        for loan in loaned_rows:
            item_id = int(loan["item_id"])
            loaned_qty = int(loan["qty"] or 0)
            returned_qty = int(returned_by_item.get(item_id, 0))
            net_used_qty = max(loaned_qty - returned_qty, 0)
            unit_price = float(loan["unit_price"] or 0)
            net_cost = net_used_qty * unit_price
            estimated_cost += net_cost

            rows.append(
                {
                    "item_id": item_id,
                    "item_name": loan["item_name"] or f"Item {item_id}",
                    "loaned_qty": loaned_qty,
                    "returned_qty": returned_qty,
                    "net_used_qty": net_used_qty,
                    "estimated_cost": net_cost,
                }
            )

        rows.sort(key=lambda r: r["estimated_cost"], reverse=True)

        stock_before = self._temporary_stock_as_of(max(0, from_timestamp - 1))
        stock_after = self._temporary_stock_as_of(return_cutoff)
        stock_delta_used = max(stock_before - stock_after, 0)

        return {
            "rows": rows,
            "estimated_cost": estimated_cost,
            "stock_before": stock_before,
            "stock_after": stock_after,
            "stock_delta_used": stock_delta_used,
        }

    def _temporary_stock_as_of(self, timestamp):
        """Estimate temporary stock level from historical event flow up to timestamp."""
        temp_where = self._temporary_where_clause(alias="")
        rows = self.database.select(
            f"""
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN LOWER(event_type) IN ('deposited', 'received') THEN COALESCE(quantity, 0)
                        WHEN LOWER(event_type) IN ('used', 'loaned') THEN -COALESCE(quantity, 0)
                        ELSE 0
                    END
                ), 0) AS stock
            FROM armoury_news
            WHERE
                timestamp <= ?
                AND {temp_where}
            """,
            (timestamp,),
        )
        if not rows:
            return 0
        return int(rows[0]["stock"] or 0)
