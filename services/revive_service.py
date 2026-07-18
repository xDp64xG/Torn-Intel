"""
services/revive_service.py

Turns raw Torn revive data into parsed Revive objects.
"""

from modules.revives.parser import ReviveParser


class ReviveService:

    def __init__(self, gateway, logger):

        self.gateway = gateway
        self.logger = logger

    #######################################################

    def iter_pages(self, sort="DESC", from_timestamp=None, to_timestamp=None, limit=100):

        response = self.gateway.faction_revives(
            limit=limit,
            sort=sort,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )

        consecutive_empty_pages = 0

        while True:
            revives = self._parse_all(response)

            if not revives:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= 2:
                    break
                yield []
                continue

            consecutive_empty_pages = 0
            yield revives

            if sort == "DESC":
                oldest_timestamp = min(r.timestamp for r in revives)

                if from_timestamp is not None and oldest_timestamp < from_timestamp:
                    response = self.gateway.faction_revives(
                        limit=limit,
                        sort=sort,
                        from_timestamp=from_timestamp,
                        to_timestamp=oldest_timestamp - 1,
                    )
                    next_revives = self._parse_all(response)
                    if next_revives:
                        yield next_revives
                    break

                response = self.gateway.faction_revives(
                    limit=limit,
                    sort=sort,
                    from_timestamp=from_timestamp,
                    to_timestamp=oldest_timestamp - 1,
                )
            else:
                newest_timestamp = max(r.timestamp for r in revives)
                response = self.gateway.faction_revives(
                    limit=limit,
                    sort=sort,
                    from_timestamp=newest_timestamp + 1,
                )

    #######################################################

    def _parse_all(self, response):

        raw_revives = response.get("revives", {}) if isinstance(response, dict) else {}

        return [
            ReviveParser.parse({**payload, "id": int(revive_id)})
            for revive_id, payload in raw_revives.items()
        ]