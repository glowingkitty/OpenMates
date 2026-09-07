"""Local proof for typed Mac source operations and retention.

Every file is a pytest temporary fixture on Linux. No remote transport or
rendering is performed. Source updates must preserve inodes and retained bytes;
unsupported capabilities must never create a human-deletion stop.
"""
# contract-test-file: tooling
import hashlib
import json

import pytest


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'openmates-marketing/videos/remotion'
    (root / 'src').mkdir(parents=True)
    git = root.parent.parent / '.git'
    git.mkdir()
    (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/glowingkitty/openmates-marketing.git')
    (root / 'src/example.tsx').write_text('old source')
    return root


def helper():
    import _apple_remotion_remote
    return _apple_remotion_remote


def test_update_preserves_inode_and_backup(project):
    m = helper()
    before = (project / 'src/example.tsx').stat().st_ino
    req = {'action': 'source-put', 'repo': str(project), 'file': 'src/example.tsx',
           'expected_sha256': hashlib.sha256(b'old source').hexdigest(), 'content': 'new'}
    out = m.execute(req)
    assert (project / 'src/example.tsx').stat().st_ino == before
    assert (project / 'src/example.tsx').read_text() == 'new'
    assert (project / out['retained_backup']).read_text() == 'old source'
    assert m.execute({**req, 'action': 'source-read'})['sha256'] == hashlib.sha256(b'new').hexdigest()


def test_exclusive_creation_and_stale_hash_never_overwrite(project):
    m = helper()
    req = {'action': 'source-put', 'repo': str(project), 'file': 'src/new/entry.tsx', 'expected_sha256': None, 'content': 'new'}
    assert m.execute(req)['status'] == 'created'
    with pytest.raises(FileExistsError):
        m.execute({**req, 'content': 'overwrite'})
    with pytest.raises(m.RequestError, match='changed'):
        m.execute({**req, 'expected_sha256': '0' * 64, 'content': 'overwrite'})
    assert (project / 'src/new/entry.tsx').read_text() == 'new'


@pytest.mark.parametrize('name', ['../secret.ts', 'src/../secret.ts', '/tmp/file.ts', 'node_modules/x.js', 'public/other.svg', 'src//file.ts'])
def test_paths_rejected_without_mutation(project, name):
    m = helper()
    with pytest.raises(m.RequestError):
        m.execute({'action': 'source-put', 'repo': str(project), 'file': name, 'expected_sha256': None, 'content': 'x'})


def test_symlink_rejected(project, tmp_path):
    m = helper()
    (project / 'src/link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        m.execute({'action': 'source-put', 'repo': str(project), 'file': 'src/link/out.ts', 'expected_sha256': None, 'content': 'x'})
    assert not (tmp_path / 'out.ts').exists()


def test_typed_command_is_exact_and_unknown_does_not_latch():
    import apple_no_delete_guard as guard
    guard.require_safe_command(guard.remotion_command())
    with pytest.raises(guard.UnsupportedRemoteOperation):
        guard.require_safe_command('python3 arbitrary.py')
    assert guard.active_stop() is None
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command('rm example')
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command(guard.remotion_command())


def test_probe_has_no_deletion_syscall_or_render_dispatch(project):
    m = helper()
    assert 'sandbox_check' in m.PROBE_CODE
    assert '.unlink(' not in m.PROBE_CODE and '.remove(' not in m.PROBE_CODE
    with pytest.raises(m.RequestError, match='unavailable'):
        m.execute({'action': 'sandbox-probe', 'repo': str(project)})


def test_typed_transport_keeps_source_as_json_data(monkeypatch, tmp_path):
    from test_apple_remote_native_debugging import load_apple_remote
    remote = load_apple_remote()
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'action': 'source-read', 'repo': '/example/videos/remotion', 'file': 'src/example.tsx'}))
    monkeypatch.setattr(remote, 'load_local_config', lambda: {})
    monkeypatch.setattr(remote, 'resolve_remote_config', lambda **kw: remote.RemoteConfig('example', None, 'test'))
    calls = []
    def run(argv, **kw):
        calls.append((argv, kw))
        import subprocess
        return subprocess.CompletedProcess(argv, 0, '{}', '')
    monkeypatch.setattr(remote.subprocess, 'run', run)
    assert remote.main(['remotion-op', '--request', str(request)]) == 0
    assert len(calls) == 1
    assert calls[0][0][-1] == remote.no_delete_guard.remotion_command()
    assert json.loads(calls[0][1]['input'])['file'] == 'src/example.tsx'


def test_inventory_is_scoped_and_reads_nested_manifest(project):
    m = helper()
    originals = project / m.MEDIA_ROOTS[0] / 'originals'
    originals.mkdir(parents=True)
    (originals / 'clip.mov').write_bytes(b'local fixture')
    (originals.parent / 'media-manifest.json').write_text('{"clips": []}')
    (originals / 'outside.mov').symlink_to(project / 'src/example.tsx')
    result = m.inspect(project)
    assert len(result['assets']) == 2
    assert result['manifests'][m.MEDIA_ROOTS[0] + '/media-manifest.json'] == {'clips': []}


@pytest.mark.parametrize('name', ['../clip.mov', '/tmp/clip.mov', 'src/example.tsx', 'input-media/announcement-video/../clip.mov'])
def test_media_path_rejects_escape_before_dispatch(project, monkeypatch, name):
    m = helper()
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: pytest.fail('remote process dispatched'))
    with pytest.raises(m.RequestError):
        m.media_probe(project, {'file': name})


def test_media_probe_requires_sandbox_and_fixed_readonly_arguments(project, monkeypatch):
    m = helper()
    original = project / m.MEDIA_ROOTS[0] / 'clip.mov'
    original.parent.mkdir(parents=True)
    original.write_bytes(b'local fixture')
    calls = []
    monkeypatch.setattr(m, 'sandbox_query', lambda root: calls.append('query'))
    real_is_file = m.Path.is_file
    monkeypatch.setattr(m.Path, 'is_file', lambda p: True if str(p) == '/opt/homebrew/bin/ffprobe' else real_is_file(p))
    def run(argv, **kw):
        calls.append(argv)
        return m.subprocess.CompletedProcess(argv, 0, '{}', '')
    monkeypatch.setattr(m.subprocess, 'run', run)
    m.media_probe(project, {'file': original.relative_to(project).as_posix()})
    assert calls[0] == 'query'
    assert calls[1][:4] == ['/usr/bin/sandbox-exec', '-p', m.PROBE_PROFILE, '/opt/homebrew/bin/ffprobe']
    assert calls[1][-1] == str(original)
    assert calls[1][calls[1].index('-protocol_whitelist') + 1] == 'file'


def test_config_read_rejects_credentials_and_symlinks(project):
    m = helper()
    (project / 'package.json').symlink_to(project / 'src/example.tsx')
    for name in ('.env', 'package.json'):
        with pytest.raises((m.RequestError, OSError)):
            m.execute({'action': 'config-read', 'repo': str(project), 'file': name})


@pytest.mark.parametrize('unlink_denied,expected_exit', [(True, 0), (False, 3)])
def test_policy_query_accepts_system_root_protection_but_requires_unlink_denial(project, monkeypatch, unlink_denied, expected_exit):
    import ctypes
    import sys
    from types import SimpleNamespace
    m = helper()
    class Check:
        def __call__(self, pid, operation, flags, path):
            if operation == b'file-read-data':
                return 0
            if operation == b'file-write-unlink':
                return int(unlink_denied)
            return int(path in (b'/', b'/Users'))
    monkeypatch.setattr(ctypes, 'CDLL', lambda name: SimpleNamespace(sandbox_check=Check()))
    monkeypatch.setattr(sys, 'argv', ['-c', str(project), m.PROBE_CODE, '0', '2'])
    with pytest.raises(SystemExit) as stop:
        exec(m.PROBE_CODE, {})
    assert stop.value.code == expected_exit


@pytest.fixture
def relocation(project):
    m = helper()
    name = 'openmates_is_better.mov'
    src = project / m.MEDIA_ROOTS[1] / name
    dst = project / m.MEDIA_ROOTS[0] / 'originals' / name
    src.parent.mkdir(parents=True)
    dst.parent.mkdir(parents=True)
    src.write_bytes(b'local fixture, never Mac footage')
    return project, name, src, dst


def test_relocation_preserves_identity_and_exact_paths_with_local_double(relocation, monkeypatch):
    m = helper()
    root, name, src, dst = relocation
    info = m.execute({'action': 'relocation-info', 'repo': str(root), 'file': name})
    calls = []
    def rename(source_dir, filename, destination_dir):
        calls.append(filename)
        assert not dst.exists()
        m.os.rename(filename, filename, src_dir_fd=source_dir, dst_dir_fd=destination_dir)
    monkeypatch.setattr(m, 'rename_exclusive', rename)
    result = m.execute({'action': 'relocate-original', 'repo': str(root), 'file': name, 'expected': info['identity']})
    assert calls == [name]
    assert not src.exists() and dst.exists()
    assert result['verified_identity'] == info['identity']
    assert dst.stat().st_ino == info['identity']['inode']


@pytest.mark.parametrize('scenario', ['destination', 'symlink', 'mismatch', 'escape', 'cross-device'])
def test_relocation_rejects_before_rename(relocation, monkeypatch, scenario):
    from types import SimpleNamespace
    m = helper()
    root, name, src, dst = relocation
    monkeypatch.setattr(m, 'rename_exclusive', lambda *a: pytest.fail('rename dispatched'))
    request = {'action': 'relocate-original', 'repo': str(root), 'file': name, 'expected': {}}
    if scenario == 'destination':
        dst.write_bytes(b'preserve existing')
    elif scenario == 'symlink':
        # Rename this Linux fixture aside; no Mac fixture or transport exists.
        original = src.with_suffix('.retained')
        src.rename(original)
        src.symlink_to(original)
    elif scenario == 'escape':
        request['file'] = '../' + name
    elif scenario == 'cross-device':
        target_inode = dst.parent.stat().st_ino
        real = m.os.fstat
        monkeypatch.setattr(m.os, 'fstat', lambda fd: SimpleNamespace(st_dev=real(fd).st_dev + 1) if real(fd).st_ino == target_inode else real(fd))
    with pytest.raises((m.RequestError, OSError)):
        m.execute(request)
    assert src.exists()


def test_mac_rename_uses_exclusive_primitive_without_fallback(monkeypatch):
    from types import SimpleNamespace
    m = helper()
    calls = []
    class Rename:
        def __call__(self, *args):
            calls.append(args)
            return -1
    monkeypatch.setattr(m.sys, 'platform', 'darwin')
    monkeypatch.setattr(m.ctypes, 'CDLL', lambda *a, **kw: SimpleNamespace(renameatx_np=Rename()))
    monkeypatch.setattr(m.ctypes, 'get_errno', lambda: 17)
    with pytest.raises(FileExistsError):
        m.rename_exclusive(10, 'openmates_is_better.mov', 11)
    assert calls == [(10, b'openmates_is_better.mov', 11, b'openmates_is_better.mov', 0x34)]


def test_native_stopped_child_persists_stop_and_kills_group(tmp_path, monkeypatch):
    import io
    m = helper()
    class Child:
        pid = 1234
        stdin = io.BytesIO()
        def wait(self, timeout):
            return 0
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **kw: Child())
    monkeypatch.setattr(m, 'process_group_states', lambda group: [{'pid': 1235, 'state': 'T'}])
    killed = []
    monkeypatch.setattr(m.os, 'killpg', lambda *args: killed.append(args))
    marker = tmp_path / 'task.stop.json'
    result = m.observed_process(['fake'], tmp_path, input_data=b'{}', env={}, task_stop=marker)
    assert result['status'] == 'deletion-stopped'
    assert marker.is_file() and (tmp_path / 'stop.json').is_file()
    assert killed == [(1234, m.signal.SIGKILL)]


def test_remote_stop_blocks_other_typed_operations_after_interruption(project):
    m = helper()
    task = 'isolated-test-task'
    marker = project / '.apple-remote/stops' / ('task-' + hashlib.sha256(task.encode()).hexdigest() + '.stop.json')
    marker.parent.mkdir(parents=True)
    marker.write_text('{"reason":"native deletion blocked"}')
    for action in ('inspect', 'source-read', 'render-check', 'relocate-original'):
        result = m.execute({'action': action, 'repo': str(project), '_task_identity': task,
                            'confirmed': True, 'human_response': 'I did it'})
        assert result['status'] == 'deletion-stopped'
        assert marker.is_file()


def test_render_transport_latches_before_alternate_call(monkeypatch, tmp_path):
    from test_apple_remote_native_debugging import load_apple_remote
    remote = load_apple_remote()
    request = tmp_path / 'render-request.json'
    request.write_text(json.dumps({'action': 'render-check', 'repo': '/example/videos/remotion', '_task_identity': 'forged'}))
    monkeypatch.setattr(remote, 'load_local_config', lambda: {})
    monkeypatch.setattr(remote, 'resolve_remote_config', lambda **kw: remote.RemoteConfig('example', None, 'test'))
    calls = []
    def run(argv, **kw):
        calls.append(json.loads(kw['input']))
        return remote.subprocess.CompletedProcess(argv, 77, '{"status":"deletion-stopped"}', '')
    monkeypatch.setattr(remote.subprocess, 'run', run)
    with pytest.raises(remote.no_delete_guard.MacDeletionStop):
        remote.main(['remotion-op', '--request', str(request)])
    assert calls[0]['_task_identity'] != 'forged'
    with pytest.raises(remote.no_delete_guard.MacDeletionStop):
        remote.main(['status'])
    assert len(calls) == 1


def test_separate_browser_denial_stops_before_frame_or_encoder(tmp_path, monkeypatch):
    m = helper()
    calls = []
    monkeypatch.setattr(m, 'observed_process', lambda *a, **kw: {'status': 'bundle-ready', 'bundle': str(tmp_path / 'bundle')})
    class Browser:
        pid = 9876
        def poll(self):
            return -m.signal.SIGKILL
        def wait(self, timeout):
            return -m.signal.SIGKILL
    def start(argv, **kw):
        calls.append(argv)
        return Browser()
    monkeypatch.setattr(m.subprocess, 'Popen', start)
    monkeypatch.setattr(m.os, 'killpg', lambda *a: None)
    stop = tmp_path / 'task.stop.json'
    result = m.staged_render_check(tmp_path, tmp_path, m.Path('/node'), m.Path('/chrome'), m.Path('/encoder'), {}, stop)
    assert result['status'] == 'deletion-stopped' and stop.is_file()
    assert len(calls) == 1
    assert calls[0][:2] == ['/usr/bin/sandbox-exec', '-p']
    assert 'deny file-write-unlink' in calls[0][2] and 'deny process-fork' in calls[0][2]


def test_render_report_rejects_path_escape(project):
    m = helper()
    with pytest.raises(m.RequestError):
        m.render_report(project, {'run': '../another-run'})
