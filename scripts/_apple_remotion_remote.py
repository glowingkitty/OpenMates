#!/usr/bin/env python3
"""Typed, dependency-free Mac source and Remotion inspection operations.

Delivered as fixed reviewed Python code; all caller values arrive as JSON data.
No shell, package installation, cleanup or arbitrary program execution is exposed.
Source updates retain a backup and write the existing inode, never git apply or
rename. The sandbox probe queries policy only and never attempts deletion.
"""
from __future__ import annotations
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import uuid

MAX_BYTES = 1024 * 1024
SOURCE_SUFFIXES = {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.css', '.json', '.txt', '.svg'}
AUDIT_FILES = (
    'node_modules/@remotion/renderer/package.json',
    'node_modules/@remotion/renderer/dist/delete-directory.js',
    'node_modules/@remotion/renderer/dist/browser/BrowserRunner.js',
    'node_modules/@remotion/renderer/dist/render-media.js',
    'node_modules/@remotion/renderer/dist/combine-video-streams.js',
    'node_modules/@remotion/renderer/dist/combine-audio.js',
)
# A global, unqualified deny: no exceptions for temporary/output/cache files.
PROBE_PROFILE = '(version 1)(allow default)(deny file-write*)'
PROBE_CODE = r'''
import ctypes,json,os,subprocess,sys
lib=ctypes.CDLL('/usr/lib/libsandbox.dylib')
check=lib.sandbox_check
check.restype=ctypes.c_int
check.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int]
paths=['/','/tmp','/Users','/Volumes',sys.argv[1]]
rows=[{'path_index':i,'read':check(os.getpid(),b'file-read-data',1,p.encode()),'unlink':check(os.getpid(),b'file-write-unlink',1,p.encode()),'create':check(os.getpid(),b'file-write-create',1,p.encode())} for i,p in enumerate(paths)]
print(json.dumps(rows))
sys.exit(0 if all(r['read']==0 and r['unlink']>0 and r['create']>0 for r in rows) else 3)
'''


class RequestError(ValueError):
    pass


def root_path(value):
    if not isinstance(value, str) or not value.startswith('/'):
        raise RequestError('repo must be an absolute Remotion project directory')
    p = Path(value)
    if '..' in p.parts or p.name != 'remotion' or p.parent.name != 'videos':
        raise RequestError('repo must end in videos/remotion without traversal')
    for part in [p, *p.parents]:
        if part.is_symlink():
            raise RequestError('symlink repository paths are not supported')
    if not p.is_dir():
        raise RequestError('Remotion project directory is unavailable')
    return p


def source_name(value):
    if not isinstance(value, str):
        raise RequestError('source path must be text')
    p = PurePosixPath(value)
    if (str(p) != value or p.is_absolute() or '..' in p.parts
            or not p.parts or not (p.parts[0] == 'src' or p.parts[:2] == ('public', 'announcement-assets')) or p.suffix not in SOURCE_SUFFIXES):
        raise RequestError('only src/ and public/announcement-assets text files are supported')
    return p.parts


def open_source(root, name, flags, create_parents=False):
    # Resolve every component through directory descriptors, rejecting symlink
    # races rather than resolving a path and reopening it by its pathname.
    parts = source_name(name)
    current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            if create_parents:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        return os.open(parts[-1], flags | os.O_NOFOLLOW, 0o600, dir_fd=current)
    finally:
        os.close(current)


def read_fd(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
        raise RequestError('source must be a bounded, non-hardlinked regular file')
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, MAX_BYTES + 1)
    data.decode('utf-8')
    return data


def source(root, request):
    name = request.get('file')
    writing = request['action'] == 'source-put'
    content = request.get('content')
    if writing and (not isinstance(content, str) or len(content.encode()) > MAX_BYTES):
        raise RequestError('source content must be bounded UTF-8')
    creating = writing and request.get('expected_sha256', 'missing') is None
    if writing and 'expected_sha256' not in request:
        raise RequestError('expected_sha256 is required (null only for exclusive creation)')
    flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL) if creating else (os.O_RDWR if writing else os.O_RDONLY)
    fd = open_source(root, name, flags, create_parents=creating)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if writing else fcntl.LOCK_SH)
        before = read_fd(fd)
        digest = hashlib.sha256(before).hexdigest()
        if not writing:
            return {'file': name, 'sha256': digest, 'content': before.decode()}
        if not creating and request.get('expected_sha256') != digest:
            raise RequestError('source changed; read it again before updating')
        data = content.encode()
        if not creating and data == before:
            return {'file': name, 'sha256': digest, 'status': 'unchanged'}
        backup_name = None
        if not creating:
            backup_name = str(PurePosixPath(name).with_name(PurePosixPath(name).name + '.retained-' + uuid.uuid4().hex + '.txt'))
            backup_fd = open_source(root, backup_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(backup_fd, 'wb') as backup:
                backup.write(before)
                backup.flush()
                os.fsync(backup.fileno())
        # No replace/rename/unlink. The backup survives success and failure.
        os.lseek(fd, 0, os.SEEK_SET)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if not written:
                raise OSError('short source write')
            view = view[written:]
        os.ftruncate(fd, len(data))
        os.fsync(fd)
        return {'file': name, 'sha256': hashlib.sha256(data).hexdigest(), 'status': 'created' if creating else 'updated', 'retained_backup': backup_name}
    finally:
        os.close(fd)


def inspect(root):
    result = {'platform': sys.platform, 'audit': {}, 'assets': []}
    for name in AUDIT_FILES:
        path = root / name
        if path.is_file() and path.stat().st_size <= MAX_BYTES:
            data = path.read_bytes()
            result['audit'][name] = {'sha256': hashlib.sha256(data).hexdigest(), 'content': data.decode()}
    assets = root / 'input-media/announcement-video'
    if assets.is_dir():
        result['assets'] = [{'name': p.name, 'bytes': p.stat().st_size} for p in assets.iterdir() if p.is_file()]
    result['sandbox_exec'] = Path('/usr/bin/sandbox-exec').is_file()
    result['sandbox_man'] = None
    for path in [Path('/usr/share/man/man1/sandbox-exec.1'), Path('/usr/share/man/man1/sandbox-exec.1.gz')]:
        if path.is_file():
            data = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
            result['sandbox_man'] = data.decode(errors='replace')[:12000]
            break
    return result


def execute(request):
    if not isinstance(request, dict) or request.get('action') not in {'inspect', 'source-read', 'source-put', 'sandbox-probe'}:
        raise RequestError('unsupported typed operation')
    root = root_path(request.get('repo'))
    if request['action'] in {'source-read', 'source-put'}:
        return source(root, request)
    if request['action'] == 'inspect':
        return inspect(root)
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise RequestError('macOS sandbox-exec is unavailable; render remains disabled')
    command = ['/usr/bin/sandbox-exec', '-p', PROBE_PROFILE, sys.executable, '-I', '-B', '-c', PROBE_CODE, str(root)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise RequestError('sandbox query failed; render remains disabled: ' + result.stderr[:400])
    return {'status': 'read-only-policy-verified', 'checks': json.loads(result.stdout),
            'render_enabled': False, 'note': 'Policy query is not a retention audit or permission to attempt deletion.'}


def main():
    try:
        raw = sys.stdin.buffer.read(2 * MAX_BYTES + 1)
        if len(raw) > 2 * MAX_BYTES:
            raise RequestError('request exceeds limit')
        print(json.dumps(execute(json.loads(raw))))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
