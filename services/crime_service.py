"""
services/crime_service.py

Turns raw Torn OC crime payloads into parsed slot and CPR rows.
"""

from modules.crimes.parser import CrimeParser


class CrimeService:

    def __init__(self, gateway, logger):
        self.gateway = gateway
        self.logger = logger

    #######################################################

    def fetch_active_slots(self):

        response = self.gateway.faction_basic_crimes_members_v2(category="available,completed")
        item_names = self._get_item_name_map()
        member_names = {
            int(member["user_id"]): member["user_name"]
            for member in CrimeParser.parse_members(response)
        }

        # Fallback if combined endpoint is unavailable.
        if not isinstance(response, dict) or response.get("error"):
            response = self.gateway.faction_crimes_v2(category="available,completed")
            member_names = self._get_member_name_map()

        if not isinstance(response, dict):
            return []

        if response.get("error"):
            self.logger.error(f"Crime API error: {response['error']}")
            return []

        return CrimeParser.parse_slots(
            response,
            member_names=member_names,
            allowed_statuses={"recruiting", "planning"},
            item_names=item_names,
        )

    #######################################################

    def fetch_cpr_rows(self):

        slots = self.fetch_active_slots()

        return slots, CrimeParser.parse_cpr_rows(slots)

    #######################################################

    def fetch_roster_members(self):

        response = self.gateway.faction_basic_crimes_members_v2(category="available,completed")
        members = CrimeParser.parse_members(response)

        if members:
            return members

        # Fallback for keys that cannot access the combined v2 endpoint.
        response = self.gateway.faction_basic()
        return CrimeParser.parse_members(response)

    #######################################################

    def backfill_completed_slots(self, pages=50):
        """
        Walk completed crimes pages for historical CPR accumulation.
        """
        member_names = self._get_member_name_map()
        item_names = self._get_item_name_map()
        all_slots = []

        for page in range(max(1, int(pages or 1))):
            offset = page * 100
            response = self.gateway.faction_crimes_v2(
                category="completed",
                offset=offset,
                limit=100,
            )

            if not isinstance(response, dict) or response.get("error"):
                break

            page_slots = CrimeParser.parse_slots(
                response,
                member_names=member_names,
                allowed_statuses={"*"},
                item_names=item_names,
            )

            raw_crimes = response.get("crimes", [])
            raw_count = len(raw_crimes) if isinstance(raw_crimes, list) else len(raw_crimes or {})
            if raw_count == 0:
                break

            if page_slots:
                all_slots.extend(page_slots)

            if raw_count < 100:
                break

        return all_slots

    #######################################################

    def _get_member_name_map(self):

        return {
            int(member["user_id"]): member["user_name"]
            for member in self.fetch_roster_members()
        }

    #######################################################

    def _get_item_name_map(self):

        response = self.gateway.torn_items()
        if not isinstance(response, dict):
            return {}

        items = response.get("items", {})
        if not isinstance(items, dict):
            return {}

        mapping = {}
        for item_id, payload in items.items():
            if not isinstance(payload, dict):
                continue
            name = payload.get("name")
            if not name:
                continue
            try:
                mapping[int(item_id)] = name
            except Exception:
                mapping[str(item_id)] = name

        return mapping
