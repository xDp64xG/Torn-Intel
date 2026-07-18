"""
services/armoury_service.py

Turns raw Torn armoury news data into parsed ArmouryNews objects.
Handles pagination through the complete event history.
No database logic lives here.
"""

from modules.armoury.parser import ArmouryParser


class ArmouryService:

    def __init__(self, gateway, logger):

        self.gateway = gateway
        self.logger = logger
        self._api_item_lookup = None

    def _get_api_item_lookup(self):
        """Load and cache Torn item metadata for fallback categorization."""
        if self._api_item_lookup is not None:
            return self._api_item_lookup

        items = self.gateway.get_torn_items()
        if not items:
            self._api_item_lookup = {}
            self.logger.warning("Torn item catalogue unavailable; using parser-only item classification")
            return self._api_item_lookup

        lookup = {}
        for item_id, info in items.items():
            name = info.get("name", "")
            if not name:
                continue
            lookup[name.lower()] = {
                "item_id": int(item_id),
                "item_type": info.get("type", "Unknown"),
            }

        self._api_item_lookup = lookup
        self.logger.info(f"Loaded {len(lookup)} Torn items for armoury classification fallback")
        return self._api_item_lookup

    def _apply_api_item_fallback(self, parsed_event):
        """Fill unknown category/item_id from Torn item type metadata when possible."""
        if parsed_event.get("item_id", 0) > 0 and parsed_event.get("item_category") != "Unknown":
            return parsed_event

        lookup = self._get_api_item_lookup()
        item_name = (parsed_event.get("item_name") or "").lower()
        api_info = lookup.get(item_name)
        if not api_info:
            return parsed_event

        if parsed_event.get("item_id", 0) == 0:
            parsed_event["item_id"] = api_info["item_id"]

        if parsed_event.get("item_category") == "Unknown":
            api_category = ArmouryParser.get_category_from_api_type(api_info.get("item_type"))
            if api_category != "Unknown":
                parsed_event["item_category"] = api_category

        return parsed_event

    #######################################################

    def iter_pages(
        self,
        faction_id,
        filters=None,
        sort="DESC",
        from_timestamp=None,
        to_timestamp=None,
    ):
        """
        Yields one list of parsed ArmouryNews objects per page.
        Walks backward through armoury history using timestamp-based pagination.
        
        For DESC (backfill):
        - Starts at to_timestamp (or now if not specified)
        - Each page's oldest timestamp becomes the next request's boundary
        - Continues until reaching from_timestamp lower bound
        - Ensures complete coverage without gaps or duplicates
        
        For ASC (live, currently unused but supported for consistency with attacks):
        - Would walk forward from from_timestamp
        - Currently falls back to DESC behavior (Torn API only supports backward)
        
        Args:
            faction_id: Faction ID
            filters: Query filters (unused for now, for API consistency)
            sort: "DESC" for backfill, "ASC" for live (Torn API only supports backward)
            from_timestamp: Lower bound (stop walking backward here)
            to_timestamp: Upper bound (start walking backward from here)
        
        Yields:
            List of parsed ArmouryNews objects
        """

        current_to = to_timestamp
        consecutive_empty_pages = 0

        while True:

            # Fetch one page
            response = self.gateway.get_armoury_news(
                faction_id,
                limit=100,
                to_timestamp=current_to,
            )

            if not response:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= 2:
                    # Two consecutive empty pages means we've exhausted
                    break
                yield []
                continue

            consecutive_empty_pages = 0

            # Parse all events in this page
            parsed_events = []
            event_timestamps = []

            for event_id_str, event_data in response.items():
                # Armoury event IDs are strings (UUIDs), not integers
                event_id = event_id_str
                event_ts = int(event_data.get("timestamp", 0) or 0)
                
                parsed = ArmouryParser.parse(event_id, event_data)
                if parsed:
                    parsed = self._apply_api_item_fallback(parsed)
                    parsed_events.append(parsed)
                    event_timestamps.append(event_ts)

            if not parsed_events:
                yield []
                continue

            yield parsed_events

            # Find oldest timestamp in this batch
            oldest_ts = min(event_timestamps)

            # If from_timestamp was specified and we've gone past it, we're done
            if from_timestamp is not None and oldest_ts <= from_timestamp:
                self.logger.info(
                    f"Reached from_timestamp boundary ({from_timestamp}), "
                    f"oldest event was {oldest_ts}, stopping pagination"
                )
                break

            # Use oldest timestamp (minus 1) for next page
            current_to = oldest_ts - 1

            if current_to <= 0:
                break
