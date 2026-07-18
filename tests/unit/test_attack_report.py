"""
Unit tests for chain reports
"""
import pytest
from modules.attacks.report import AttackReport
from services.container import ServiceContainer


@pytest.fixture
def report():
    """Set up attack report"""
    services = ServiceContainer()
    return AttackReport(services.database)


class TestChainReports:
    """Test chain reporting functionality"""

    def test_chain_hit_returns_correct_attack(self, report):
        """Test finding a specific hit by position"""
        hit = report.chain_hit(1, 1)
        
        assert hit is not None
        assert hit["hit_position"] == 1
        assert "attacker_id" in hit
        assert "defender_id" in hit

    def test_chain_hit_invalid_number_returns_none(self, report):
        """Test that invalid hit numbers return None"""
        hit = report.chain_hit(1, 99999)
        
        assert hit is None

    def test_chain_stats_returns_all_fields(self, report):
        """Test that chain stats include all required fields"""
        stats = report.chain_stats(1)
        
        assert stats is not None
        assert "total_hits" in stats
        assert "unique_attackers" in stats
        assert "success_rate_pct" in stats
        assert "total_respect_gained" in stats
        assert "top_attacker" in stats

    def test_chain_stats_nonexistent_chain(self, report):
        """Test that nonexistent chains return None"""
        stats = report.chain_stats(999999)
        
        assert stats is None

    def test_chain_timeline_ordered_by_timestamp(self, report):
        """Test that timeline returns hits in chronological order"""
        timeline = report.chain_timeline(1)
        
        assert len(timeline) > 0
        
        # Verify hits are numbered sequentially
        for i, hit in enumerate(timeline, 1):
            assert hit["hit_number"] == i

    def test_chain_leaderboard_sorted_by_hits(self, report):
        """Test that leaderboard is sorted by hit count"""
        leaderboard = report.chain_leaderboard(1)
        
        assert len(leaderboard) > 0
        
        # First attacker should have most hits
        for i in range(len(leaderboard) - 1):
            assert leaderboard[i]["hits"] >= leaderboard[i+1]["hits"]

    def test_chain_leaderboard_includes_stats(self, report):
        """Test that leaderboard includes all stat fields"""
        leaderboard = report.chain_leaderboard(1)
        
        assert len(leaderboard) > 0
        
        first = leaderboard[0]
        assert "attacker_name" in first
        assert "hits" in first
        assert "total_respect" in first
        assert "success_rate_pct" in first
