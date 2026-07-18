"""
Simple in-memory cache for runtime state.

Later this can be backed by SQLite or Redis.
"""

from __future__ import annotations

from typing import Any


class Cache:

    def __init__(self):

        self._cache = {}

    #####################################################

    def get(self, key: str, default=None) -> Any:

        return self._cache.get(key, default)

    #####################################################

    def set(self, key: str, value: Any):

        self._cache[key] = value

    #####################################################

    def has(self, key: str) -> bool:

        return key in self._cache

    #####################################################

    def remove(self, key: str):

        self._cache.pop(key, None)

    #####################################################

    def clear(self):

        self._cache.clear()

    #####################################################

    def keys(self):

        return self._cache.keys()