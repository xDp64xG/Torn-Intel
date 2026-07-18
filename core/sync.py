"""
Base synchronization class.

Every sync class (Attacks, Crimes, Companies, etc.)
inherits from this.
"""

from abc import ABC, abstractmethod
import time


class BaseSync(ABC):

    def __init__(self, services):

        self.services = services

        self.api = services.api
        self.db = services.database
        self.cache = services.cache
        self.events = services.events
        self.logger = services.logger

    ########################################################

    @property
    @abstractmethod
    def name(self):
        """Human readable module name."""
        pass

    ########################################################

    @abstractmethod
    def sync(self):
        """Synchronize data."""
        pass

    ########################################################

    def start(self ,**kwargs):

        print(f"\n========== {self.name} ==========")

        imported = self.sync(**kwargs)

        print(f"Imported {imported:,} records.")

        print("=" * 32)

        return imported

    ########################################################

    def _ensure_sync_checkpoint_table(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_checkpoints (
                module_key TEXT PRIMARY KEY,
                resume_from INTEGER,
                updated_at INTEGER,
                note TEXT
            )
            """
        )
        self.db.commit()

    def _get_resume_checkpoint(self, module_key):
        self._ensure_sync_checkpoint_table()
        rows = self.db.select(
            "SELECT resume_from FROM sync_checkpoints WHERE module_key = ?",
            (module_key,),
        )
        if rows:
            return rows[0]["resume_from"]
        return None

    def _set_resume_checkpoint(self, module_key, resume_from, note=""):
        self._ensure_sync_checkpoint_table()
        self.db.execute(
            """
            INSERT INTO sync_checkpoints (module_key, resume_from, updated_at, note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(module_key) DO UPDATE SET
                resume_from = excluded.resume_from,
                updated_at = excluded.updated_at,
                note = excluded.note
            """,
            (module_key, int(resume_from), int(time.time()), note),
        )
        self.db.commit()

    def _clear_resume_checkpoint(self, module_key):
        self._ensure_sync_checkpoint_table()
        self.db.execute(
            "DELETE FROM sync_checkpoints WHERE module_key = ?",
            (module_key,),
        )
        self.db.commit()