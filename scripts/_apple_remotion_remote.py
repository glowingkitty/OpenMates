#!/usr/bin/env python3
"""Typed, dependency-free Mac source and Remotion inspection operations.

Delivered as fixed reviewed Python code; all caller values arrive as JSON data.
No shell, package installation, cleanup or arbitrary program execution is exposed.
Source updates retain a backup and write the existing inode, never git apply or
rename. The sandbox probe queries policy only and never attempts deletion.
"""
from __future__ import annotations
import fcntl
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import signal
import time
import uuid

MAX_BYTES = 1024 * 1024
MEDIA_ROOTS = ('input-media/announcement-video', 'renders/mac-local/announcement-video/originals')
READ_FILES = {'package.json', 'remotion.config.ts', 'tsconfig.json'}
RELOCATION_FILES = {'gemini_find_doctor_appointments.mov', 'openmates_is_better.mov'}
RENAME_EXCL = 0x00000004
RENAME_NOFOLLOW_ANY = 0x00000010
RENAME_RESOLVE_BENEATH = 0x00000020
RENDER_CODE = None
RENDER_PROFILE = '(version 1)(allow default)(deny file-write-unlink (with send-signal SIGKILL))'
SOURCE_SUFFIXES = {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.css', '.json', '.txt', '.svg'}
AUDIT_FILES = (
    'node_modules/@remotion/renderer/package.json',
    'node_modules/@remotion/renderer/dist/delete-directory.js',
    'node_modules/@remotion/renderer/dist/browser/BrowserRunner.js',
    'node_modules/@remotion/renderer/dist/render-media.js',
    'node_modules/@remotion/renderer/dist/combine-video-streams.js',
    'node_modules/@remotion/renderer/dist/combine-audio.js',
    'node_modules/@remotion/renderer/dist/open-browser.js',
    'node_modules/@remotion/renderer/dist/render-frames.js',
    'node_modules/@remotion/renderer/dist/prepare-server.js',
    'node_modules/@remotion/bundler/dist/bundle.js',
)
# A global, unqualified deny: no exceptions for temporary/output/cache files.
PROBE_PROFILE = '(version 1)(allow default)(deny file-write*)'
NO_UNLINK_PROFILE = '(version 1)(allow default)(deny file-write-unlink (with send-signal SIGKILL))'
PROBE_CODE = r'''
import ctypes,json,os,subprocess,sys
lib=ctypes.CDLL('/usr/lib/libsandbox.dylib')
check=lib.sandbox_check
check.restype=ctypes.c_int
check.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int]
paths=['/','/tmp','/Users','/Volumes',sys.argv[1]]
rows=[{'path_index':i,'read':check(os.getpid(),b'file-read-data',1,p.encode()),'unlink':check(os.getpid(),b'file-write-unlink',1,p.encode()),'create':check(os.getpid(),b'file-write-create',1,p.encode())} for i,p in enumerate(paths)]
expected_create=int(sys.argv[3])
depth=int(sys.argv[4])
valid=all(r['read']==0 and r['unlink']>0 and (r['create']>0 if expected_create else (r['create']==0 if r['path_index'] in (1,4) else True)) for r in rows)
child=None
if valid and depth<2:
    result=subprocess.run([sys.executable,'-I','-B','-c',sys.argv[2],sys.argv[1],sys.argv[2],sys.argv[3],str(depth+1)],capture_output=True,text=True,timeout=10)
    valid=result.returncode==0
    child=json.loads(result.stdout) if result.stdout else None
print(json.dumps({'depth':depth,'checks':rows,'child':child}))
sys.exit(0 if valid else 3)
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
    result['manifests'] = {}
    for location in MEDIA_ROOTS:
        assets = root / location
        if not assets.is_dir() or assets.is_symlink():
            continue
        pending = [(assets, 0)]
        while pending:
            directory, depth = pending.pop()
            for p in sorted(directory.iterdir()):
                if p.is_symlink():
                    continue
                if p.is_dir() and depth < 3:
                    pending.append((p, depth + 1))
                elif p.is_file():
                    name = p.relative_to(root).as_posix()
                    result['assets'].append({'file': name, 'bytes': p.stat().st_size})
                    if p.name == 'media-manifest.json' and p.stat().st_size <= MAX_BYTES:
                        result['manifests'][name] = json.loads(p.read_text())
                if len(result['assets']) + len(pending) > 500:
                    raise RequestError('media inspection exceeds bounded inventory')
    result['sandbox_exec'] = Path('/usr/bin/sandbox-exec').is_file()
    result['installed_tools'] = {}
    for relative in ('node_modules/@remotion/compositor-darwin-arm64', 'node_modules/@remotion/compositor-darwin-x64', 'node_modules/.remotion'):
        base = root / relative
        if base.is_dir() and not base.is_symlink():
            result['installed_tools'][relative] = sorted(p.name for p in base.iterdir())[:50]
    result['sandbox_man'] = None
    for path in [Path('/usr/share/man/man1/sandbox-exec.1'), Path('/usr/share/man/man1/sandbox-exec.1.gz')]:
        if path.is_file():
            data = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
            result['sandbox_man'] = data.decode(errors='replace')[:12000]
            break
    return result


def media_path(root, name):
    if not isinstance(name, str):
        raise RequestError('media file is required')
    p = PurePosixPath(name)
    if str(p) != name or p.is_absolute() or '..' in p.parts or not any(name.startswith(prefix + '/') for prefix in MEDIA_ROOTS):
        raise RequestError('media must be within an approved original-media directory')
    path = root / name
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise RequestError('symlink media paths are unsupported')
    if not path.is_file() or path.suffix.lower() not in {'.mov', '.mp4', '.m4v', '.wav', '.mp3'}:
        raise RequestError('unsupported original media file')
    return path


def open_directory(path):
    current = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        result = current
        current = None
        return result
    finally:
        if current is not None:
            os.close(current)


def file_identity(fd):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise RequestError('relocation requires one non-hardlinked regular file')
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        data = os.read(fd, MAX_BYTES)
        if not data:
            break
        digest.update(data)
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise RequestError('original changed while hashing')
    return {'device': before.st_dev, 'inode': before.st_ino, 'bytes': before.st_size, 'sha256': digest.hexdigest()}


def rename_exclusive(source_dir, name, destination_dir):
    if sys.platform != 'darwin':
        raise RequestError('atomic no-overwrite Mac rename unavailable')
    library = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    rename = getattr(library, 'renameatx_np', None)
    if rename is None:
        raise RequestError('renameatx_np unavailable; no fallback allowed')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    flags = RENAME_EXCL | RENAME_NOFOLLOW_ANY | RENAME_RESOLVE_BENEATH
    if rename(source_dir, name.encode(), destination_dir, name.encode(), flags) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def relocate(root, request):
    name = request.get('file')
    if name not in RELOCATION_FILES:
        raise RequestError('only the two explicitly authorized original filenames may relocate')
    source = MEDIA_ROOTS[1]
    destination = MEDIA_ROOTS[0] + '/originals'
    source_dir = open_directory(root / source)
    try:
        destination_dir = open_directory(root / destination)
        try:
            if os.fstat(source_dir).st_dev != os.fstat(destination_dir).st_dev:
                raise RequestError('cross-device relocation refused; no copy/unlink fallback')
            try:
                os.stat(name, dir_fd=destination_dir, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise RequestError('destination exists; never overwrite or delete it')
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_dir)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                before = file_identity(fd)
                if before['device'] != os.fstat(destination_dir).st_dev:
                    raise RequestError('cross-device source refused')
                result = {'source': source + '/' + name, 'destination': destination + '/' + name, 'identity': before}
                if request['action'] == 'relocation-info':
                    return result
                if request.get('expected') != before:
                    raise RequestError('original identity/hash mismatch; inspect again')
                linked = os.stat(name, dir_fd=source_dir, follow_symlinks=False)
                if (linked.st_dev, linked.st_ino) != (before['device'], before['inode']):
                    raise RequestError('source pathname changed before rename')
                rename_exclusive(source_dir, name, destination_dir)
                after_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=destination_dir)
                try:
                    after = file_identity(after_fd)
                finally:
                    os.close(after_fd)
                if after != before:
                    raise RequestError('post-relocation identity mismatch; no automatic rollback')
                result.update(status='relocated', verified_identity=after)
                return result
            finally:
                os.close(fd)
        finally:
            os.close(destination_dir)
    finally:
        os.close(source_dir)


def sandbox_query(root, profile=PROBE_PROFILE):
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise RequestError('macOS sandbox-exec is unavailable; render remains disabled')
    command = ['/usr/bin/sandbox-exec', '-p', profile, sys.executable, '-I', '-B', '-c', PROBE_CODE, str(root), PROBE_CODE, '1' if profile == PROBE_PROFILE else '0', '0']
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise RequestError('sandbox query failed; render remains disabled: '
                           + json.dumps({'profile': 'read-only' if profile == PROBE_PROFILE else 'no-unlink',
                                         'exit_code': result.returncode, 'stderr': result.stderr[:400],
                                         'query_output': result.stdout[:5000]}))
    return json.loads(result.stdout)


def media_probe(root, request):
    path = media_path(root, request.get('file'))
    sandbox_query(root)
    binary = next((p for p in (Path('/opt/homebrew/bin/ffprobe'), Path('/usr/local/bin/ffprobe'),
                              root / 'node_modules/@remotion/compositor-darwin-arm64/ffprobe',
                              root / 'node_modules/@remotion/compositor-darwin-x64/ffprobe') if p.is_file()), None)
    if binary is None:
        raise RequestError('installed ffprobe unavailable; no installation allowed')
    # ffprobe reads existing media only, with network protocols and all filesystem
    # writes denied. No renderer, decoder output, report files or cleanup invoked.
    command = ['/usr/bin/sandbox-exec', '-p', PROBE_PROFILE, str(binary), '-v', 'error',
               '-protocol_whitelist', 'file', '-show_format', '-show_streams', '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False, cwd=str(binary.parent),
                            env={'PATH': '/usr/bin:/bin', 'AV_LOG_FORCE_NOCOLOR': '1'})
    if result.returncode:
        raise RequestError('read-only ffprobe failed: ' + result.stderr[:400])
    return {'file': request['file'], 'metadata': json.loads(result.stdout)}


def process_group_states(group):
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,pgid=,stat='], capture_output=True,
                            text=True, timeout=5, check=True)
    rows = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] == str(group):
            rows.append({'pid': int(fields[0]), 'state': fields[2]})
    return rows


def observed_process(command, run, *, input_data, env, probe=False, task_stop=None):
    # Retained logs avoid pipe backpressure. All launched descendants inherit
    # the OS policy; Node additionally prevents detached child groups.
    with (run / 'stdout.log').open('xb') as output, (run / 'stderr.log').open('xb') as errors:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output, stderr=errors,
                                 env=env, start_new_session=True)
        try:
            child.stdin.write(input_data)
            child.stdin.close()
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                states = process_group_states(child.pid)
                stopped = [row for row in states if 'T' in row['state']]
                explicit_stop = run / 'stop.json'
                if explicit_stop.exists():
                    detail = json.loads(explicit_stop.read_text())
                    if task_stop is not None and not task_stop.exists():
                        with task_stop.open('x') as marker:
                            json.dump(detail, marker)
                    return {'status': 'deletion-stopped', 'detail': detail}
                if stopped:
                    if probe:
                        return {'status': 'harmless-read-denial-stopped', 'stopped_processes': stopped}
                    # Only the Node supervisor may intentionally stop after a
                    # written outcome. A stopped native child is always terminal.
                    native = [row for row in stopped if row['pid'] != child.pid]
                    if not native and (run / 'result.json').is_file():
                        return json.loads((run / 'result.json').read_text())
                    if not native and (run / 'failure.json').is_file():
                        return {'status': 'render-failed', **json.loads((run / 'failure.json').read_text())}
                    detail = {'reason': 'OS no-unlink policy stopped a native render process; no deletion retry',
                              'stopped_processes': stopped, 'manual_delete_command': None}
                    with explicit_stop.open('x') as marker:
                        json.dump(detail, marker)
                    if task_stop is not None:
                        with task_stop.open('x') as marker:
                            json.dump(detail, marker)
                    return {'status': 'deletion-stopped', 'detail': detail}
                if child.poll() is not None:
                    if probe and child.returncode == -signal.SIGKILL:
                        return {'status': 'harmless-read-denial-killed', 'exit_code': child.returncode}
                    if probe and child.returncode == 0 and (run / 'stdout.log').read_text().strip() == '{"fork_denied": true, "errno": 1}':
                        return {'status': 'native-fork-denial-verified', 'exit_code': 0}
                    if not probe and child.returncode == -signal.SIGKILL:
                        detail = {'reason': 'OS policy killed render supervisor; no automatic retry', 'exit_code': child.returncode}
                        with (run / 'stop.json').open('x') as marker:
                            json.dump(detail, marker)
                        if task_stop is not None:
                            with task_stop.open('x') as marker:
                                json.dump(detail, marker)
                        return {'status': 'deletion-stopped', 'detail': detail}
                    return {'status': 'render-failed', 'exit_code': child.returncode,
                            'stderr': (run / 'stderr.log').read_text(errors='replace')[-3000:]}
                time.sleep(0.05)
            return {'status': 'render-failed', 'error': 'bounded render check timed out; artifacts retained'}
        finally:
            # SIGKILL avoids native/user-space cleanup handlers. Never unlink
            # profiles, logs, frames, output or supervisor evidence.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=10)


def render_check(root, request):
    if RENDER_CODE is None:
        raise RequestError('fixed render helper was not supplied by wrapper')
    sandbox_query(root, RENDER_PROFILE)
    node = next((p for p in (Path('/opt/homebrew/bin/node'), Path('/usr/local/bin/node')) if p.is_file()), None)
    browser = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    encoder = root / 'node_modules/@remotion/compositor-darwin-arm64/ffmpeg'
    if request['action'] != 'supervisor-probe' and (node is None or not browser.is_file() or not encoder.is_file()):
        raise RequestError('required installed Node/Chrome/compositor encoder unavailable; no downloads')
    task = request.get('_task_identity')
    if not isinstance(task, str) or not task:
        raise RequestError('render requires wrapper-bound task identity')
    parent = root / 'renders/no-delete-retained'
    renders = root / 'renders'
    if not renders.exists():
        renders.mkdir()
    fd = open_directory(renders)
    os.close(fd)
    parent.mkdir(exist_ok=True)
    # Reject symlink parents before creating any run artifacts.
    fd = open_directory(parent)
    os.close(fd)
    capability_key = hashlib.sha256((RENDER_CODE + RENDER_PROFILE).encode()).hexdigest()
    def capability(kind):
        return parent / ('capability-' + capability_key + '-' + kind + '.json')
    if request['action'] == 'render-check':
        for kind, expected in [('read', 'harmless-read-denial-killed'), ('fork', 'native-fork-denial-verified')]:
            proof = capability(kind)
            if not proof.is_file() or json.loads(proof.read_text()).get('status') != expected:
                raise RequestError('required harmless supervisor proof missing for current runner: ' + kind)
    run = parent / uuid.uuid4().hex
    run.mkdir(mode=0o700)
    env = {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin', 'TMPDIR': str(run / 'tmp')}
    (run / 'tmp').mkdir()
    (run / 'empty-public').mkdir()
    if request['action'] == 'supervisor-probe':
        # Actual denied READ only, no deletion fixture/syscall. This checks the
        # supervisor's SIGSTOP observation using an existing harmless device.
        profile = '(version 1)(allow default)(deny file-read-data (with send-signal SIGKILL) (literal "/dev/null"))'
        code = 'import os; f=os.open("/dev/null",os.O_RDONLY); os.read(f,1)'
        if request.get('probe_kind', 'read') == 'fork':
            profile = '(version 1)(allow default)(deny process-fork)'
            code = 'import os,json\ntry:\n pid=os.fork(); os._exit(3)\nexcept OSError as e:\n print(json.dumps({"fork_denied":e.errno==1,"errno":e.errno}))'
        elif request.get('probe_kind', 'read') != 'read':
            raise RequestError('unsupported harmless supervisor probe')
        command = ['/usr/bin/sandbox-exec', '-p', profile, sys.executable, '-I', '-B', '-c',
                   code]
        result = observed_process(command, run, input_data=b'', env=env, probe=True)
        result['probe_kind'] = request.get('probe_kind', 'read')
    else:
        command = ['/usr/bin/sandbox-exec', '-p', RENDER_PROFILE, str(node), '-e', RENDER_CODE]
        payload = json.dumps({'root': str(root), 'run': str(run), 'browser': str(browser), 'encoder': str(encoder)}).encode()
        task_stop = parent / ('task-' + hashlib.sha256(task.encode()).hexdigest() + '.stop.json')
        result = observed_process(command, run, input_data=payload, env=env, task_stop=task_stop)
    result['run'] = str(run)
    with (run / 'supervisor-result.json').open('x') as artifact:
        json.dump(result, artifact)
    if request['action'] == 'supervisor-probe' and result['status'] in {'harmless-read-denial-killed', 'native-fork-denial-verified'}:
        proof = capability(request.get('probe_kind', 'read'))
        if not proof.exists():
            with proof.open('x') as artifact:
                json.dump(result, artifact)
    return result


def execute(request):
    if not isinstance(request, dict) or request.get('action') not in {'inspect', 'source-read', 'source-put', 'sandbox-probe', 'media-probe', 'config-read', 'relocation-info', 'relocate-original', 'supervisor-probe', 'render-check'}:
        raise RequestError('unsupported typed operation')
    root = root_path(request.get('repo'))
    task = request.get('_task_identity')
    if isinstance(task, str) and task:
        task_stop = root / 'renders/no-delete-retained' / ('task-' + hashlib.sha256(task.encode()).hexdigest() + '.stop.json')
        if task_stop.exists():
            return {'status': 'deletion-stopped', 'detail': json.loads(task_stop.read_text()), 'persistent_stop': str(task_stop)}
    if request['action'] in {'supervisor-probe', 'render-check'}:
        return render_check(root, request)
    if request['action'] in {'relocation-info', 'relocate-original'}:
        return relocate(root, request)
    if request['action'] in {'source-read', 'source-put'}:
        return source(root, request)
    if request['action'] == 'inspect':
        return inspect(root)
    if request['action'] == 'config-read':
        name = request.get('file')
        if name not in READ_FILES:
            raise RequestError('unsupported config file')
        fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            data = read_fd(fd)
            return {'file': name, 'content': data.decode(), 'sha256': hashlib.sha256(data).hexdigest()}
        finally:
            os.close(fd)
    if request['action'] == 'media-probe':
        return media_probe(root, request)
    return {'status': 'read-only-policy-verified', 'checks': sandbox_query(root),
            'no_unlink_inheritance': sandbox_query(root, NO_UNLINK_PROFILE),
            'render_enabled': False, 'note': 'Policy query is not a retention audit or permission to attempt deletion.'}


def main():
    try:
        raw = sys.stdin.buffer.read(2 * MAX_BYTES + 1)
        if len(raw) > 2 * MAX_BYTES:
            raise RequestError('request exceeds limit')
        result = execute(json.loads(raw))
        print(json.dumps(result))
        if result.get('status') == 'deletion-stopped':
            return 77
        if result.get('status') == 'render-failed':
            return 2
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
