"""Dependency-free, offline tests. No application import or service connection."""
import ast
import asyncio
import binascii
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from datetime import datetime
from unittest.mock import patch
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


def load_definition(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if getattr(n, 'name', None) == name)
    node.decorator_list = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.returns = None
        for arg in node.args.args:
            arg.annotation = None
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, path, 'exec'), namespace)
    return namespace[name]


class Connected(Exception):
    pass


class FakeSocket:
    def __init__(self):
        self.closed = None
        self.client = types.SimpleNamespace(host='203.0.113.7')

    async def close(self, code):
        self.closed = code


class FakeManager:
    def __init__(self):
        self.connected = False
        self.identity = None

    async def connect(self, *args):
        self.connected = True
        self.identity = args
        raise Connected()


class AuthenticationTests(unittest.TestCase):
    def endpoint(self, payload):
        manager = FakeManager()
        fn = load_definition('server.py', 'websocket_endpoint', {
            'auth': types.SimpleNamespace(decode_token=lambda _: payload),
            'manager': manager,
        })
        return fn, manager

    def test_invalid_tokens_cannot_connect(self):
        for token in ('admin', '', 'invalid-jwt'):
            with self.subTest(token=token):
                fn, manager = self.endpoint(None)
                socket = FakeSocket()
                asyncio.run(fn(socket, token, 'test-device'))
                self.assertEqual(socket.closed, 1008)
                self.assertFalse(manager.connected)

    def test_signed_payload_needs_nonempty_identity(self):
        for payload in ({'role': 'developer'}, {'sub': ''}, {'sub': ' '}, {'sub': 42}):
            with self.subTest(payload=payload):
                fn, manager = self.endpoint(payload)
                socket = FakeSocket()
                asyncio.run(fn(socket, 'signed-test-token', 'test-device'))
                self.assertEqual(socket.closed, 1008)
                self.assertFalse(manager.connected)

    def test_valid_developer_reaches_authenticated_connect(self):
        fn, manager = self.endpoint({'sub': 'fixture-admin', 'role': 'developer'})
        with self.assertRaises(Connected):
            asyncio.run(fn(FakeSocket(), 'signed-test-token', 'test-device'))
        self.assertEqual(manager.identity[1:4], ('admin', 'test-device', 'fixture-admin'))

    def test_valid_user_does_not_gain_developer_group(self):
        fn, manager = self.endpoint({'sub': 'fixture-user', 'role': 'user'})
        with self.assertRaises(Connected):
            asyncio.run(fn(FakeSocket(), 'signed-test-token', 'test-device'))
        self.assertEqual(manager.identity[1], 'user')

    def test_constants_have_no_implicit_bootstrap_password(self):
        with patch.dict(os.environ, {}, clear=True):
            namespace = {'__file__': str(ROOT / 'app/core/app_constants.py')}
            exec((ROOT / 'app/core/app_constants.py').read_text(encoding='utf-8'), namespace)
            self.assertEqual(namespace['DEFAULT_AUTH_CREDENTIALS'], {})

    def init_database(self, path, credentials):
        cls = load_definition('app/core/auth_service.py', 'AuthService', {
            'os': os, 'sqlite3': sqlite3, 'hashlib': hashlib, 'binascii': binascii,
            'datetime': datetime, 'Optional': Optional, 'List': list,
            'DEFAULT_AUTH_CREDENTIALS': credentials, 'DB_PATH': str(path),
        })
        instance = cls.__new__(cls)
        instance._init_db()
        return instance

    def test_empty_database_requires_explicit_strong_password(self):
        for password in ('', 'admin', 'changeme', 'too-short', ' ' * 12):
            with self.subTest(case=bool(password)), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(RuntimeError, 'AUTH_ADMIN_PASSWORD'):
                    self.init_database(Path(tmp) / 'test.db', {'admin': {'password': password}})

    def test_bootstrap_and_existing_database_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'test.db'
            self.init_database(db, {'admin': {'password': 'unit-test-only-password'}})
            with sqlite3.connect(db) as conn:
                before = conn.execute('SELECT * FROM users').fetchall()
            self.init_database(db, {})
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT * FROM users').fetchall(), before)


class ExportGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('export_guard', ROOT / 'tools/check_public_tree.py')
        cls.guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.guard)

    def test_rejects_private_runtime_paths(self):
        for path in ('config.json', '.env', '.env.local', '.secret.key', 'user_data.db',
                     'logs/run.log', '.workbuddy/memory/day.md', 'export/image.png',
                     'runtime/pi/node_modules/package/index.js', 'AI_JOURNAL.md'):
            with self.subTest(path=path):
                self.assertIsNotNone(self.guard.path_problem(path))

    def test_retains_public_examples_license_and_source(self):
        for path in ('.env.example', 'config.example.json', 'LICENSE', 'app/core/config.py',
                     'config/api_mode.example.json', 'runtime/pi/package-lock.json'):
            with self.subTest(path=path):
                self.assertIsNone(self.guard.path_problem(path))

    def test_detects_secret_shapes_without_printing_values(self):
        for prefix, length in ((b'ghp_', 36), (b'sk-', 40), (b'AKIA', 16)):
            self.assertTrue(self.guard.content_problems(prefix + b'A' * length))


if __name__ == '__main__':
    unittest.main()
