class TornAPIError(Exception):
    pass


class APIKeyError(TornAPIError):
    pass


class RateLimitError(TornAPIError):
    pass


class DatabaseError(Exception):
    pass