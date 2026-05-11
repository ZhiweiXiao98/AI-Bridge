import pytest

def test_local_worker_smoke_import():
    m = pytest.importorskip('app.core.worker', reason='PyQt/system libs unavailable in container', exc_type=ImportError)
    assert hasattr(m, '__file__')
