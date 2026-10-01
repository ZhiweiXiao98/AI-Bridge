"""Shared lightweight test doubles."""


class RecordingSignal:
    """Small Qt-like signal stub that records emitted payloads."""

    def __init__(self):
        self.payloads = []
        self.items = self.payloads

    def emit(self, *args):
        payload = args[0] if len(args) == 1 else args
        self.payloads.append(payload)


class RecordingLock:
    """Minimal QMutex-like lock stub for bridge tests."""

    def __init__(self, allowed=True):
        self.allowed = allowed
        self.unlock_count = 0

    def tryLock(self):
        return self.allowed

    def unlock(self):
        self.unlock_count += 1
