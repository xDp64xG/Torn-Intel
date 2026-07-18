import requests
import time
import re


class RateLimitError(Exception):
    """Raised when API rate limit is hit."""
    pass


class HttpClient:
    """
    HTTP client with retry logic and rate limit handling.
    Works with ApiKeyManager to handle multiple keys and exponential backoff.
    """

    def __init__(self, timeout=30, key_manager=None):
        self.timeout = timeout
        self.key_manager = key_manager
        self.session = requests.Session()

    ##################################################

    def get(self, url, params=None, max_retries=5, retry_backoff_base=2):
        """
        Make a GET request with automatic retry on rate limits.
        
        Args:
            url: URL to request
            params: Query parameters (should include 'key')
            max_retries: Max retry attempts
            retry_backoff_base: Base for exponential backoff
            
        Returns:
            JSON response
            
        Raises:
            RateLimitError: If rate limit persists after all retries
            requests.HTTPError: For other HTTP errors
        """
        attempt = 0
        
        retry_schedule = [10, 20, 30, 60]
        if self.key_manager and hasattr(self.key_manager.settings, "rate_limit_retry_schedule"):
            retry_schedule = self.key_manager.settings.rate_limit_retry_schedule

        while attempt < max_retries:
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                
                data = response.json()
                
                # Check for Torn API errors in response
                if isinstance(data, dict) and "error" in data:
                    error_code = data["error"].get("code")
                    error_msg = data["error"].get("error", "Unknown error")
                    
                    # Error code 5 = burst rate limit, 14 = daily read limit
                    if error_code in (5, 14):
                        wait_seconds = None
                        wait_match = re.search(r"(\d+)\s*second", str(error_msg), re.IGNORECASE)
                        if wait_match:
                            wait_seconds = int(wait_match.group(1))

                        attempt += 1
                        if attempt >= max_retries:
                            raise RateLimitError(
                                f"Rate limited after {max_retries} attempts: {error_msg}"
                            )

                        # Fixed escalating backoff tuned for heavier backfill runs.
                        if wait_seconds:
                            backoff = wait_seconds
                        else:
                            idx = min(attempt - 1, len(retry_schedule) - 1)
                            backoff = retry_schedule[idx]
                        if self.key_manager and params and params.get("key"):
                            self.key_manager.record_rate_limit(params["key"], wait_seconds=backoff)
                        print(
                            f"Rate limit (code {error_code}), backing off {backoff}s "
                            f"(attempt {attempt}/{max_retries})"
                        )
                        time.sleep(backoff)
                        continue
                    
                    # Other Torn API errors - don't retry
                    return data
                
                # Success
                if self.key_manager and params.get("key"):
                    self.key_manager.record_success(params["key"])
                
                return data
                
            except requests.exceptions.Timeout:
                attempt += 1
                if self.key_manager and params and params.get("key"):
                    self.key_manager.record_failure(params["key"])
                if attempt >= max_retries:
                    raise
                
                backoff = retry_backoff_base ** attempt
                print(f"Timeout, backing off {backoff}s (attempt {attempt}/{max_retries})")
                time.sleep(backoff)
                
            except requests.exceptions.RequestException as e:
                attempt += 1
                if self.key_manager and params and params.get("key"):
                    self.key_manager.record_failure(params["key"])
                if attempt >= max_retries:
                    raise
                
                backoff = retry_backoff_base ** attempt
                print(f"Request error: {e}, backing off {backoff}s (attempt {attempt}/{max_retries})")
                time.sleep(backoff)