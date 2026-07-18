"""
modules/crimes/sync.py

Sync active OC 2.0 slots and CPR data.
"""

from core.sync import BaseSync
from core.schema import SchemaBuilder
from models.crime_slot import CrimeSlot, CrimeCprStat, CrimeMember, CrimeSlotHistory
from repositories.crime_slot_repository import CrimeSlotRepository
from modules.crimes.parser import CrimeParser


class CrimeSync(BaseSync):

    name = "Crimes"

    def __init__(self, services):

        super().__init__(services)

        self.crimes = services.crimes
        self.repo = CrimeSlotRepository(services.database)

        schema = SchemaBuilder(services.database, services.logger)
        if not services.database.table_exists(CrimeSlot.table_name):
            schema.create(CrimeSlot)
        if not services.database.table_exists(CrimeCprStat.table_name):
            schema.create(CrimeCprStat)
        if not services.database.table_exists(CrimeMember.table_name):
            schema.create(CrimeMember)
        if not services.database.table_exists(CrimeSlotHistory.table_name):
            schema.create(CrimeSlotHistory)

        self._ensure_member_columns()

    #######################################################

    def sync(self, mode="backfill", filters=None, **kwargs):

        if mode == "live":
            return self._sync_snapshot()

        if mode == "backfill":
            pages = kwargs.get("pages", 50)
            return self._backfill(pages=pages)

        raise ValueError(
            f"Unknown sync mode for crimes: '{mode}'"
        )

    #######################################################

    def _sync_snapshot(self):

        members = self.crimes.fetch_roster_members()
        slots, cpr_rows = self.crimes.fetch_cpr_rows()

        self.repo.replace_members(members)
        self.repo.replace_active_slots(slots)
        self.repo.insert_history_slots(slots)
        self.repo.upsert_cpr_stats(cpr_rows)

        self.logger.info(
            f"Crimes snapshot synced: {len(members)} members, {len(slots)} active slots, {len(cpr_rows)} CPR rows"
        )

        return len(slots)

    #######################################################

    def _backfill(self, pages=50):

        members = self.crimes.fetch_roster_members()
        active_slots = self.crimes.fetch_active_slots()
        completed_slots = self.crimes.backfill_completed_slots(pages=pages)

        all_cpr_rows = CrimeParser.parse_cpr_rows(active_slots)
        completed_cpr_rows = CrimeParser.parse_cpr_rows(completed_slots)
        all_cpr_rows.extend(completed_cpr_rows)

        self.repo.replace_members(members)
        self.repo.replace_active_slots(active_slots)
        self.repo.insert_history_slots(active_slots)
        self.repo.insert_history_slots(completed_slots)
        self.repo.upsert_cpr_stats(all_cpr_rows)

        self.logger.info(
            "Crimes backfill synced: "
            f"{len(members)} members, {len(active_slots)} active slots, "
            f"{len(completed_slots)} completed slots scanned, {len(all_cpr_rows)} CPR rows upserted"
        )

        return len(completed_slots)

    #######################################################

    def _ensure_member_columns(self):

        columns = self.db.select("PRAGMA table_info(crime_members)")
        names = {str(col["name"]).lower() for col in columns}

        if "is_in_oc" not in names:
            self.db.execute("ALTER TABLE crime_members ADD COLUMN is_in_oc INTEGER")
            self.db.commit()
