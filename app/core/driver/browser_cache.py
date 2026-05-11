# filename: app/core/driver/browser_cache.py
"""
浏览器消息缓存 —— 按 cache_key (message_id + role) 索引已解析的消息，避免重复 BS4 解析。

缓存命中条件：cache_key 相同 → 内容未变，直接复用。
缓存失效条件：状态机事件驱动（如 PIPELINE_END 失效最后 AI 消息）/ 会话切换时清空。
不再使用 html_len 等内容指纹做命中判断。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CachedMessage:
    """单条消息的缓存条目。"""
    message_id: str
    role: str
    segments: list = field(default_factory=list)
    raw_len: int = 0


class BrowserMessageCache:
    """
    浏览器消息缓存管理器。

    cache_key = f"{message_id}:{role}"  (同一 data-message-id 下 User 和 AI 是两条不同消息)

    用法：
        cache = BrowserMessageCache()
        hit = cache.get(cache_key)  # 命中返回 CachedMessage，否则 None
        cache.put(cache_key, message_id, role, segments, raw_len)  # 写入/更新
        cache.invalidate_message(message_id)  # 状态机事件驱动失效
        cache.clear()  # 会话切换时清空
    """

    def __init__(self):
        self._store: Dict[str, CachedMessage] = {}
        # 按顺序记录 cache_key，用于组装完整列表
        self._order: List[str] = []

    @staticmethod
    def make_key(message_id: str, role: str) -> str:
        """生成缓存 key：message_id:role。同一 data-message-id 下 User 和 AI 是两条不同消息。"""
        return f"{message_id}:{role}"

    @property
    def size(self) -> int:
        return len(self._store)

    def get(self, cache_key: str) -> Optional[CachedMessage]:
        """按 cache_key 查缓存。命中则返回 CachedMessage，否则 None。"""
        return self._store.get(cache_key)

    def put(self, cache_key: str, message_id: str, role: str,
            segments: list, raw_len: int) -> CachedMessage:
        """写入或更新缓存条目。"""
        entry = CachedMessage(
            message_id=message_id,
            role=role,
            segments=segments,
            raw_len=raw_len,
        )
        self._store[cache_key] = entry
        return entry

    def contains(self, cache_key: str) -> bool:
        return cache_key in self._store

    def remove(self, cache_key: str):
        self._store.pop(cache_key, None)

    def invalidate_message(self, message_id: str):
        """状态机事件驱动：失效指定 message_id 的所有缓存条目（User + AI）。
        例如 PIPELINE_END 时失效最后一条 AI 消息，强制下次提取重新获取稳定版本。"""
        keys_to_remove = [k for k in self._store if k.startswith(f"{message_id}:")]
        for k in keys_to_remove:
            del self._store[k]
        if keys_to_remove:
            logger.debug("[消息缓存] 状态机驱动失效 | message_id=%s | 清除=%d 条", message_id, len(keys_to_remove))

    def clear(self):
        """会话切换时清空全部缓存。"""
        count = len(self._store)
        self._store.clear()
        self._order.clear()
        if count > 0:
            logger.debug("[消息缓存] 已清空 %d 条缓存", count)

    def update_order(self, ordered_ids: List[str]):
        """更新消息顺序（每轮 probe 后调用）。"""
        self._order = list(ordered_ids)

    def get_ordered_entries(self) -> List[Optional[CachedMessage]]:
        """按当前顺序返回缓存条目列表（未命中的位置为 None）。"""
        return [self._store.get(mid) for mid in self._order]

    def get_stats(self) -> dict:
        """返回缓存统计信息，用于日志。"""
        return {
            'cached_count': len(self._store),
            'order_count': len(self._order),
        }
