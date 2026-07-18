"""
gateways/armoury_gateway.py

Torn API access for armoury data, including armorynews and item market prices.
"""

import time
from services.http_client import RateLimitError


class ArmouryGateway:
    """Access faction armoury data from Torn API"""
    
    def __init__(self, http_client, key_manager=None, settings=None):
        """Initialize with HTTP client and optional key manager"""
        self.http = http_client
        self.key_manager = key_manager
        self.settings = settings
        self.faction_url = "https://api.torn.com/faction/"
        self.market_url = "https://api.torn.com/v2/market/"
        self.torn_url = "https://api.torn.com/torn/"
        self.torn_v2_url = "https://api.torn.com/v2/torn/"

    def get_torn_items(self):
        """Fetch Torn item catalogue (v1 torn/items) for name/type lookups."""
        params = {"selections": "items"}

        if self.key_manager:
            api_key = self.key_manager.get_next_key(skip_rate_limited=True)
        elif self.settings:
            api_key = self.settings.api_key
        else:
            api_key = None

        if api_key:
            params["key"] = api_key

        response = self.http.get(self.torn_url, params=params)
        if not response or "error" in response:
            return {}

        return response.get("items", {})
    
    def get_armoury_news(self, faction_id, limit=100, to_timestamp=None):
        """
        Fetch armoury news events for a faction.
        
        Args:
            faction_id: Faction ID
            limit: Max results per page (max 100)
            to_timestamp: Optional - fetch events up to this timestamp
        
        Returns:
            Dict mapping event_id to event data
        """
        base_params = {
            "selections": "armorynews",
            "limit": limit,
        }
        if to_timestamp:
            base_params["to"] = to_timestamp

        url = f"{self.faction_url}{faction_id}"

        attempts = 1
        if self.key_manager and getattr(self.key_manager, "api_keys", None):
            attempts = max(1, len(self.key_manager.api_keys))

        last_error = None

        for _ in range(attempts):
            params = dict(base_params)

            if self.key_manager:
                api_key = self.key_manager.get_next_key(skip_rate_limited=True)
            elif self.settings:
                api_key = self.settings.api_key
            else:
                api_key = None

            if api_key:
                params["key"] = api_key

            response = self.http.get(url, params=params)

            if not response:
                continue

            if "error" in response:
                error = response.get("error", {})
                code = error.get("code")
                last_error = error

                if code in (5, 14):
                    raise RateLimitError(f"Armoury API rate limit: {error}")

                # Permission/key issues: try the next key automatically.
                if code in (2, 6, 7, 10, 16):
                    continue

                # Any other API error: stop and return empty to caller.
                break

            armorynews = response.get("armorynews", {})
            if isinstance(armorynews, dict):
                return armorynews

        if last_error:
            # Keep this lightweight; caller can continue gracefully.
            print(f"Armoury API error: {last_error}")
        return {}
    
    def get_armoury_items(self, faction_id, category):
        """
        Get armoury items by category.
        
        Args:
            faction_id: Faction ID
            category: Item category (armor, boosters, drugs, temporary, utilities, weapons)
        
        Returns:
            Dict with item information
        """
        params = {
            "selections": category,
        }
        
        # Add API key
        if self.key_manager:
            api_key = self.key_manager.get_next_key(skip_rate_limited=True)
        elif self.settings:
            api_key = self.settings.api_key
        else:
            api_key = None
        
        if api_key:
            params["key"] = api_key
        
        url = f"{self.faction_url}{faction_id}"
        response = self.http.get(url, params=params)
        
        if not response:
            return {}
        
        return response.get(category, {})
    
    def get_item_market_price(self, item_id):
        """
        Get item market price from the v2 market/itemmarket endpoint.
        
        Args:
            item_id: Torn item ID
        
        Returns:
            Dict with item data including average_price, or the raw API error dict.
        """
        params = {
            "limit": 1,
            "offset": 0,
        }
        
        # Add API key
        if self.key_manager:
            api_key = self.key_manager.get_next_key(skip_rate_limited=True)
        elif self.settings:
            api_key = self.settings.api_key
        else:
            api_key = None
        
        if api_key:
            params["key"] = api_key
        
        url = f"{self.market_url}{item_id}/itemmarket"
        response = self.http.get(url, params=params)
        
        if not response:
            return None

        if "error" in response:
            return response

        if "itemmarket" not in response:
            return None
        
        itemmarket = response.get("itemmarket", {})
        if not itemmarket or "item" not in itemmarket:
            return None
        
        item = itemmarket["item"]
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "type": item.get("type"),
            "average_price": item.get("average_price", 0),
        }

    def get_item_value_market_price(self, item_id):
        """
        Get item market price from v2 torn/{id}/items using value.market_price.

        Args:
            item_id: Torn item ID

        Returns:
            Dict with item data including average_price (mapped from value.market_price),
            or raw API error dict.
        """
        params = {"sort": "ASC"}

        if self.key_manager:
            api_key = self.key_manager.get_next_key(skip_rate_limited=True)
        elif self.settings:
            api_key = self.settings.api_key
        else:
            api_key = None

        if api_key:
            params["key"] = api_key

        url = f"{self.torn_v2_url}{item_id}/items"
        response = self.http.get(url, params=params)

        if not response:
            return None

        if "error" in response:
            return response

        # The v2 payload shape can vary by rollout; normalize defensively.
        candidate = None

        items = response.get("items") if isinstance(response, dict) else None
        if isinstance(items, dict):
            candidate = items.get(str(item_id))
            if not isinstance(candidate, dict) and items:
                first = next(iter(items.values()))
                candidate = first if isinstance(first, dict) else None
        elif isinstance(items, list):
            for entry in items:
                if isinstance(entry, dict) and str(entry.get("id")) == str(item_id):
                    candidate = entry
                    break
            if candidate is None and items:
                first = items[0]
                candidate = first if isinstance(first, dict) else None

        if candidate is None and isinstance(response, dict):
            direct = response.get(str(item_id))
            if isinstance(direct, dict):
                candidate = direct

        if candidate is None and isinstance(response, dict):
            direct_item = response.get("item")
            if isinstance(direct_item, dict):
                candidate = direct_item

        if not isinstance(candidate, dict):
            return None

        value = candidate.get("value") if isinstance(candidate.get("value"), dict) else {}
        market_price = value.get("market_price")

        # Fallback if market price is exposed at item-level in some payloads.
        if market_price is None:
            market_price = candidate.get("market_price", 0)

        return {
            "id": candidate.get("id", item_id),
            "name": candidate.get("name"),
            "average_price": market_price or 0,
            "source": "torn_v2_torn_items_value",
        }
    
    def follow_pagination(self, url, params, limit=100):
        """
        Follow pagination links through armoury news.
        
        Args:
            url: API endpoint URL
            params: Query parameters
            limit: Yield limit
        
        Yields:
            Event records
        """
        # Add API key if not already present
        if "key" not in params:
            if self.key_manager:
                params["key"] = self.key_manager.get_next_key(skip_rate_limited=True)
            elif self.settings:
                params["key"] = self.settings.api_key
        
        next_url = url
        count = 0
        
        while next_url and count < limit:
            response = self.http.get(next_url, params=params)
            
            if not response or "armorynews" not in response:
                break
            
            events = response.get("armorynews", {})
            if not events:
                break
            
            for event_id, event in events.items():
                yield event_id, event
                count += 1
                if count >= limit:
                    break
            
            # Check for next page in metadata
            metadata = response.get("_metadata", {})
            links = metadata.get("links", {})
            next_url = links.get("next")
            
            if next_url:
                time.sleep(0.5)  # Rate limit friendly
    
    def page_by_timestamp(self, faction_id, from_timestamp=None, to_timestamp=None, limit=100):
        """
        Page through armoury news using timestamps as pagination anchors.
        
        Walks backward through time, yielding events. Each batch's oldest timestamp
        becomes the boundary for the next request.
        
        Args:
            faction_id: Faction ID
            from_timestamp: Earliest timestamp to fetch (inclusive)
            to_timestamp: Latest timestamp to fetch (exclusive, walks backward from here)
            limit: Max results per page
        
        Yields:
            Tuple of (event_id, event_data, timestamp)
        """
        current_to = to_timestamp  # Start from specified time or now
        
        while True:
            params = {
                "selections": "armorynews",
                "limit": limit,
            }
            if current_to:
                params["to"] = current_to
            
            # Add API key
            if self.key_manager:
                api_key = self.key_manager.get_next_key(skip_rate_limited=True)
            elif self.settings:
                api_key = self.settings.api_key
            else:
                api_key = None
            
            if api_key:
                params["key"] = api_key
            
            url = f"{self.faction_url}{faction_id}"
            response = self.http.get(url, params=params)
            
            if not response or "armorynews" not in response:
                break
            
            events = response.get("armorynews", {})
            if not events:
                break
            
            # Process all events in this batch
            event_list = []
            for event_id_str, event_data in events.items():
                event_ts = int(event_data.get("timestamp", 0) or 0)
                # Armoury event IDs are strings (UUIDs), not integers
                event_list.append((event_id_str, event_data, event_ts))
                yield event_id_str, event_data, event_ts
            
            # Sort by timestamp to find the oldest
            event_list.sort(key=lambda x: x[2])
            oldest_ts = event_list[0][2]  # Oldest timestamp in this batch
            
            # Stop if we've reached the lower bound
            if from_timestamp and oldest_ts <= from_timestamp:
                break
            
            # Use oldest timestamp (minus 1) for next page to avoid duplicates
            current_to = oldest_ts - 1
            
            if current_to <= 0:
                break
            
            time.sleep(0.5)  # Rate limit friendly
