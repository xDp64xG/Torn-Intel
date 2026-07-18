"""
Lightweight publish/subscribe event system.
"""

from collections import defaultdict
from typing import Callable


class EventBus:

    def __init__(self):

        self.listeners = defaultdict(list)

    ########################################################

    def subscribe(
        self,
        event: str,
        callback: Callable
    ):

        self.listeners[event].append(callback)

    ########################################################

    def emit(
        self,
        event: str,
        *args,
        **kwargs
    ):

        for callback in self.listeners[event]:

            callback(
                *args,
                **kwargs
            )