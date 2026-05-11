import pytest

def test_remote_protocol_smoke_import():
    m = pytest.importorskip('app.core.remote_worker', reason='PyQt/system libs unavailable in container', exc_type=ImportError)
    assert hasattr(m, '__file__')
