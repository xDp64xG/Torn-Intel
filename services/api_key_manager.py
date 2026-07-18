"""
services/api_key_manager.py

Manages multiple API keys for rate limit distribution and rotation.
Handles key cycling, rate limit tracking, and retry logic.
"""

import time
from collections import defaultdict


class ApiKeyManager:
    """
    Manage multiple API keys with automatic rotation and rate limit handling.
    
    Features:
    - Cycle through keys to distribute API calls
    - Track rate limit status per key
    - Exponential backoff retry logic
    - Automatic key recovery
    """

    def __init__(self, api_keys, settings, logger):
        """
        Args:
            api_keys: List of API key strings
            settings: Settings object with max_retries, retry_backoff_base, rate_limit_error_code
            logger: Logger instance
        """
        self.api_keys = api_keys
        self.settings = settings
        self.logger = logger
        
        # Track current key index for round-robin rotation
        self.current_key_index = 0
        
        # Track rate limit status per key
        # key -> {"rate_limited": bool, "retry_after": timestamp, "failed_attempts": int}
        self.key_status = defaultdict(lambda: {
            "rate_limited": False,
            "retry_after": 0,
            "failed_attempts": 0,
            "total_requests": 0,
            "total_rate_limits": 0,
        })

    ########################################################

    def get_next_key(self, skip_rate_limited=True):
        """
        Get the next API key, optionally skipping rate-limited ones.
        Uses round-robin rotation.
        
        Args:
            skip_rate_limited: If True, skip keys that are currently rate limited
        
        Returns:
            API key string
        """
        start_index = self.current_key_index
        
        while True:
            key = self.api_keys[self.current_key_index]
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
            
            # Check if we should skip this key
            if skip_rate_limited:
                status = self.key_status[key]
                if status["rate_limited"]:
                    # Check if enough time has passed to retry
                    if time.time() < status["retry_after"]:
                        # Still rate limited, try next key
                        if self.current_key_index == start_index:
                            # All keys are exhausted, wait and use this one anyway
                            wait_time = status["retry_after"] - time.time()
                            self.logger.warning(
                                f"All API keys rate limited, waiting {wait_time:.1f}s"
                            )
                            time.sleep(wait_time + 1)
                            status["rate_limited"] = False
                            return key
                        continue
                    else:
                        # Rate limit has expired, clear it and use this key
                        status["rate_limited"] = False
                        self.logger.info(f"Key recovered from rate limit")
            
            return key

    ########################################################

    def record_success(self, key):
        """Record a successful API call with this key."""
        status = self.key_status[key]
        status["total_requests"] += 1
        status["failed_attempts"] = 0

    ########################################################

    def record_rate_limit(self, key, wait_seconds=None):
        """
        Record a rate limit error for a key.
        
        Args:
            key: API key that was rate limited
            wait_seconds: Seconds to wait before retry (from API response if available)
        """
        status = self.key_status[key]
        status["total_rate_limits"] += 1
        status["rate_limited"] = True
        status["failed_attempts"] += 1
        
        if wait_seconds:
            # Use API's suggested wait time
            status["retry_after"] = time.time() + wait_seconds
            self.logger.warning(
                f"Rate limited (key {key[:8]}...), waiting {wait_seconds}s"
            )
        else:
            # Use exponential backoff
            backoff = self.settings.retry_backoff_base ** status["failed_attempts"]
            status["retry_after"] = time.time() + backoff
            self.logger.warning(
                f"Rate limited (key {key[:8]}...), backing off {backoff}s (attempt {status['failed_attempts']})"
            )

    ########################################################

    def record_failure(self, key, error_code=None):
        """
        Record a request failure.
        
        Args:
            key: API key that failed
            error_code: Torn API error code if available
        """
        status = self.key_status[key]
        status["failed_attempts"] += 1
        status["total_requests"] += 1

    ########################################################

    def get_status(self):
        """Get summary of all keys and their status."""
        summary = []
        for key in self.api_keys:
            status = self.key_status[key]
            is_limited = status["rate_limited"]
            time_until_retry = max(0, status["retry_after"] - time.time())
            
            summary.append({
                "key": f"{key[:12]}...",
                "rate_limited": is_limited,
                "time_until_retry": f"{time_until_retry:.1f}s" if is_limited else "N/A",
                "total_requests": status["total_requests"],
                "total_rate_limits": status["total_rate_limits"],
            })
        
        return summary

    ########################################################

    def log_status(self):
        """Log current status of all API keys."""
        status = self.get_status()
        available_keys = sum(1 for s in status if not s["rate_limited"])
        
        self.logger.info(f"API Key Status: {available_keys}/{len(self.api_keys)} available")
        for s in status:
            if s["rate_limited"]:
                self.logger.info(
                    f"  Key {s['key']} - RATE LIMITED (retry in {s['time_until_retry']})"
                )
            else:
                self.logger.info(
                    f"  Key {s['key']} - {s['total_requests']} req, {s['total_rate_limits']} limits"
                )
