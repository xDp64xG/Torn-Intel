"""
gateways/torn_gateway.py

Torn-specific API access, scoped by faction/user/etc.
Defaults to API v2; falls back to v1 automatically for
selections that v2 doesn't support yet.

Features:
- Automatic v1/v2 fallback
- Rate limit handling with key rotation
- Automatic retry with exponential backoff
- Multiple API key support
"""

from __future__ import annotations

import time


V1_ONLY_ERROR_CODE = 22


class TornGateway:

    def __init__(self, http, settings, logger, key_manager=None):

        self.http = http
        self.settings = settings
        self.logger = logger
        self.key_manager = key_manager

    #######################################################

    def _request(self, url, params):

        self.logger.info(f"GET {url}")

        response = self.http.get(
            url,
            params=params,
            max_retries=self.settings.max_retries,
            retry_backoff_base=self.settings.retry_backoff_base
        )

        time.sleep(self.settings.request_delay)

        return response

    #######################################################

    def _get_v2(self, scope, selection, resource_id=None, **params):

        segments = [self.settings.base_url, "v2", scope]

        if resource_id is not None:
            segments.append(str(resource_id))

        segments.append(selection)

        url = "/".join(segments)

        # Get the next available API key
        if self.key_manager:
            api_key = self.key_manager.get_next_key(skip_rate_limited=True)
        else:
            api_key = self.settings.api_key

        query = {
            "key": api_key,
            "comment": self.settings.comment,
        }
        query.update({k: v for k, v in params.items() if v is not None})

        return self._request(url, query)

    #######################################################

    def _get_v1(self, scope, selection, resource_id=None, **params):

        resource = f"{scope}/{resource_id}" if resource_id else scope

        url = f"{self.settings.base_url}/{resource}/"

        # Get the next available API key
        if self.key_manager:
            api_key = self.key_manager.get_next_key(skip_rate_limited=True)
        else:
            api_key = self.settings.api_key

        query = {
            "key": api_key,
            "comment": self.settings.comment,
            "selections": selection,
        }
        query.update({k: v for k, v in params.items() if v is not None})

        return self._request(url, query)

    #######################################################

    def _get(self, scope, selection, resource_id=None, **params):

        response = self._get_v2(scope, selection, resource_id, **params)

        if isinstance(response, dict) and response.get("error", {}).get("code") == V1_ONLY_ERROR_CODE:

            self.logger.warning(
                f"{scope}/{selection} is v1-only, falling back"
            )

            return self._get_v1(scope, selection, resource_id, **params)

        return response

    #######################################################
    # Faction-scoped endpoints
    #######################################################

    def faction_attacks(
        self,
        filters=None,
        limit=100,
        sort="DESC",
        from_timestamp=None,
        to_timestamp=None,
        timestamp=None,
    ):
        """
        Get faction attacks. Uses v1 API which supports the `to` parameter
        for walking backwards through historical data. v1 has better
        historical support than v2 for this endpoint.
        """

        return self._get_v1(
            "faction",
            "attacks",
            filters=filters,
            limit=limit,
            sort=sort,
            **{"from": from_timestamp, "to": to_timestamp},
            timestamp=timestamp,
        )

    def faction_revives(
        self,
        limit=100,
        sort="DESC",
        from_timestamp=None,
        to_timestamp=None,
        timestamp=None,
    ):
        """
        Get faction revives from v1 API with attacks-style timestamp pagination.
        """

        return self._get_v1(
            "faction",
            "revives",
            limit=limit,
            sort=sort,
            **{"from": from_timestamp, "to": to_timestamp},
            timestamp=timestamp,
        )

    #######################################################

    def faction_chains(self):

        return self._get_v1(
            "faction",
            "chains",
        )

    def faction_basic(self):

        return self._get_v1(
            "faction",
            "basic",
        )

    def torn_items(self):

        return self._get_v1(
            "torn",
            "items",
        )

    def faction_crimes_v2(self, category="available,completed", offset=0, limit=100):
        """
        Get faction OC 2.0 crimes with slot/item requirement data.

        Args:
            category: Torn crimes category filter, e.g. "available,completed"
        """

        return self._get_v2(
            "faction",
            "crimes",
            cat=category,
            offset=offset,
            limit=limit,
        )

    def faction_basic_crimes_members_v2(self, category="available,completed", offset=0, limit=100):
        """
        Combined v2 payload used by OC tooling scripts:
        faction/basic,crimes,members
        """

        return self._get_v2(
            "faction",
            "basic,crimes,members",
            cat=category,
            offset=offset,
            limit=limit,
            striptags="true",
        )

    def faction_rankedwars(self):
        """
        Get faction ranked wars metadata.
        Returns: {war_id: {factions: {...}, war: {start, end, target, winner}}}
        """

        return self._get_v1(
            "faction",
            "rankedwars",
        )
    
    def market_items(self):
        """
        Get all items with market pricing data.
        Uses v1 API which has market data endpoint.
        Returns: {item_id: {name, category, average_price, ...}}
        """
        
        # Try v1 market endpoint
        return self._get_v1(
            "market",
            "items",
        )
    
    def follow(self, url):

        return self._request(url, {"key": self.settings.api_key})