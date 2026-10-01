def __getattr__(name):
    if name == "WorkerThread":
        from app.core.worker import WorkerThread
        return WorkerThread
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["WorkerThread"]
