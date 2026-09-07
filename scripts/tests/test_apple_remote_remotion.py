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
    root = tmp_path / 'videos/remotion'
    (root / 'src').mkdir(parents=True)
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
