# test-file: scripts/tests/test_apple_remote_patch.py
"""Apply reviewed text patches to a remote Git checkout without reset or clean.

This same dependency-free program runs locally in tests and over SSH in use.
Requests are JSON data on stdin; neither filenames nor patch text become code.
Only explicitly listed, hash-matched source files may change. Media stays local.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

MAX_BYTES = 1024 * 1024
MAX_FILES = 32
SOURCE_SUFFIXES = {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.svelte', '.json',
                   '.css', '.scss', '.html', '.md', '.yml', '.yaml', '.py', '.swift', '.txt'}


class PatchError(RuntimeError):
    pass


def git(root: Path, *args: str, patch: str | None = None) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], input=patch.encode() if patch is not None else None,
                            capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise PatchError('Git validation/apply failed; checkout and patch must match. No reset or clean was attempted.')
    return result.stdout


def checkout(value: str) -> Path:
    requested = Path(value)
    if not requested.is_absolute():
        raise PatchError('Repository must be an explicit absolute path')
    root = requested.resolve(strict=True)
    if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root:
        raise PatchError('Repository must be the Git checkout root')
    return root


def source_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or '\\' in name or any(ord(c) < 32 for c in name):
        raise PatchError('Invalid source path')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {'..', '.', '.git', '.ssh', 'node_modules'} or p.startswith('.env') for p in path.parts):
        raise PatchError('Source paths must stay inside the checkout and exclude private metadata')
    if str(path) != name or (path.suffix not in SOURCE_SUFFIXES and path.name != '.gitignore'):
        raise PatchError('Only explicit text source/config files may be patched; media is excluded')
    target = root
    for component in path.parts:
        target = target / component
        if target.is_symlink():
            raise PatchError('Symlink targets and symlink parents are not supported')
    if not target.resolve().is_relative_to(root):
        raise PatchError('Source path escapes checkout')
    return target


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_BYTES or path.stat().st_nlink != 1:
        raise PatchError('Source file is not a bounded regular file')
    content = path.read_bytes()
    content.decode('utf-8')
    return hashlib.sha256(content).hexdigest()


def execute(request: dict) -> dict:
    root = checkout(request['repo'])
    action = request.get('action')
    if action == 'snapshot':
        names = request.get('files')
        if not isinstance(names, list) or not 1 <= len(names) <= MAX_FILES:
            raise PatchError('List between 1 and 32 source files')
        return {'files': {name: digest(source_path(root, name)) for name in names}}
    if action != 'apply':
        raise PatchError('Unknown patch operation')
    expected, patch = request.get('expected'), request.get('patch')
    if not isinstance(expected, dict) or not 1 <= len(expected) <= MAX_FILES:
        raise PatchError('Expected hashes must list between 1 and 32 source files')
    if not isinstance(patch, str) or not patch or len(patch.encode()) > MAX_BYTES or '\x00' in patch:
        raise PatchError('Patch must be bounded UTF-8 text')
    if not isinstance(request.get('apply', False), bool):
        raise PatchError('Apply must be an explicit boolean')
    if re.search(r'^(?:GIT binary patch|Binary files |rename |copy |deleted file mode |old mode |new mode )', patch, re.M):
        raise PatchError('Binary changes, renames, deletions and mode changes are not supported')
    if re.search(r'^\+\+\+ /dev/null(?:\t.*)?$', patch, re.M):
        raise PatchError('Deleting source files is not supported')
    for mode in re.findall(r'^new file mode (\d+)$', patch, re.M):
        if mode != '100644':
            raise PatchError('New files must be regular non-executable text files')
    paths = {name: source_path(root, name) for name in expected}
    for value in expected.values():
        if value is not None and (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)):
            raise PatchError('Expected hash must be SHA-256 or null for a new file')
    # Git's own parser handles quoted filenames; -z makes path boundaries explicit.
    numstat = git(root, 'apply', '--numstat', '-z', '-', patch=patch)
    touched = []
    for row in numstat.split(b'\0'):
        if not row:
            continue
        fields = row.split(b'\t', 2)
        if len(fields) != 3 or fields[0] == b'-' or fields[1] == b'-':
            raise PatchError('Only text patches with ordinary file paths are supported')
        touched.append(fields[2].decode())
    if len(touched) != len(set(touched)) or set(touched) != set(expected):
        raise PatchError('Patch paths must exactly match the reviewed hash manifest')
    # Cross-client edits are detected even if a patch would still apply by context.
    git_dir = Path(git(root, 'rev-parse', '--absolute-git-dir').decode().strip())
    with (git_dir / 'openmates-patch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name, target in paths.items():
            source_path(root, name)
            if digest(target) != expected[name]:
                raise PatchError('Source changed since snapshot; read it again and prepare a fresh patch')
        git(root, 'apply', '--check', '--whitespace=nowarn', '-', patch=patch)
        if request.get('apply', False):
            git(root, 'apply', '--whitespace=nowarn', '-', patch=patch)
        return {'status': 'applied' if request.get('apply', False) else 'checked',
                'files': {name: digest(target) for name, target in paths.items()}}


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(2 * MAX_BYTES + 1)
        if len(raw) > 2 * MAX_BYTES:
            raise PatchError('Request too large')
        print(json.dumps(execute(json.loads(raw))))
        return 0
    except (PatchError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        # Never echo source contents or private absolute remote paths on failure.
        print(json.dumps({'error': str(exc) if isinstance(exc, PatchError) else 'Invalid patch request or inaccessible checkout'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
