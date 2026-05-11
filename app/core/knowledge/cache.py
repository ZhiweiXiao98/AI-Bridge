# filename: app/core/knowledge/cache.py
"""LRU 缓存，支持 TTL 过期"""

import time
from collections import OrderedDict
from app.core.knowledge.config import CACHE_MAX_SIZE, CACHE_TTL_SECONDS


class LRUCache:
    """带 TTL 的 LRU 缓存"""

    def __init__(self, max_size=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS):
        self.max_size = max_size
        self.ttl = ttl
        self._cache = OrderedDict()  # key -> (value, timestamp)

    def get(self, key):
        """获取缓存，未命中返回 None"""
        if key not in self._cache:
            return None
        value, ts = self._cache[key]
        if time.time() - ts > self.ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def put(self, key, value):
        """写入缓存"""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, time.time())
        if len(self._cache) > self.max_size:
            self._cache.popitem(last=False)

    def invalidate(self, prefix=None):
        """清除缓存，可按前缀清除"""
        if prefix is None:
            self._cache.clear()
        else:
            keys_to_del = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_del:
                del self._cache[k]

    @property
    def size(self):
        return len(self._cache)