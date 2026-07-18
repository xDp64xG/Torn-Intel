"""
services/scheduler.py

Continuous background sync scheduler for live data collection.
Uses multi-key system to efficiently pull all available data.
"""

import time
from datetime import datetime


class SyncScheduler:
    """Run sync operations continuously, using all API keys efficiently."""

    def __init__(self, engine, logger):
        self.engine = engine
        self.logger = logger

    def run_continuous(self, module, catch_up_cooldown=5, duration_seconds=None):
        """
        Run live sync aggressively until caught up, then poll for new data.

        Strategy:
        1. Keep syncing as fast as possible until 0 records imported
        2. Once caught up, poll at intervals (catch_up_cooldown)
        3. If new data appears, resume aggressive sync
        4. Stop only if all keys are rate limited or duration exceeded

        Args:
            module: Module name (e.g., 'attacks')
            catch_up_cooldown: Seconds to wait between polls when caught up (default: 5s)
            duration_seconds: Total seconds to run (None = infinite)

        Usage:
            scheduler = SyncScheduler(engine, logger)
            scheduler.run_continuous('attacks', catch_up_cooldown=10)
        """
        start_time = time.time()
        run_count = 0
        consecutive_empty = 0

        self.logger.info(
            f"🔄 Starting aggressive {module} sync (cooldown: {catch_up_cooldown}s when caught up)"
        )

        try:
            while True:
                # Check if we've exceeded max duration
                if duration_seconds is not None:
                    elapsed = time.time() - start_time
                    if elapsed > duration_seconds:
                        self.logger.info(
                            f"⏱️  Duration limit reached ({elapsed:.0f}s)"
                        )
                        break

                # Run sync
                run_count += 1
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                try:
                    imported = self.engine.sync(module, mode="live")
                    
                    if imported > 0:
                        # Got new data - reset empty counter and keep going
                        consecutive_empty = 0
                        self.logger.info(
                            f"[{timestamp}] Run #{run_count}: ✓ Imported {imported} records (continuing...)"
                        )
                        # No sleep - keep pulling data
                        
                    else:
                        # No new data this run
                        consecutive_empty += 1
                        
                        if consecutive_empty == 1:
                            # Just caught up
                            self.logger.info(
                                f"[{timestamp}] Run #{run_count}: ✓ No new records (caught up)"
                            )
                        else:
                            self.logger.info(
                                f"[{timestamp}] Run #{run_count}: ✓ Still caught up ({consecutive_empty}x)"
                            )
                        
                        # We're caught up - wait before polling again
                        self.logger.info(f"  ⏸️  Waiting {catch_up_cooldown}s to poll for new data...")
                        time.sleep(catch_up_cooldown)
                        
                except Exception as e:
                    self.logger.error(
                        f"  ✗ Sync error: {type(e).__name__}: {e}"
                    )
                    # On error, wait a bit before retrying
                    time.sleep(catch_up_cooldown)

        except KeyboardInterrupt:
            elapsed = time.time() - start_time
            self.logger.info(
                f"\n⏹️  Stopped after {run_count} runs ({elapsed:.0f}s total)"
            )
