"""
Sync faction revives and auto-match pending revive requests.
"""

import time

from core.sync import BaseSync
from core.schema import SchemaBuilder
from models.revive import Revive, ReviveRequest
from repositories.revive_repository import ReviveRepository
from repositories.revive_request_repository import ReviveRequestRepository
from services.http_client import RateLimitError
from utils.colors import highlight, info, success


class ReviveSync(BaseSync):

    name = "Revives"

    def __init__(self, services):

        super().__init__(services)

        self.revives = services.revives
        self.repo = ReviveRepository(services.database)
        self.request_repo = ReviveRequestRepository(services.database)

        schema = SchemaBuilder(services.database, services.logger)
        if not services.database.table_exists(Revive.table_name):
            schema.create(Revive)
        if not services.database.table_exists(ReviveRequest.table_name):
            schema.create(ReviveRequest)

    #######################################################

    def sync(self, mode="backfill", filters=None, **kwargs):

        if mode == "backfill":
            return self._backfill(
                from_timestamp=kwargs.get("from_timestamp"),
                to_timestamp=kwargs.get("to_timestamp"),
            )

        if mode == "live":
            return self._live()

        if mode == "search":
            return 0

        raise ValueError(f"Unknown sync mode for revives: '{mode}'")

    #######################################################

    def _backfill(self, from_timestamp=None, to_timestamp=None):

        total = 0
        checkpoint_key = "revives_backfill"

        start_to_timestamp = to_timestamp
        if start_to_timestamp is None:
            resume_to = self._get_resume_checkpoint(checkpoint_key)
            if resume_to is not None:
                start_to_timestamp = int(resume_to)
                self.logger.info(f"Resuming revives backfill from checkpoint (to={start_to_timestamp})")

        initial_anchor = int(start_to_timestamp) if start_to_timestamp is not None else int(time.time())
        self._set_resume_checkpoint(checkpoint_key, initial_anchor, note="initial revives backfill anchor")

        try:
            for page in self.revives.iter_pages(
                sort="DESC",
                from_timestamp=from_timestamp,
                to_timestamp=start_to_timestamp,
            ):
                if page:
                    next_to = min(r.timestamp for r in page) - 1
                    if next_to > 0:
                        self._set_resume_checkpoint(
                            checkpoint_key,
                            next_to,
                            note="auto-saved during revives backfill",
                        )

                for revive in page:
                    if self.repo.exists(revive.revive_id):
                        continue

                    self.repo.insert(revive)
                    fulfilled = self.request_repo.match_revive(revive)
                    if fulfilled:
                        self.logger.success(
                            f"{info('Revive request fulfilled')} target={highlight(fulfilled.get('target_name') or fulfilled.get('target_id'))} "
                            f"by {success(fulfilled.get('fulfilled_by_name') or fulfilled.get('fulfilled_by_id'))} "
                            f"at {success(fulfilled.get('revived_timestamp') or fulfilled.get('fulfilled_at') or revive.timestamp)}"
                        )
                    total += 1

        except RateLimitError as exc:
            self.logger.warning(f"Revives backfill paused due to rate limit: {exc}")
            resume_to = self._get_resume_checkpoint(checkpoint_key)
            if resume_to is not None:
                self.logger.info(
                    f"Resume with: python main.py sync revives --mode backfill --to {resume_to}"
                )
            return total

        self._clear_resume_checkpoint(checkpoint_key)
        return total

    #######################################################

    def _live(self):

        last_ts = self.repo.latest_timestamp()
        from_timestamp = last_ts + 1 if last_ts is not None else None
        total = 0

        for page in self.revives.iter_pages(sort="ASC", from_timestamp=from_timestamp):
            for revive in page:
                if self.repo.exists(revive.revive_id):
                    continue

                self.repo.insert(revive)
                fulfilled = self.request_repo.match_revive(revive)
                if fulfilled:
                    self.logger.success(
                        f"{info('Revive request fulfilled')} target={highlight(fulfilled.get('target_name') or fulfilled.get('target_id'))} "
                        f"by {success(fulfilled.get('fulfilled_by_name') or fulfilled.get('fulfilled_by_id'))} "
                        f"at {success(fulfilled.get('revived_timestamp') or fulfilled.get('fulfilled_at') or revive.timestamp)}"
                    )
                total += 1

        return total