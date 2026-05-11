# filename: app/core/browser_sync/seq.py
"""单调递增 seq 生成器。

每个 Worker 实例持有一个 SeqGenerator，每次事件推送时递增。
seq 用于客户端检测事件缺失、乱序、重复。
"""

import threading


class SeqGenerator:
    """线程安全的单调递增 seq 生成器。"""

    def __init__(self, start: int = 0):
        self._seq = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    @property
    def current(self) -> int:
        return self._seq

    def reset(self, start: int = 0):
        with self._lock:
            self._seq = start
