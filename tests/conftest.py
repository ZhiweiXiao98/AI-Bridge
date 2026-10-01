"""
Pytest 配置和 Fixtures
"""
import os
import re

import pytest


def _block_network(config):
    if config.getoption("disable_socket", default=False):
        import pytest_socket

        pytest_socket.disable_socket(
            allow_unix_socket=config.getoption("allow_unix_socket", default=False)
        )


def pytest_sessionstart(session):
    """Block collection-time network calls too when running offline CI."""
    if session.config.getoption("disable_socket", default=False):
        for key in list(os.environ):
            if re.search(r"(^|_)(API_KEY|TOKEN|SECRET|PASSWORD)(_|$)", key.upper()):
                os.environ.pop(key)
        # Keep the lock throughout fixture finalizers and between tests. The
        # plugin's teardown hook otherwise restores sockets before finalizers run.
        socket_plugin = session.config.pluginmanager.get_plugin("socket")
        if socket_plugin is not None:
            session.config.pluginmanager.unregister(socket_plugin)
        _block_network(session.config)


def _load_docker():
    try:
        import docker
    except Exception:
        return None
    return docker

def pytest_configure(config):
    """注册自定义标记"""
    config.addinivalue_line(
        "markers", "docker: 需要 Docker 环境的测试"
    )

@pytest.fixture(scope="session")
def docker_available():
    """检查 Docker 是否可用"""
    docker = _load_docker()
    if docker is None:
        return False
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False

@pytest.fixture(scope="session")
def docker_client(docker_available):
    """提供 Docker 客户端"""
    if not docker_available:
        pytest.skip("Docker not available")
    docker = _load_docker()
    return docker.from_env()

def pytest_collection_modifyitems(config, items):
    """自动跳过需要 Docker 但 Docker 不可用的测试"""
    docker = _load_docker()
    if docker is None:
        docker_available = False
    else:
        try:
            client = docker.from_env()
            client.ping()
            docker_available = True
        except Exception:
            docker_available = False

    if not docker_available:
        skip_docker = pytest.mark.skip(reason="Docker not available")
        for item in items:
            if "docker" in item.keywords or "DockerSandbox" in str(item.fspath):
                item.add_marker(skip_docker)
