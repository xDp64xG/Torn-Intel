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

    def _request(self, url, params, pool="default"):

        self.logger.info(f"GET {url}")

        response = self.http.get(
            url,
            params=params,
            max_retries=self.settings.max_retries,
            retry_backoff_base=self.settings.retry_backoff_base,
            pool=pool,
        )

        time.sleep(self.settings.request_delay)

        return response

    #######################################################

    def _get_v2(self, scope, selection, resource_id=None, pool="default", **params):

        segments = [self.settings.base_url, "v2", scope]

        if resource_id is not None:
            segments.append(str(resource_id))

        segments.append(selection)

        url = "/".join(segments)

        # Get the next available API key for this pool
        if self.key_manager:
            api_key = self.key_manager.get_next_key(pool=pool, skip_rate_limited=True)
        else:
            api_key = self.settings.api_key

        query = {
            "key": api_key,
            "comment": self.settings.comment,
        }
        query.update({k: v for k, v in params.items() if v is not None})

        return self._request(url, query, pool=pool)

    #######################################################

    def _get_v1(self, scope, selection, resource_id=None, pool="default", **params):

        resource = f"{scope}/{resource_id}" if resource_id else scope

        url = f"{self.settings.base_url}/{resource}/"

        # Get the next available API key for this pool
        if self.key_manager:
            api_key = self.key_manager.get_next_key(pool=pool, skip_rate_limited=True)
        else:
            api_key = self.settings.api_key

        query = {
            "key": api_key,
            "comment": self.settings.comment,
            "selections": selection,
        }
        query.update({k: v for k, v in params.items() if v is not None})

        return self._request(url, query, pool=pool)

    #######################################################

    def _get(self, scope, selection, resource_id=None, pool="default", **params):

        response = self._get_v2(scope, selection, resource_id, pool=pool, **params)

        if isinstance(response, dict) and response.get("error", {}).get("code") == V1_ONLY_ERROR_CODE:

            self.logger.warning(
                f"{scope}/{selection} is v1-only, falling back"
            )

            return self._get_v1(scope, selection, resource_id, pool=pool, **params)

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
        pool="default",
    ):
        """
        Get faction attacks. Uses v1 API which supports the `to` parameter
        for walking backwards through historical data.
        """

        return self._get_v1(
            "faction",
            "attacks",
            pool=pool,
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
        pool="default",
    ):
        """
        Get faction revives from v1 API with attacks-style timestamp pagination.
        """

        return self._get_v1(
            "faction",
            "revives",
            pool=pool,
            limit=limit,
            sort=sort,
            **{"from": from_timestamp, "to": to_timestamp},
            timestamp=timestamp,
        )

    #######################################################

    def faction_chains(self, pool="default"):

        return self._get_v1(
            "faction",
            "chains",
            pool=pool,
        )

    def faction_chain(self, pool="default"):
        """Read the live chain timer, not the historical chains selection."""
        return self._get_v1("faction", "chain", pool=pool)

    def user_profile(self, user_id, pool="default"):
        return self._get_v1("user", "profile", resource_id=int(user_id), pool=pool)

    def faction_basic(self, pool="default"):

        return self._get_v1(
            "faction",
            "basic",
            pool=pool,
        )

    def faction_inventory(self, category, pool="default"):
        """Get one category of a faction's cached inventory, paginating if needed."""
        inventory = []
        first_response = None
        offset = 0

        while True:
            response = self._get_v2(
                "faction",
                "inventory",
                pool=pool,
                cat=category,
                limit=100,
                offset=offset,
            )
            if not isinstance(response, dict) or response.get("error"):
                return response
            if first_response is None:
                first_response = response
            page = response.get("inventory")
            if not isinstance(page, list):
                return response
            inventory.extend(page)
            metadata = response.get("_metadata") or {}
            try:
                total = int(metadata.get("total") or len(inventory))
            except (TypeError, ValueError):
                total = len(inventory)
            if len(inventory) >= total or len(page) < 100:
                break
            offset += len(page)

        first_response["inventory"] = inventory
        return first_response

    def faction_contributors(self, stat, pool="default"):
        """Get current faction members' contribution values for a stat."""
        return self._get(
            "faction",
            "contributors",
            pool=pool,
            stat=stat,
            cat="current",
        )

    def faction_balance(self, pool="default"):
        """Faction vault balances; the key owner needs faction API access."""

        return self._get_v2(
            "faction",
            "balance",
            pool=pool,
        )

    def faction_funds_news(self, pool="default"):
        """Faction vault transaction news (give-to-user, deposits)."""

        return self._get_v1(
            "faction",
            "fundsnews",
            pool=pool,
        )

    def user_discord(self, discord_id, pool="default"):
        """Look up a Torn user by Discord ID; only works if they linked Discord in Torn."""

        return self._get_v1(
            "user",
            "discord",
            resource_id=discord_id,
            pool=pool,
        )

    def torn_items(self, pool="GLOBAL"):

        return self._get_v1(
            "torn",
            "items",
            pool=pool,
        )

    def faction_crimes_v2(self, category="available,completed", offset=0, limit=100, pool="default"):
        """
        Get faction OC 2.0 crimes with slot/item requirement data.

        Args:
            category: Torn crimes category filter, e.g. "available,completed"
        """

        return self._get_v2(
            "faction",
            "crimes",
            pool=pool,
            cat=category,
            offset=offset,
            limit=limit,
        )

    def faction_basic_crimes_members_v2(self, category="available,completed", offset=0, limit=100, pool="default"):
        """
        Combined v2 payload used by OC tooling scripts:
        faction/basic,crimes,members
        """

        return self._get_v2(
            "faction",
            "basic,crimes,members",
            pool=pool,
            cat=category,
            offset=offset,
            limit=limit,
            striptags="true",
        )

    def faction_rankedwars(self, pool="default"):
        """
        Get faction ranked wars metadata.
        Returns: {war_id: {factions: {...}, war: {start, end, target, winner}}}
        """

        return self._get_v1(
            "faction",
            "rankedwars",
            pool=pool,
        )
    
    def market_items(self, pool="GLOBAL"):
        """
        Get all items with market pricing data.
        Uses v1 API which has market data endpoint.
        Returns: {item_id: {name, category, average_price, ...}}
        """
        
        # Try v1 market endpoint
        return self._get_v1(
            "market",
            "items",
            pool=pool,
        )
    
    def follow(self, url, pool="default"):

        key = self.key_manager.get_next_key(pool=pool, skip_rate_limited=True) if self.key_manager else self.settings.api_key
        return self._request(url, {"key": key}, pool=pool)