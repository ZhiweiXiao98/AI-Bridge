"""HTTP protocol tests use isolated paths and an in-memory authentication stub."""
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def server_module(tmp_path, monkeypatch):
    # Importing the real auth singleton would bootstrap persistent credentials.
    # These endpoint tests replace that boundary; auth regressions live in public_ci.
    auth_module = types.ModuleType('app.core.auth_service')
    auth_module.auth = MagicMock()
    auth_module.DB_PATH = str(tmp_path / 'unused.db')
    path = Path(__file__).resolve().parents[1] / 'server.py'
    monkeypatch.chdir(tmp_path)
    from app.core.config import ConfigManager
    monkeypatch.setattr(ConfigManager, 'load', staticmethod(lambda: {'export_image_path': str(tmp_path / 'images')}))
    spec = importlib.util.spec_from_file_location('_http_test_server', path)
    server = importlib.util.module_from_spec(spec)
    key = 'app.core.auth_service'
    previous = sys.modules.get(key)
    sys.modules[key] = auth_module
    try:
        spec.loader.exec_module(server)
    finally:
        if previous is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = previous
    server.app.dependency_overrides[server.verify_admin] = lambda: {'sub': 'fixture-admin', 'role': 'developer'}
    yield server
    server.app.dependency_overrides.clear()


def test_sync_messages_endpoint(server_module):
    server_module.LATEST_MESSAGES_DATA = [{'id': 1, 'text': 'Hello'}]
    with TestClient(server_module.app) as client:
        response = client.get('/api/sync/messages')
    assert response.status_code == 200
    assert response.json()[0]['text'] == 'Hello'


def test_sync_code_endpoint(server_module):
    server_module.LATEST_SYNC_DATA = {'file1.py': "print('code')"}
    with TestClient(server_module.app) as client:
        response = client.get('/api/sync/code')
    assert response.status_code == 200
    assert 'file1.py' in response.json()


def test_upload_endpoint(server_module):
    files = {'file': ('test.txt', b'test content', 'text/plain')}
    with TestClient(server_module.app) as client:
        response = client.post('/api/upload', files=files)
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'
    assert Path(response.json()['path']).read_bytes() == b'test content'
