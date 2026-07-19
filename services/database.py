"""
services/database.py

SQLite database manager for TornIntel.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class Database:

    def __init__(self, settings, logger):

        self.logger = logger

        db_path = Path(settings.database_path)

        db_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self._lock = threading.RLock()
        self._local = threading.local()

        self.connection = sqlite3.connect(
            db_path,
            check_same_thread=False
        )

        self.connection.row_factory = sqlite3.Row

        self.logger.success(
            f"Connected to {db_path}"
        )

    #######################################################

    def execute(self, sql, params=()):

        with self._lock:
            cursor = self.connection.execute(sql, params)
            self._local.cursor = cursor
            return cursor

    #######################################################

    def executemany(self, sql, values):

        with self._lock:
            cursor = self.connection.executemany(sql, values)
            self._local.cursor = cursor

    #######################################################

    def commit(self):

        with self._lock:
            self.connection.commit()

    #######################################################

    def rollback(self):

        with self._lock:
            self.connection.rollback()

    #######################################################

    def close(self):

        with self._lock:
            self.connection.close()

    #######################################################

    def fetchone(self):

        cursor = getattr(self._local, "cursor", None)
        if cursor is None:
            raise RuntimeError("No active cursor for current thread")
        return cursor.fetchone()

    #######################################################

    def fetchall(self):

        cursor = getattr(self._local, "cursor", None)
        if cursor is None:
            raise RuntimeError("No active cursor for current thread")
        return cursor.fetchall()

    #######################################################

    def table_exists(self, table_name):

        self.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name=?
            """,
            (table_name,)
        )

        return self.fetchone() is not None

    #######################################################

    def create_table(self, sql):

        self.execute(sql)

        self.commit()

    #######################################################

    def insert(self, table, values):

        columns = ",".join(values.keys())

        placeholders = ",".join(
            "?"
            for _ in values
        )

        sql = f"""
        INSERT INTO {table}
        ({columns})
        VALUES
        ({placeholders})
        """

        self.execute(
            sql,
            tuple(values.values())
        )

        self.commit()

    #######################################################

    def select(self, sql, params=()):

        self.execute(sql, params)

        return self.fetchall()