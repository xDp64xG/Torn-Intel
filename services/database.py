"""
services/database.py

SQLite database manager for TornIntel.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:

    def __init__(self, settings, logger):

        self.logger = logger

        db_path = Path(settings.database_path)

        db_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.connection = sqlite3.connect(db_path)

        self.connection.row_factory = sqlite3.Row

        self.cursor = self.connection.cursor()

        self.logger.success(
            f"Connected to {db_path}"
        )

    #######################################################

    def execute(self, sql, params=()):

        self.cursor.execute(sql, params)

        return self.cursor

    #######################################################

    def executemany(self, sql, values):

        self.cursor.executemany(sql, values)

    #######################################################

    def commit(self):

        self.connection.commit()

    #######################################################

    def rollback(self):

        self.connection.rollback()

    #######################################################

    def close(self):

        self.connection.close()

    #######################################################

    def fetchone(self):

        return self.cursor.fetchone()

    #######################################################

    def fetchall(self):

        return self.cursor.fetchall()

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