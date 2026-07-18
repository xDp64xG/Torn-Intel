"""
services/attack_service.py

Turns raw Torn attack data into parsed Attack objects.
No database or HTTP logic lives here.
"""

from modules.attacks.parser import AttackParser


class AttackService:

    def __init__(self, gateway, logger):

        self.gateway = gateway
        self.logger = logger

    #######################################################

    def latest(self, filters=None):

        response = self.gateway.faction_attacks(filters=filters)

        return self._parse_all(response)

    #######################################################

    def iter_pages(
        self,
        filters=None,
        sort="DESC",
        from_timestamp=None,
        to_timestamp=None,
    ):
        """
        Yields one list of parsed Attack objects per page.
        Handles both v1 and v2 API formats with proper pagination.
        
        For v1 (dict-based responses):
        - sort="DESC" walks backward from to_timestamp (or now if not specified)
        - Continues fetching pages until reaching from_timestamp lower bound
        - Each page walks backward in time, ensuring complete coverage
        - Stops only when oldest attack is significantly below from_timestamp
        
        For v2 (list-based responses with _metadata.links.next):
        - Uses cursor-based pagination from Torn's _metadata.links.next
        """

        response = self.gateway.faction_attacks(
            filters=filters,
            sort=sort,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )

        consecutive_empty_pages = 0

        while True:

            attacks = self._parse_all(response)

            if not attacks:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= 2:
                    # Two consecutive empty pages means we've exhausted the data
                    break
                yield []
                continue

            consecutive_empty_pages = 0
            yield attacks

            # Check if this is v1 response (dict) or v2 (list with metadata)
            raw_attacks = response.get("attacks", [])
            is_v1 = isinstance(raw_attacks, dict)

            if is_v1 and attacks and sort == "DESC":
                # V1 pagination: walk backward using `to` parameter
                oldest_timestamp = min(a.timestamp_started for a in attacks)
                
                # If from_timestamp was specified and we've gone past it,
                # we've covered the range and can safely stop
                if from_timestamp is not None and oldest_timestamp < from_timestamp:
                    # Continue one more fetch to ensure we get any edge cases
                    # but after that, stop for sure
                    response = self.gateway.faction_attacks(
                        filters=filters,
                        sort=sort,
                        from_timestamp=from_timestamp,
                        to_timestamp=oldest_timestamp - 1,
                    )
                    next_attacks = self._parse_all(response)
                    if next_attacks:
                        # Yield the final partial page
                        yield next_attacks
                    # Now break
                    break

                # Fetch next page going backward
                response = self.gateway.faction_attacks(
                    filters=filters,
                    sort=sort,
                    from_timestamp=from_timestamp,
                    to_timestamp=oldest_timestamp - 1,  # One second before oldest
                )

            else:
                # V2 pagination: use cursor-based links
                next_url = (
                    response
                    .get("_metadata", {})
                    .get("links", {})
                    .get("next")
                )

                if not next_url:
                    break

                response = self.gateway.follow(next_url)

    #######################################################

    def _parse_all(self, response):

        raw_attacks = response.get("attacks", [])

        # Handle both v1 (dict keyed by ID) and v2 (list) formats
        if isinstance(raw_attacks, dict):
            # V1: attacks are keyed by ID, need to pass ID to parser
            return [
                AttackParser.parse({**attack, "id": int(attack_id)})
                for attack_id, attack in raw_attacks.items()
            ]
        else:
            # V2: attacks are in a list, ID is already in each attack
            return [
                AttackParser.parse(attack)
                for attack in raw_attacks
            ]