"""
Base class for every TornIntel module.
"""

from abc import ABC, abstractmethod


class Module(ABC):
    """
    Every module inherits from this.
    """

    def __init__(self, services):
        self.services = services

    @property
    @abstractmethod
    def name(self):
        """
        Human readable module name.
        """
        pass

    @abstractmethod
    def sync(self):
        """
        Download latest data.
        """
        pass

    @abstractmethod
    def report(self):
        """
        Produce report.
        """
        pass