"""Fail closed for known private/runtime paths in the public tracked tree.

This is a publication guard, not a substitute for human privacy/license review.
Only tracked bytes are scanned; findings print paths and rule names, never values.
"""
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {
    '.workbuddy', '.claude', '.codebuddy', '.trae', '.config', '.worktrees',
    'node_modules', 'venv', '.venv', '__pycache__', 'logs', 'knowledge_bases',
    '_knowledge_base', '_knowledge_base_v2', 'chrome_user_data', 'temp_uploads',
}
BLOCKED_NAMES = {
    '.env', '.secret.key', 'config.json', 'server_config.json', 'session_states.json',
    'AI_JOURNAL.md', 'AI_README.md', 'AGENT.md', 'AGENTS.md',
}
BLOCKED_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.log', '.pyc', '.pem', '.p12', '.pfx'}
SECRET_PATTERNS = {
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'provider-key': re.compile(rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b'),
    'aws-access-key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
}


def path_problem(path):
    p = PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts:
        return 'unsafe-path'
    if any(part in BLOCKED_PARTS for part in p.parts):
        return 'private-or-runtime-directory'
    if p.name in BLOCKED_NAMES or p.name.startswith('.env.') and p.name != '.env.example':
        return 'private-configuration'
    if p.suffix.lower() in BLOCKED_SUFFIXES:
        return 'private-or-runtime-file'
    if path.startswith(('docs/归档/', 'docs/导出HTML/', 'export/', 'screenshots/')):
        return 'private-output-or-history'
    return None


def content_problems(data):
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(data)]


def main():
    output = subprocess.check_output(['git', 'ls-files', '-z', '--stage'], cwd=ROOT)
    problems = []
    count = 0
    for record in output.decode('utf-8').split('\0'):
        if not record:
            continue
        metadata, path = record.split('\t', 1)
        mode = metadata.split()[0]
        count += 1
        issue = path_problem(path)
        if issue:
            problems.append((path, issue))
        if mode in {'120000', '160000'}:
            problems.append((path, 'symlink-or-submodule'))
            continue
        for issue in content_problems((ROOT / path).read_bytes()):
            problems.append((path, issue))
    for path, issue in problems:
        print(f'{path}: {issue}', file=sys.stderr)
    if problems:
        return 1
    print(f'Public export guard passed: {count} tracked files; human review still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
