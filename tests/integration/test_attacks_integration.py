"""
Integration tests for attacks module
"""
import pytest
from services.database import Database
from config.settings import Settings
from utils.logger import Logger
from modules.attacks.sync import AttackSync
from modules.attacks.queries import AttackQueries
from services.container import ServiceContainer


@pytest.fixture
def services():
    """Set up services for testing"""
    return ServiceContainer()


@pytest.fixture
def syncer(services):
    """Set up attack syncer"""
    return AttackSync(services)


@pytest.fixture
def queries(services):
    """Set up attack queries"""
    return AttackQueries(services.database)


class TestAttackSync:
    """Test attack synchronization"""

    def test_backfill_mode_imports_attacks(self, syncer):
        """Test that backfill mode imports records from API"""
        # This test requires a real API key and will hit the live API
        # Adjust the limit to avoid too many API calls during tests
        result = syncer.sync(mode="backfill", filters=None)
        
        assert isinstance(result, int)
        assert result >= 0

    def test_live_mode_handles_empty_database(self, syncer):
        """Test that live mode works when database is empty"""
        # In a test database, start should pick up from beginning
        result = syncer.sync(mode="live", filters=None)
        
        assert isinstance(result, int)
        assert result >= 0


class TestAttackQueries:
    """Test attack search queries"""

    def test_by_attacker_returns_results(self, queries):
        """Test searching attacks by attacker ID"""
        # Get first attacker from database
        rows = queries.repo.db.select(
            "SELECT DISTINCT attacker_id FROM attacks LIMIT 1"
        )
        if rows and rows[0]["attacker_id"] is not None:
            attacker_id = rows[0]["attacker_id"]
            results = queries.by_attacker(attacker_id)
            
            assert isinstance(results, list)
            # Verify all results have matching attacker
            for result in results:
                assert result["attacker_id"] == attacker_id

    def test_by_defender_returns_results(self, queries):
        """Test searching attacks by defender ID"""
        rows = queries.repo.db.select(
            "SELECT DISTINCT defender_id FROM attacks LIMIT 1"
        )
        if rows and rows[0]["defender_id"] is not None:
            defender_id = rows[0]["defender_id"]
            results = queries.by_defender(defender_id)
            
            assert isinstance(results, list)
            # Verify all results have matching defender
            for result in results:
                assert result["defender_id"] == defender_id

    def test_by_result_returns_results(self, queries):
        """Test searching attacks by result"""
        rows = queries.repo.db.select(
            "SELECT DISTINCT result FROM attacks WHERE result IS NOT NULL LIMIT 1"
        )
        if rows:
            result_type = rows[0]["result"]
            results = queries.by_result(result_type)
            
            assert isinstance(results, list)
            # Verify all results have matching result
            for result in results:
                assert result["result"] == result_type

    def test_by_chain_returns_results(self, queries):
        """Test searching attacks by chain"""
        rows = queries.repo.db.select(
            "SELECT DISTINCT chain FROM attacks WHERE chain > 0 LIMIT 1"
        )
        if rows:
            chain_num = rows[0]["chain"]
            results = queries.by_chain(chain_num)
            
            assert isinstance(results, list)
            # Verify all results have matching chain
            for result in results:
                assert result["chain"] == chain_num
