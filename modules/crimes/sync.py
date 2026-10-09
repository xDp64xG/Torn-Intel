"""
modules/crimes/sync.py

Sync active OC 2.0 slots and CPR data.
"""

from core.sync import BaseSync
from core.schema import SchemaBuilder
from models.crime_slot import CrimeSlot, CrimeCprStat, CrimeMember, CrimeSlotHistory, CrimeDelayEvent, CrimeDelayNotification
from repositories.crime_slot_repository import CrimeSlotRepository
from modules.crimes.parser import CrimeParser


class CrimeSync(BaseSync):

    name = "Crimes"

    def __init__(self, services):

        super().__init__(services)

        self.crimes = services.crimes
        self.repo = CrimeSlotRepository(services.database)

        schema = SchemaBuilder(services.database, services.logger)
        schema.create(CrimeSlot)
        schema.create(CrimeCprStat)
        schema.create(CrimeMember)
        schema.create(CrimeSlotHistory)
        schema.create(CrimeDelayEvent)
        schema.create(CrimeDelayNotification)

        self._ensure_member_columns()

    #######################################################

    def sync(self, mode="backfill", filters=None, faction=None, **kwargs):

        if str(faction or "").strip().lower() == "all":
            total = 0
            for f in self.services.settings.list_factions():
                self.logger.info(f"Syncing crimes for faction {f.tag} ({f.name})...")
                total += self._sync_one_faction(mode=mode, faction=f.tag, pages=kwargs.get("pages", 50))
            return total

        return self._sync_one_faction(mode=mode, faction=faction, pages=kwargs.get("pages", 50))

    def _sync_one_faction(self, mode="backfill", faction=None, pages=50):

        if mode == "live":
            return self._sync_snapshot(faction=faction)

        if mode == "backfill":
            return self._backfill(pages=pages, faction=faction)

        raise ValueError(
            f"Unknown sync mode for crimes: '{mode}'"
        )

    #######################################################

    def _sync_snapshot(self, faction=None):

        snapshot = self.crimes.fetch_snapshot(faction=faction)
        if not snapshot.get("ok", True) or not snapshot.get("members"):
            self.logger.warning(f"Crimes snapshot sync skipped for {faction or 'default'}: incomplete or invalid snapshot from Torn API")
            return 0

        faction_tag = snapshot.get("faction_tag")
        faction_id = snapshot.get("faction_id")
        members = snapshot["members"]
        slots = snapshot["active_slots"]
        cpr_rows = snapshot["cpr_rows"]

        self.repo.replace_members(members, faction_tag=faction_tag, faction_id=faction_id)
        self.repo.replace_active_slots(slots, faction_tag=faction_tag, faction_id=faction_id)
        self.repo.insert_history_slots(slots, faction_tag=faction_tag, faction_id=faction_id)
        self.repo.upsert_cpr_stats(cpr_rows, faction_tag=faction_tag, faction_id=faction_id)
        delay_summary = self.repo.track_flying_delays(
            slots,
            members,
            crime_status_rows=snapshot.get("crime_status_rows") or [],
            faction_tag=faction_tag,
            faction_id=faction_id,
        )

        self.logger.info(
            f"Crimes snapshot synced [{faction_tag}]: {len(members)} members, {len(slots)} active slots, {len(cpr_rows)} CPR rows, "
            f"{delay_summary.get('active', 0)} active OC delays (travel/hospital), "
            f"{delay_summary.get('started', 0)} started, {delay_summary.get('resolved', 0)} resolved"
        )

        return len(slots)

    #######################################################

    def _backfill(self, pages=50, faction=None):

        snapshot = self.crimes.fetch_snapshot(faction=faction)
        if not snapshot.get("ok", True) or not snapshot.get("members"):
            self.logger.warning(f"Crimes backfill sync skipped for {faction or 'default'}: incomplete or invalid snapshot from Torn API")
            return 0

        faction_tag = snapshot.get("faction_tag")
        faction_id = snapshot.get("faction_id")
        members = snapshot["members"]
        active_slots = snapshot["active_slots"]
        completed_slots = self.crimes.backfill_completed_slots(pages=pages, faction=faction)

        all_cpr_rows = list(snapshot["cpr_rows"])
        completed_cpr_rows = CrimeParser.parse_cpr_rows(completed_slots, faction_id=faction_id, faction_tag=faction_tag)
        all_cpr_rows.extend(completed_cpr_rows)

        self.repo.replace_members(members, faction_tag=faction_tag, faction_id=faction_id)
        self.repo.replace_active_slots(active_slots, faction_tag=faction_tag, faction_id=faction_id)
        self.repo.insert_history_slots(active_slots, faction_tag=faction_tag, faction_id=faction_id)
        self.repo.insert_history_slots(completed_slots, faction_tag=faction_tag, faction_id=faction_id)
        self.repo.upsert_cpr_stats(all_cpr_rows, faction_tag=faction_tag, faction_id=faction_id)
        self.repo.track_flying_delays(
            active_slots,
            members,
            crime_status_rows=snapshot.get("crime_status_rows") or [],
            faction_tag=faction_tag,
            faction_id=faction_id,
        )

        self.logger.info(
            f"Crimes backfill synced [{faction_tag}]: "
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

        if "status_state" not in names:
            self.db.execute("ALTER TABLE crime_members ADD COLUMN status_state TEXT")
            self.db.commit()

        if "status_description" not in names:
            self.db.execute("ALTER TABLE crime_members ADD COLUMN status_description TEXT")
            self.db.commit()
