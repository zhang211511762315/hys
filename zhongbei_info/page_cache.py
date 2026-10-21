from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError


class BestEffortPageCache(RedisCache):
    """Only disposable page caching degrades; admission/auth cache stays strict."""
    def get(self, key, default=None, version=None):
        try:
            return super().get(key, default, version)
        except RedisError:
            return default

    def set(self, key, value, timeout=300, version=None):
        try:
            return super().set(key, value, timeout, version)
        except RedisError:
            return False
