"""
modules/rankedwars/sync.py

Sync ranked wars from the API to the local database.
Unlike attacks (which walk paginated history), ranked wars is a complete snapshot.
"""

from core.sync import BaseSync
from core.schema import SchemaBuilder
from models.rankedwar import RankedWar
from repositories.rankedwar_repository import RankedWarRepository


class RankedWarsSync(BaseSync):
    """
    Sync ranked wars from the API.
    
    Modes:
    - 'backfill': Fetch all wars from the API and upsert them.
    
    Unlike attacks, there's no pagination—the API returns all wars at once.
    Just fetch, parse, and upsert.
    """
    
    name = "Ranked Wars"
    
    def __init__(self, services):
        super().__init__(services)
        
        self.logger = services.logger
        self.repo = RankedWarRepository(services.database)
        
        # Import here to avoid circular dependency
        from services.rankedwars_service import RankedWarsService
        
        self.service = RankedWarsService(
            gateway=services.gateway,
            logger=services.logger,
            settings=services.settings,
        )
        
        # Ensure table exists
        if not services.database.table_exists(RankedWar.table_name):
            self.logger.info(f"Creating {RankedWar.table_name} table...")
            SchemaBuilder(services.database, services.logger).create(RankedWar)
    
    def sync(self, mode="backfill", filters=None, **kwargs):
        """
        Sync ranked wars.
        
        Args:
            mode: Always 'backfill' for now (fetches all wars, upserts)
            filters: Ignored
            **kwargs: Other options (ignored)
        
        Returns:
            Count of wars inserted/updated
        """
        
        if mode != "backfill":
            self.logger.warning(f"Unknown mode '{mode}' for rankedwars; using backfill")
        
        self.logger.info("=== RANKED WARS SYNC START ===")
        
        wars = self.service.fetch_wars()
        
        if not wars:
            self.logger.info("No ranked wars to sync")
            self.logger.info("=== RANKED WARS SYNC END ===")
            return 0
        
        # Upsert each war
        inserted = 0
        updated = 0
        
        for war in wars:
            # Auto-detect chains within war's time window
            chain_ids = self._detect_chains(war.war_start, war.war_end)
            chain_ids_str = ",".join(str(cid) for cid in chain_ids) if chain_ids else None
            
            # Check if already exists
            existing = self.repo.by_id(war.war_id)
            
            if existing:
                # Update
                self.db.execute(f"""
                    UPDATE {RankedWar.table_name}
                    SET our_faction_id = ?, our_faction_name = ?,
                        opponent_faction_id = ?, opponent_faction_name = ?,
                        our_score = ?, opponent_score = ?,
                        our_chain = ?, opponent_chain = ?,
                        war_start = ?, war_end = ?, war_target = ?, war_winner_id = ?,
                        chain_ids = ?,
                        synced_at = ?
                    WHERE war_id = ?
                """, (
                    war.our_faction_id, war.our_faction_name,
                    war.opponent_faction_id, war.opponent_faction_name,
                    war.our_score, war.opponent_score,
                    war.our_chain, war.opponent_chain,
                    war.war_start, war.war_end, war.war_target, war.war_winner_id,
                    chain_ids_str,
                    war.synced_at,
                    war.war_id,
                ))
                updated += 1
            else:
                # Insert
                self.db.execute(f"""
                    INSERT INTO {RankedWar.table_name}
                    (war_id, our_faction_id, our_faction_name,
                     opponent_faction_id, opponent_faction_name,
                     our_score, opponent_score,
                     our_chain, opponent_chain,
                     war_start, war_end, war_target, war_winner_id,
                     chain_ids,
                     synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    war.war_id,
                    war.our_faction_id, war.our_faction_name,
                    war.opponent_faction_id, war.opponent_faction_name,
                    war.our_score, war.opponent_score,
                    war.our_chain, war.opponent_chain,
                    war.war_start, war.war_end, war.war_target, war.war_winner_id,
                    chain_ids_str,
                    war.synced_at,
                ))
                inserted += 1
        
        # Commit all changes
        self.db.commit()
        
        total = inserted + updated
        self.logger.info(f"Inserted {inserted}, updated {updated} ranked wars")
        self.logger.info("=== RANKED WARS SYNC END ===")
        
        return total
    
    def _detect_chains(self, war_start, war_end):
        """
        Auto-detect chain IDs that fall within the war's time window.
        
        Args:
            war_start: War start timestamp
            war_end: War end timestamp
        
        Returns:
            List of chain_ids
        """
        rows = self.db.select("""
            SELECT chain_id FROM chains
            WHERE timestamp_start >= ? AND timestamp_end <= ?
            ORDER BY chain_id ASC
        """, (war_start, war_end))
        
        return [r["chain_id"] for r in rows] if rows else []
