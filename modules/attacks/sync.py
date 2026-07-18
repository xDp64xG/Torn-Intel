"""
modules/attacks/sync.py

Keeps the local attacks table up to date. Two modes:
- backfill: walk backward from now, stop once an
  already-synced attack is hit.
- live: pick up from the last synced attack and walk
  forward, inserting anything new.

Read-only lookups against already-synced data live in
modules/attacks/queries.py, not here.
"""

from core.sync import BaseSync
from core.schema import SchemaBuilder
from models.attack import Attack
from repositories.attack_repository import AttackRepository
from services.http_client import RateLimitError
import time


class AttackSync(BaseSync):

    name = "Attacks"

    def __init__(self, services):

        super().__init__(services)

        self.attacks = services.attacks

        self.repo = AttackRepository(services.database)

        if not services.database.table_exists(Attack.table_name):

            SchemaBuilder(
                services.database,
                services.logger
            ).create(Attack)

    #######################################################

    def sync(self, mode="backfill", filters=None, **kwargs):

        if mode == "backfill":
            return self._backfill(
                filters,
                from_timestamp=kwargs.get("from_timestamp"),
                to_timestamp=kwargs.get("to_timestamp"),
            )

        if mode == "live":
            return self._live(filters)

        raise ValueError(
            f"Unknown sync mode for attacks: '{mode}'"
        )

    #######################################################

    def _backfill(self, filters, from_timestamp=None, to_timestamp=None):
        """
        Walk backward through attack history, importing any records not yet synced.
        
        If to_timestamp is provided, start from that point and walk backward.
        If from_timestamp is provided, stop when we reach it (lower bound).
        
        Unlike live mode, this continues through the entire history,
        skipping records that already exist instead of stopping.
        """

        total = 0
        checkpoint_key = "attacks_backfill"

        start_to_timestamp = to_timestamp
        if start_to_timestamp is None:
            resume_to = self._get_resume_checkpoint(checkpoint_key)
            if resume_to is not None:
                start_to_timestamp = int(resume_to)
                self.logger.info(
                    f"Resuming attacks backfill from checkpoint (to={start_to_timestamp})"
                )

        # Seed resume anchor so failures before first fetched page still resume deterministically.
        initial_anchor = int(start_to_timestamp) if start_to_timestamp is not None else int(time.time())
        self._set_resume_checkpoint(
            checkpoint_key,
            initial_anchor,
            note="initial attacks backfill anchor",
        )

        try:
            for page in self.attacks.iter_pages(
                filters=filters,
                sort="DESC",
                from_timestamp=from_timestamp,
                to_timestamp=start_to_timestamp,
            ):
                if page:
                    next_to = min(a.timestamp_started for a in page) - 1
                    if next_to > 0:
                        self._set_resume_checkpoint(
                            checkpoint_key,
                            next_to,
                            note="auto-saved during attacks backfill",
                        )

                for attack in page:
                    if self.repo.exists(attack.attack_id):
                        continue  # Skip duplicates, continue deeper history

                    self.repo.insert(attack)
                    total += 1

        except RateLimitError as exc:
            self.logger.warning(
                f"Attacks backfill paused due to rate limit: {exc}"
            )
            resume_to = self._get_resume_checkpoint(checkpoint_key)
            if resume_to is not None:
                self.logger.info(
                    f"Resume with: python main.py sync attacks --mode backfill --to {resume_to}"
                )
            return total

        self._clear_resume_checkpoint(checkpoint_key)
        return total

    #######################################################

    def _live(self, filters):

        last_id = self.repo.latest_attack()

        from_timestamp = None

        if last_id is not None:

            existing = self.repo.where("attack_id", last_id).first()

            if existing:
                from_timestamp = existing["timestamp_started"] + 1

        total = 0

        for page in self.attacks.iter_pages(
            filters=filters,
            sort="ASC",
            from_timestamp=from_timestamp,
        ):

            for attack in page:

                if self.repo.exists(attack.attack_id):
                    continue

                self.repo.insert(attack)

                total += 1

        return total