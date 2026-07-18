"""
Lightweight SQL Query Builder for TornIntel.
"""

from __future__ import annotations


class Query:

    def __init__(self, database, table):

        self.db = database
        self.table = table

        self._where = []
        self._params = []

        self._order = None
        self._limit = None

    ####################################################

    def where(self, column, value):

        self._where.append(f"{column}=?")
        self._params.append(value)

        return self

    ####################################################

    def order_by(self, column, descending=False):

        direction = "DESC" if descending else "ASC"

        self._order = f"{column} {direction}"

        return self

    ####################################################

    def limit(self, amount):

        self._limit = amount

        return self

    ####################################################

    def all(self):

        sql = f"SELECT * FROM {self.table}"

        if self._where:
            sql += " WHERE " + " AND ".join(self._where)

        if self._order:
            sql += f" ORDER BY {self._order}"

        if self._limit:
            sql += f" LIMIT {self._limit}"

        return self.db.select(sql, tuple(self._params))

    ####################################################

    def first(self):

        self.limit(1)

        rows = self.all()

        return rows[0] if rows else None