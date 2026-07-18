"""
services/container.py

Wires every shared service together in one place. Every
sync/query module receives this container and pulls out
exactly what it needs - nothing constructs its own
dependencies internally.
"""

from config.settings import Settings
from utils.logger import Logger
from services.database import Database
from services.cache import Cache
from services.http_client import HttpClient
from services.api_key_manager import ApiKeyManager
from gateways.torn_gateway import TornGateway
from gateways.armoury_gateway import ArmouryGateway
from services.attack_service import AttackService
from services.chain_service import ChainService
from services.rankedwars_service import RankedWarsService
from services.armoury_service import ArmouryService
from services.crime_service import CrimeService
from services.revive_service import ReviveService
from services.revive_request_listener import ReviveRequestListener
from services.item_price_service import ItemPriceService
from repositories.armoury_news_repository import ArmouryNewsRepository
from repositories.item_price_repository import ItemPriceRepository
from core.events import EventBus
from services.scheduler import SyncScheduler


class ServiceContainer:

    def __init__(self):

        self.settings = Settings()

        self.logger = Logger()

        self.database = Database(self.settings, self.logger)

        self.cache = Cache()

        self.events = EventBus()

        # Create API key manager for multi-key support and rate limiting
        self.key_manager = ApiKeyManager(
            api_keys=self.settings.api_keys,
            settings=self.settings,
            logger=self.logger,
        )
        
        self.logger.info(f"Initialized with {len(self.settings.api_keys)} API key(s)")

        self.http = HttpClient(
            timeout=self.settings.request_timeout,
            key_manager=self.key_manager,
        )

        self.gateway = TornGateway(
            http=self.http,
            settings=self.settings,
            logger=self.logger,
            key_manager=self.key_manager,
        )

        # Armoury gateway for faction item tracking
        self.armoury_gateway = ArmouryGateway(
            http_client=self.http,
            key_manager=self.key_manager,
            settings=self.settings,
        )

        # Repositories for armoury data persistence
        self.armoury_repo = ArmouryNewsRepository(self.database)
        self.item_price_repo = ItemPriceRepository(self.database)

        # BaseSync looks for `services.api` generically -
        # gateway fills that role for now.
        self.api = self.gateway

        self.attacks = AttackService(
            gateway=self.gateway,
            logger=self.logger,
        )

        self.chains = ChainService(
            gateway=self.gateway,
            logger=self.logger,
        )

        self.rankedwars = RankedWarsService(
            gateway=self.gateway,
            logger=self.logger,
            settings=self.settings,
        )

        self.armoury = ArmouryService(
            gateway=self.armoury_gateway,
            logger=self.logger,
        )

        self.crimes = CrimeService(
            gateway=self.gateway,
            logger=self.logger,
        )

        self.revives = ReviveService(
            gateway=self.gateway,
            logger=self.logger,
        )

        self.revive_listener = ReviveRequestListener(self)

        self.item_price_service = ItemPriceService(
            gateway=self.armoury_gateway,
            market_gateway=self.gateway,
            database=self.database,
            logger=self.logger,
        )

        self.scheduler = SyncScheduler(
            engine=None,  # Will be wired by engine after it's created
            logger=self.logger,
        )