import os
from pathlib import Path
import subprocess
import sys


def test_offline_mode_blocks_collection_network_and_removes_credentials(tmp_path):
    # Exercise a fresh pytest process: fixtures cannot protect imports during collection.
    (tmp_path / "conftest.py").write_text(
        Path(__file__).with_name("conftest.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "test_collection.py").write_text(
        "import os, socket\n"
        "assert 'OPENAI_API_KEY' not in os.environ\n"
        "assert os.environ['TIKTOKEN_CACHE_DIR'] == 'offline-cache'\n"
        "socket.socket()\n",
        encoding="utf-8",
    )
    env = dict(os.environ, OPENAI_API_KEY="test-only-placeholder", TIKTOKEN_CACHE_DIR="offline-cache")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "--disable-socket", "--allow-unix-socket", "-q"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "SocketBlockedError" in result.stdout


def test_offline_mode_blocks_network_in_fixture_finalizers(tmp_path):
    (tmp_path / "conftest.py").write_text(
        Path(__file__).with_name("conftest.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "test_finalizer.py").write_text(
        "import pytest, socket\n"
        "from pytest_socket import SocketBlockedError\n"
        "@pytest.fixture(autouse=True)\n"
        "def guarded():\n"
        "    yield\n"
        "    with pytest.raises(SocketBlockedError):\n"
        "        socket.socket()\n"
        "def test_first(): pass\n"
        "def test_second(): pass\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "--disable-socket", "--allow-unix-socket", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
